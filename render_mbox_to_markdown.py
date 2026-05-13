"""
render_mbox_to_markdown.py
===========================
Project : email-evidence-tools
Purpose : Render an mbox file as a single Markdown document, chronological by
          Date header (UTC), with full forensic headers, plain-text body, and
          an attachment manifest. Designed for legal-case review where every
          message must be traceable back to its source mbox.

          For each message the renderer writes:
            - a numbered heading with ISO-8601 date and subject
            - a key/value metadata block (date, from, to, cc, message-id,
              source mbox, byte offset, sha-256 of the raw message)
            - the plain-text body (text/plain preferred; text/html stripped
              to text as a fallback)
            - a per-attachment table (filename, mime, size, sha-256)

          Attachment binaries are written to <output-dir>/attachments/ with
          collision-safe filenames, so the MD references each one by relative
          path. Messages with unparseable Date headers are appended in a
          final "Undated" section rather than silently dropped.

Inputs  : --mbox-file PATH          source mbox (typically the output of
                                    extract_messages_by_address.py)
          --output-dir DIR          where to write the MD + attachments
          --title TEXT (optional)   H1 title for the MD file
          --subject-line TEXT       (optional) summary line under the H1

Outputs : <output-dir>/<basename>.md           the rendered document
          <output-dir>/<basename>_messages.csv tabular index
          <output-dir>/attachments/            extracted attachment binaries
          <output-dir>/render_manifest.json    hashes + counts + metadata

Usage   : C:\\Code\\venvs\\email-evidence-tools\\Scripts\\python.exe \\
              .\\render_mbox_to_markdown.py \\
              --mbox-file ".\\path\\to\\input.mbox" \\
              --output-dir ".\\out"
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

# mbox separator at start of line: "From " + at least one non-space char.
FROM_SEP_RE = re.compile(rb"^From [^\s]", re.MULTILINE)


# -------------------------------------------------------------------------
# HTML -> text fallback (used only when no text/plain part is present)
# -------------------------------------------------------------------------

class _HtmlToText(HTMLParser):
    """Minimal HTML stripper that preserves line breaks and hyperlink URLs."""

    BLOCK_TAGS = {
        "p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "table", "thead", "tbody",
    }
    SKIP_TAGS = {"script", "style", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []
        self._skip_depth = 0
        self._last_link = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "a":
            for k, v in attrs:
                if k == "href":
                    self._last_link = v
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "a" and self._last_link:
            self._parts.append(f" <{self._last_link}>")
            self._last_link = None
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self):
        out = "".join(self._parts)
        # Strip trailing whitespace from each line (Outlook HTML often produces
        # "<p>&nbsp;</p>" which decodes to a line containing only   / spaces).
        out = "\n".join(line.rstrip() for line in out.splitlines())
        # Collapse runs of >2 blank lines down to 2.
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()


def html_to_text(html: str) -> str:
    p = _HtmlToText()
    try:
        p.feed(html)
        p.close()
    except Exception as e:
        return f"[html-to-text parse error: {e!r}]\n\n{html}"
    return p.text()


# -------------------------------------------------------------------------
# Mbox streaming
# -------------------------------------------------------------------------

def iter_mbox_messages(mbox_path: Path):
    """Yield (start_offset, raw_bytes) for each message in an mbox file."""
    CHUNK = 4 * 1024 * 1024
    with mbox_path.open("rb") as f:
        buf = bytearray()
        msg_start = 0
        in_message = False
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            buf.extend(chunk)
            while True:
                search_start = 0 if not in_message else 1
                m = FROM_SEP_RE.search(buf, search_start)
                if not m:
                    break
                sep_pos = m.start()
                if not in_message:
                    if sep_pos > 0:
                        del buf[:sep_pos]
                        msg_start += sep_pos
                    in_message = True
                    continue
                yield msg_start, bytes(buf[:sep_pos])
                del buf[:sep_pos]
                msg_start += sep_pos
        if in_message and buf:
            yield msg_start, bytes(buf)


# -------------------------------------------------------------------------
# Body + attachment extraction
# -------------------------------------------------------------------------

def extract_body(msg) -> tuple[str, str]:
    """Return (body_text, body_source) where body_source is one of
    'text/plain', 'text/html->stripped', or 'none'."""
    # email.policy.default's get_body returns the best body part by preference.
    try:
        plain_part = msg.get_body(preferencelist=("plain",))
    except Exception:
        plain_part = None
    if plain_part is not None:
        try:
            return plain_part.get_content().strip(), "text/plain"
        except Exception:
            pass

    try:
        html_part = msg.get_body(preferencelist=("html",))
    except Exception:
        html_part = None
    if html_part is not None:
        try:
            return html_to_text(html_part.get_content()), "text/html->stripped"
        except Exception as e:
            return f"[html body could not be decoded: {e!r}]", "text/html->error"

    # Fall back: walk parts and concatenate any text/* content we can decode.
    pieces = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ct = (part.get_content_type() or "").lower()
        if ct.startswith("text/"):
            try:
                pieces.append(part.get_content())
            except Exception:
                continue
    if pieces:
        return "\n\n".join(pieces).strip(), "text/walk"
    return "", "none"


def collect_attachments(msg):
    """Return a list of (filename, content_type, bytes) tuples for parts
    that look like attachments (have a filename or Content-Disposition attachment)."""
    out = []
    seen_idx = 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        cd = (part.get("Content-Disposition") or "").lower()
        ct = (part.get_content_type() or "").lower()
        is_attachment = bool(filename) or "attachment" in cd
        if not is_attachment:
            # Inline images: keep them as attachments anyway for evidence.
            if ct.startswith("image/") and "inline" in cd:
                pass
            else:
                continue
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:
            payload = b""
        if not filename:
            filename = f"part_{seen_idx:03d}"
        seen_idx += 1
        out.append((filename, ct or "application/octet-stream", payload))
    return out


# -------------------------------------------------------------------------
# Rendering helpers
# -------------------------------------------------------------------------

def safe_filename(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", s or "")
    s = s.strip(" .")
    return s[:120] or "unnamed"


def header_str(msg, name) -> str:
    vals = msg.get_all(name, [])
    if not vals:
        return ""
    return " ".join(str(v).replace("\r\n", " ").replace("\n", " ").strip() for v in vals)


def addrs_list(msg, *headers):
    raw = []
    for h in headers:
        for v in msg.get_all(h, []):
            raw.append(v)
    out = []
    for name, addr in getaddresses(raw):
        if addr:
            out.append(f"{name} <{addr}>" if name else addr)
    return out


def parse_date_utc(date_raw: str):
    if not date_raw:
        return None
    try:
        dt = parsedate_to_datetime(date_raw)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def fmt_kb(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    return f"{n/1024/1024:.2f} MB"


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------

def parse_args():
    ap = argparse.ArgumentParser(description="Render an mbox to a chronological Markdown evidence document.")
    ap.add_argument("--mbox-file", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--title", default=None,
                    help="H1 title for the MD file. Defaults to the mbox basename.")
    ap.add_argument("--subject-line", default=None,
                    help="One-line summary placed under the H1.")
    return ap.parse_args()


def main():
    args = parse_args()
    mbox_path = Path(args.mbox_file)
    out_dir   = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    att_dir   = out_dir / "attachments"
    att_dir.mkdir(exist_ok=True)

    basename  = mbox_path.stem
    md_path   = out_dir / f"{basename}.md"
    csv_path  = out_dir / f"{basename}_messages.csv"
    manifest_path = out_dir / "render_manifest.json"

    title = args.title or basename
    parser = BytesParser(policy=policy.default)

    # Pass 1: parse every message, keep enough state to sort and render.
    print(f"[render] reading {mbox_path}  ({mbox_path.stat().st_size / 1e6:.1f} MB)")
    records = []
    parse_errors = []
    for offset, raw in iter_mbox_messages(mbox_path):
        # Drop the leading "From " separator line before parsing.
        nl = raw.find(b"\n")
        msg_bytes = raw[nl + 1:] if nl != -1 else raw
        try:
            msg = parser.parsebytes(msg_bytes)
        except Exception as e:
            parse_errors.append({"byte_offset": offset, "error": repr(e)})
            continue
        date_raw = header_str(msg, "Date")
        dt = parse_date_utc(date_raw)
        records.append({
            "offset": offset,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_size": len(raw),
            "msg": msg,
            "date_utc": dt,
            "date_raw": date_raw,
            "message_id": (msg.get("Message-ID") or "").strip(),
        })

    print(f"[render] parsed {len(records)} messages ({len(parse_errors)} parse errors)")

    dated   = [r for r in records if r["date_utc"] is not None]
    undated = [r for r in records if r["date_utc"] is None]
    dated.sort(key=lambda r: (r["date_utc"], r["message_id"]))

    # Pass 2: write Markdown + CSV + attachments.
    with md_path.open("w", encoding="utf-8") as md, \
         csv_path.open("w", newline="", encoding="utf-8") as cf:

        cw = csv.writer(cf)
        cw.writerow([
            "n", "date_utc", "date_raw", "from", "to", "cc", "subject",
            "message_id", "raw_sha256", "attachment_count",
        ])

        md.write(f"# {title}\n\n")
        if args.subject_line:
            md.write(f"_{args.subject_line}_\n\n")
        md.write("## Provenance\n\n")
        md.write(f"- Source mbox: `{mbox_path}`\n")
        md.write(f"- Source size: {mbox_path.stat().st_size:,} bytes\n")
        md.write(f"- Source SHA-256: `{sha256_of_file(mbox_path)}`\n")
        md.write(f"- Rendered: {datetime.now(timezone.utc).isoformat()}\n")
        md.write(f"- Total messages: {len(records)}\n")
        md.write(f"- Dated (in chronological section): {len(dated)}\n")
        md.write(f"- Undated (appended at end): {len(undated)}\n")
        md.write(f"- Parse errors: {len(parse_errors)}\n\n")
        if dated:
            md.write(f"- Date range: {dated[0]['date_utc'].isoformat()}  →  "
                     f"{dated[-1]['date_utc'].isoformat()}\n\n")
        md.write("Each message is numbered. Attachments are extracted under "
                 "`attachments/<NNN>__<safe-filename>` and referenced by SHA-256.\n\n")
        md.write("---\n\n")

        md.write("## Messages (chronological)\n\n")
        total_attachments = 0
        for i, rec in enumerate(dated, start=1):
            n_str = f"{i:04d}"
            write_message(
                md=md, cw=cw, n=i, n_str=n_str,
                rec=rec, att_dir=att_dir,
            )
            total_attachments += rec["att_count"]

        if undated:
            md.write("\n---\n\n## Messages (undated)\n\n")
            for j, rec in enumerate(undated, start=1):
                n_str = f"U{j:04d}"
                write_message(
                    md=md, cw=cw, n=len(dated) + j, n_str=n_str,
                    rec=rec, att_dir=att_dir,
                )
                total_attachments += rec["att_count"]

        if parse_errors:
            md.write("\n---\n\n## Parse errors\n\n")
            md.write("These message regions could not be parsed and were skipped.\n\n")
            for pe in parse_errors:
                md.write(f"- byte offset {pe['byte_offset']:,}: `{pe['error']}`\n")

    md_sha = sha256_of_file(md_path)
    csv_sha = sha256_of_file(csv_path)

    manifest = {
        "rendered_utc": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "input_mbox": str(mbox_path),
        "input_mbox_sha256": sha256_of_file(mbox_path),
        "input_mbox_size": mbox_path.stat().st_size,
        "output_md": str(md_path),
        "output_md_sha256": md_sha,
        "output_csv": str(csv_path),
        "output_csv_sha256": csv_sha,
        "messages_total": len(records),
        "messages_dated": len(dated),
        "messages_undated": len(undated),
        "parse_errors": len(parse_errors),
        "attachments_total": total_attachments,
        "date_range_utc": (
            [dated[0]["date_utc"].isoformat(), dated[-1]["date_utc"].isoformat()]
            if dated else None
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[render] DONE")
    print(f"  md       : {md_path}")
    print(f"  csv      : {csv_path}")
    print(f"  manifest : {manifest_path}")
    print(f"  attachments : {total_attachments} files under {att_dir}")


def write_message(md, cw, n, n_str, rec, att_dir: Path):
    msg = rec["msg"]
    date_iso = rec["date_utc"].isoformat() if rec["date_utc"] else "(no date)"
    subject = header_str(msg, "Subject") or "(no subject)"
    from_   = ", ".join(addrs_list(msg, "From")) or header_str(msg, "From")
    to_     = ", ".join(addrs_list(msg, "To"))   or header_str(msg, "To")
    cc_     = ", ".join(addrs_list(msg, "Cc"))   or header_str(msg, "Cc")
    bcc_    = ", ".join(addrs_list(msg, "Bcc"))  or header_str(msg, "Bcc")
    reply_to = ", ".join(addrs_list(msg, "Reply-To")) or header_str(msg, "Reply-To")
    sender   = ", ".join(addrs_list(msg, "Sender")) or header_str(msg, "Sender")
    deliv    = ", ".join(addrs_list(msg, "Delivered-To")) or header_str(msg, "Delivered-To")
    message_id = rec["message_id"] or "(none)"
    in_reply_to = header_str(msg, "In-Reply-To")
    references  = header_str(msg, "References")
    mime_v      = header_str(msg, "MIME-Version")

    body, body_source = extract_body(msg)

    # Save attachments
    attachments = collect_attachments(msg)
    att_rows = []
    for k, (fname, ct, data) in enumerate(attachments, start=1):
        sha = hashlib.sha256(data).hexdigest()
        save_name = f"{n_str}__{k:02d}__{safe_filename(fname)}"
        save_path = att_dir / save_name
        try:
            save_path.write_bytes(data)
        except Exception as e:
            att_rows.append((fname, ct, len(data), sha, f"[write failed: {e!r}]"))
            continue
        att_rows.append((fname, ct, len(data), sha, save_name))
    rec["att_count"] = len(att_rows)

    # --- Markdown block ---
    md.write(f"### {n_str} — {date_iso} — {subject}\n\n")
    md.write("```yaml\n")
    md.write(f"n:              {n_str}\n")
    md.write(f"date_utc:       {date_iso}\n")
    md.write(f"date_header:    {rec['date_raw']}\n")
    md.write(f"from:           {from_}\n")
    md.write(f"to:             {to_}\n")
    if cc_:        md.write(f"cc:             {cc_}\n")
    if bcc_:       md.write(f"bcc:            {bcc_}\n")
    if reply_to:   md.write(f"reply_to:       {reply_to}\n")
    if sender:     md.write(f"sender:         {sender}\n")
    if deliv:      md.write(f"delivered_to:   {deliv}\n")
    md.write(f"subject:        {subject}\n")
    md.write(f"message_id:     {message_id}\n")
    if in_reply_to: md.write(f"in_reply_to:    {in_reply_to}\n")
    if references:  md.write(f"references:     {references}\n")
    if mime_v:      md.write(f"mime_version:   {mime_v}\n")
    md.write(f"source_offset:  {rec['offset']}\n")
    md.write(f"raw_size_bytes: {rec['raw_size']}\n")
    md.write(f"raw_sha256:     {rec['raw_sha256']}\n")
    md.write(f"body_source:    {body_source}\n")
    md.write("```\n\n")

    md.write("**Body**\n\n")
    if body:
        md.write("```text\n")
        # Escape any stray triple-backticks in body
        md.write(body.replace("```", "ʼʼʼ"))
        if not body.endswith("\n"):
            md.write("\n")
        md.write("```\n\n")
    else:
        md.write("_(no decodable text body)_\n\n")

    if att_rows:
        md.write(f"**Attachments ({len(att_rows)})**\n\n")
        md.write("| # | filename | mime | size | sha-256 | saved as |\n")
        md.write("|---|---|---|---|---|---|\n")
        for k, (fname, ct, size, sha, saved) in enumerate(att_rows, start=1):
            md.write(
                f"| {k} | `{fname}` | `{ct}` | {fmt_kb(size)} | "
                f"`{sha}` | `attachments/{saved}` |\n"
            )
        md.write("\n")

    md.write("---\n\n")

    cw.writerow([
        n_str, date_iso, rec["date_raw"], from_, to_, cc_,
        subject, message_id, rec["raw_sha256"], len(att_rows),
    ])


def sha256_of_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    main()
