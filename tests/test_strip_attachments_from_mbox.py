"""Covers MIME-structure preservation and exact resume in strip_attachments_from_mbox.py."""

import base64
import csv
import email
import hashlib
import mailbox
import subprocess
import sys
from email import policy
from pathlib import Path

import mbox_builder as mb

SCRIPT = Path(__file__).resolve().parent.parent / "strip_attachments_from_mbox.py"


def run_strip(mbox_path: Path, out_mbox: Path, inventory: Path, checkpoint: Path):
    """Run the stripper as the user runs it."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--input-mbox", str(mbox_path),
         "--output-mbox", str(out_mbox),
         "--attachment-csv", str(inventory),
         "--checkpoint-file", str(checkpoint)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def read_inventory(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_first_message(out_mbox: Path):
    """Parse the first message out of a written mbox, separator line removed."""
    raw = out_mbox.read_bytes().split(b"\n", 1)[1]
    return email.message_from_bytes(raw, policy=policy.default)


def structure(msg):
    """Return the MIME tree as nested content types."""
    if msg.is_multipart():
        return [msg.get_content_type()] + [structure(p) for p in msg.get_payload()]
    return msg.get_content_type()


def test_attachment_is_removed_and_inventoried(tmp_path):
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.attachment_message(payload=b"12345")])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    assert len(rows) == 1
    assert rows[0]["Filename"] == "doc.bin"
    assert rows[0]["Size"] == "5"
    assert b"attachment-bytes" not in out.read_bytes()


def test_nested_containers_survive_stripping(tmp_path):
    """Re-attaching surviving leaves at the top level flattened the tree.

    A multipart/alternative inside a multipart/mixed came back as two sibling
    parts, so a reader rendered the plain and HTML versions one after the other
    instead of choosing between them.
    """
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.nested_message()])
    out = tmp_path / "out.mbox"
    run_strip(mbox, out, tmp_path / "inv.csv", tmp_path / "cp.json")

    assert structure(parse_first_message(out)) == [
        "multipart/mixed",
        ["multipart/alternative", "text/plain", "text/html"],
    ]


def test_resume_keeps_the_inventory_written_before_the_interruption(tmp_path):
    """The inventory was rebuilt from an in-memory list at the end of every run.

    A resumed run therefore replaced the whole CSV with only the attachments it
    saw after the resume point, destroying the record of everything stripped
    earlier while the files themselves stayed gone from the output.
    """
    first_half = [mb.attachment_message(mid="att1", filename="first.bin", payload=b"first")]
    both = first_half + [mb.attachment_message(mid="att2", filename="second.bin", payload=b"second")]

    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    cp = tmp_path / "cp.json"

    # Run against the first message only, exactly as an interrupted run would leave things.
    partial = mb.write_mbox(tmp_path / "in.mbox", first_half)
    run_strip(partial, out, inv, cp)
    assert [r["Filename"] for r in read_inventory(inv)] == ["first.bin"]

    # Resume against the full archive.
    full = mb.write_mbox(tmp_path / "in.mbox", both)
    stdout = run_strip(full, out, inv, cp)
    assert "Resuming from message 2" in stdout
    assert [r["Filename"] for r in read_inventory(inv)] == ["first.bin", "second.bin"]


def test_resumed_output_matches_an_uninterrupted_run(tmp_path):
    """Resume must be exactly-once: same bytes as if the run had never stopped."""
    messages = [
        mb.attachment_message(mid="att1", filename="first.bin", payload=b"first"),
        mb.attachment_message(mid="att2", filename="second.bin", payload=b"second"),
        mb.plain_message(mid="tail", body="No attachment here."),
    ]

    clean_out = tmp_path / "clean.mbox"
    clean_inv = tmp_path / "clean.csv"
    full = mb.write_mbox(tmp_path / "full.mbox", messages)
    run_strip(full, clean_out, clean_inv, tmp_path / "clean.json")

    resumed_out = tmp_path / "resumed.mbox"
    resumed_inv = tmp_path / "resumed.csv"
    cp = tmp_path / "resumed.json"
    partial = mb.write_mbox(tmp_path / "partial.mbox", messages[:1])
    run_strip(partial, resumed_out, resumed_inv, cp)
    run_strip(mb.write_mbox(partial, messages), resumed_out, resumed_inv, cp)

    assert resumed_inv.read_bytes() == clean_inv.read_bytes()
    assert resumed_out.read_bytes() == clean_out.read_bytes()


def test_checkpoint_without_byte_lengths_restarts_instead_of_duplicating(tmp_path):
    """A checkpoint from before exact resume cannot be trusted, so the run starts over."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.attachment_message(payload=b"12345")])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    cp = tmp_path / "cp.json"

    run_strip(mbox, out, inv, cp)
    cp.write_text("1", encoding="utf-8")  # the old bare-integer format
    stdout = run_strip(mbox, out, inv, cp)

    assert "predates exact resume" in stdout
    assert len(read_inventory(inv)) == 1


def single_part_attachment_message(mid="singleatt", filename="invoice.pdf", payload=b"single-attachment-bytes",
                                    date="Fri, 09 Jan 2026 09:00:00 +0000", subject=None):
    """A single-part message that is itself an attachment, with no multipart wrapper.

    This is the shape `mbox_builder.attachment_message` does not cover: the whole
    message body is the attachment, so there is no multipart/mixed container and no
    separate text part.
    """
    encoded = base64.b64encode(payload).decode()
    subject = subject or f"Single part attachment {mid}"
    return f"""{mb.SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: {subject}
Content-Type: application/pdf; name="{filename}"
Content-Disposition: attachment; filename="{filename}"
Content-Transfer-Encoding: base64

{encoded}
"""


def test_single_part_attachment_is_inventoried_with_decoded_size_and_hash(tmp_path):
    """A non-multipart message whose entire body is an attachment must still be inventoried.

    Size and SHA-256 must be computed over the decoded (raw) bytes, not the
    base64-encoded bytes on the wire.
    """
    payload = b"single-attachment-bytes"
    msg_text = single_part_attachment_message(payload=payload)
    mbox = mb.write_mbox(tmp_path / "in.mbox", [msg_text])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    assert len(rows) == 1
    assert rows[0]["Filename"] == "invoice.pdf"
    assert rows[0]["Size"] == str(len(payload))
    assert rows[0]["SHA256"] == hashlib.sha256(payload).hexdigest()


def test_single_part_attachment_is_replaced_with_placeholder_and_headers_preserved(tmp_path):
    """The stripped copy keeps the message, swapping its body for a placeholder.

    It must parse as text/plain with a utf-8 charset, carry no Content-Disposition
    header and no filename/name parameter, and its Subject/From/Date/Message-ID
    headers must be byte-identical to the input.
    """
    payload = b"single-attachment-bytes"
    msg_text = single_part_attachment_message(payload=payload, mid="singleatt2")
    mbox = mb.write_mbox(tmp_path / "in.mbox", [msg_text])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    stripped = parse_first_message(out)

    assert stripped.get_content_type() == "text/plain"
    assert (stripped.get_content_charset() or "").lower() == "utf-8"
    assert stripped["Content-Disposition"] is None
    assert stripped.get_filename() is None
    assert stripped.get_param("name") is None

    expected_body = (
        f"[attachment removed: {rows[0]['Filename']}, {rows[0]['Size']} bytes, "
        f"sha256 {rows[0]['SHA256']}]"
    )
    body = stripped.get_payload(decode=True).decode("utf-8").rstrip("\n")
    assert body == expected_body

    original = email.message_from_string(msg_text.split("\n", 1)[1], policy=policy.default)
    for header in ("Subject", "From", "Date", "Message-ID"):
        assert stripped[header] == original[header]


def test_single_part_attachment_message_count_matches_input(tmp_path):
    """The stripped mbox keeps the same message count, including the replaced one."""
    messages = [
        single_part_attachment_message(mid="singleatt3"),
        mb.plain_message(mid="tail2", body="No attachment here."),
    ]
    mbox = mb.write_mbox(tmp_path / "in.mbox", messages)
    out = tmp_path / "out.mbox"
    run_strip(mbox, out, tmp_path / "inv.csv", tmp_path / "cp.json")

    inbox_in = mailbox.mbox(str(mbox))
    inbox_out = mailbox.mbox(str(out))
    assert len(list(inbox_in)) == len(list(inbox_out)) == 2


def test_ordinary_single_part_message_passes_through_unchanged(tmp_path):
    """A single-part message with no filename and no Content-Disposition is untouched."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.plain_message(mid="untouched", body="Just an ordinary email.")])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    assert read_inventory(inv) == []
    stripped = parse_first_message(out)
    assert stripped.get_payload(decode=True).decode("utf-8").rstrip("\n") == "Just an ordinary email."


def nonascii_filename_single_part_message(mid="nonascii", date="Wed, 14 Jan 2026 09:00:00 +0000",
                                           payload=b"nonascii-bytes"):
    """A single-part attachment whose filename is a literal (raw, unencoded) non-ASCII string.

    The whole Content-Disposition header carries a non-ASCII byte on the wire, so
    BytesParser under compat32 parses it to a Header object, and the decoded
    filename itself is non-ASCII text that must survive into the placeholder.
    """
    encoded = base64.b64encode(payload).decode()
    return f"""{mb.SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: Non ASCII filename
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="café.pdf"
Content-Transfer-Encoding: base64

{encoded}
"""


def rfc2231_filename_single_part_message(mid="rfc2231", date="Sat, 10 Jan 2026 09:00:00 +0000",
                                          payload=b"euro-rate-bytes"):
    """A single-part attachment with an RFC 2231 encoded filename parameter.

    The Content-Disposition header is pure ASCII on the wire; get_filename()
    decodes it to a filename containing a non-ASCII character (a euro sign).
    """
    encoded = base64.b64encode(payload).decode()
    return f"""{mb.SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: RFC 2231 filename
Content-Type: application/octet-stream
Content-Disposition: attachment; filename*=UTF-8''%E2%82%ACrate.pdf
Content-Transfer-Encoding: base64

{encoded}
"""


def eightbit_disposition_single_part_message(mid="eightbit", date="Sun, 11 Jan 2026 09:00:00 +0000",
                                              payload=b"eightbit-bytes"):
    """A single-part attachment whose Content-Disposition header carries a raw 8-bit
    (unencoded) non-ASCII byte outside the filename, so it parses to a Header object.
    """
    encoded = base64.b64encode(payload).decode()
    return f"""{mb.SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: Eight bit disposition
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="invoice.pdf"; x-note="café"
Content-Transfer-Encoding: base64

{encoded}
"""


def single_part_attachment_no_filename_message(mid="noname", date="Mon, 12 Jan 2026 09:00:00 +0000",
                                                payload=b"noname-bytes"):
    """A single-part attachment with Content-Disposition: attachment and no filename param."""
    encoded = base64.b64encode(payload).decode()
    return f"""{mb.SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: No filename attachment
Content-Type: application/octet-stream
Content-Disposition: attachment
Content-Transfer-Encoding: base64

{encoded}
"""


def crlf_filename_single_part_message(mid="crlf", date="Tue, 13 Jan 2026 09:00:00 +0000",
                                       payload=b"crlf-bytes"):
    """A single-part attachment whose filename decodes to text containing CR, LF, and "]".

    The control characters and bracket arrive via RFC 2231 percent-encoding, so the
    header line on the wire stays well-formed; only the decoded filename is hostile.
    """
    encoded = base64.b64encode(payload).decode()
    return f"""{mb.SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: CRLF filename
Content-Type: application/octet-stream
Content-Disposition: attachment; filename*=UTF-8''evil%0D%0A%5Dtail.pdf
Content-Transfer-Encoding: base64

{encoded}
"""


def single_part_text_with_filename_message(mid="textfilename", date="Thu, 15 Jan 2026 09:00:00 +0000",
                                            body="Just a text part with a filename param."):
    """A single-part text/plain message that also carries a filename parameter.

    is_attachment_part would flag this (filename present), but the maintype is
    text, so it must be exempt and pass through untouched, as on master.
    """
    return f"""{mb.SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: Text with filename
Content-Type: text/plain; charset="utf-8"; name="notes.txt"
Content-Disposition: attachment; filename="notes.txt"

{body}
"""


def test_single_part_attachment_with_literal_nonascii_filename_does_not_crash(tmp_path):
    """A raw, non-ASCII filename must not raise during flattening (blocker: UnicodeEncodeError)
    or during attachment detection (blocker: AttributeError on a Header object).

    compat32 has no way to know the source charset of a raw 8-bit header, so it
    decodes each non-ASCII byte independently as 'unknown-8bit' and the filename
    comes back with the accented byte replaced by U+FFFD; the fix under test is
    that this mojibake round-trips into the placeholder rather than crashing.
    """
    mbox = mb.write_mbox(tmp_path / "in.mbox", [nonascii_filename_single_part_message()])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    assert len(rows) == 1
    expected_filename = "caf��.pdf"
    assert rows[0]["Filename"] == expected_filename

    stripped = parse_first_message(out)
    body = stripped.get_payload(decode=True).decode("utf-8").rstrip("\n")
    assert body == f"[attachment removed: {expected_filename}, {rows[0]['Size']} bytes, sha256 {rows[0]['SHA256']}]"


def test_single_part_attachment_with_rfc2231_filename_does_not_crash(tmp_path):
    """An RFC 2231 encoded filename decodes to non-ASCII text that must survive flattening."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [rfc2231_filename_single_part_message()])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    assert len(rows) == 1
    assert rows[0]["Filename"] == "€rate.pdf"

    stripped = parse_first_message(out)
    body = stripped.get_payload(decode=True).decode("utf-8").rstrip("\n")
    assert body == f"[attachment removed: €rate.pdf, {rows[0]['Size']} bytes, sha256 {rows[0]['SHA256']}]"
    # The flattened bytes must round-trip through the parser to the same text, not
    # just avoid raising.
    assert (stripped.get_content_charset() or "").lower() == "utf-8"


def test_single_part_attachment_with_eightbit_disposition_does_not_crash(tmp_path):
    """A raw 8-bit Content-Disposition header must not raise AttributeError in is_attachment_part."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [eightbit_disposition_single_part_message()])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    assert len(rows) == 1
    assert rows[0]["Filename"] == "invoice.pdf"


def test_single_part_attachment_with_no_filename_uses_unnamed(tmp_path):
    """No filename parameter at all falls back to 'unnamed' in the placeholder."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [single_part_attachment_no_filename_message()])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    assert len(rows) == 1
    assert rows[0]["Filename"] is None or rows[0]["Filename"] == ""

    stripped = parse_first_message(out)
    body = stripped.get_payload(decode=True).decode("utf-8").rstrip("\n")
    assert body == f"[attachment removed: unnamed, {rows[0]['Size']} bytes, sha256 {rows[0]['SHA256']}]"


def test_crlf_and_bracket_in_filename_are_escaped_in_placeholder(tmp_path):
    """CR, LF, and "]" in a filename must be escaped in the placeholder text, though the
    inventory row keeps the true filename."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [crlf_filename_single_part_message()])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    assert len(rows) == 1
    assert rows[0]["Filename"] == "evil\r\n]tail.pdf"

    stripped = parse_first_message(out)
    body = stripped.get_payload(decode=True).decode("utf-8").rstrip("\n")
    assert body == f"[attachment removed: evil\\r\\n\\]tail.pdf, {rows[0]['Size']} bytes, sha256 {rows[0]['SHA256']}]"


def test_single_part_text_message_with_filename_param_passes_through_unchanged(tmp_path):
    """A single-part text/plain message with a filename param is exempt, exactly as on master."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [single_part_text_with_filename_message()])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    assert read_inventory(inv) == []
    stripped = parse_first_message(out)
    assert stripped.get_content_type() == "text/plain"
    assert stripped.get_filename() == "notes.txt"
    body = stripped.get_payload(decode=True).decode("utf-8").rstrip("\n")
    assert body == "Just a text part with a filename param."


def test_header_order_of_other_headers_is_unchanged(tmp_path):
    """Message-ID, Date, From, To, Subject keep their original relative order."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [single_part_attachment_message(mid="orderchk")])
    out = tmp_path / "out.mbox"
    run_strip(mbox, out, tmp_path / "inv.csv", tmp_path / "cp.json")

    stripped = parse_first_message(out)
    other_headers = [k for k in stripped.keys()
                      if k not in ("Content-Type", "Content-Disposition",
                                   "Content-Transfer-Encoding", "MIME-Version")]
    assert other_headers == ["Message-ID", "Date", "From", "To", "Subject"]


def test_resumed_single_part_attachment_run_does_not_duplicate_the_row(tmp_path):
    """A resumed run over a single-part-attachment message must not duplicate its inventory row."""
    messages = [
        single_part_attachment_message(mid="resumeatt1"),
        mb.plain_message(mid="resumetail", body="No attachment here."),
    ]

    clean_out = tmp_path / "clean.mbox"
    clean_inv = tmp_path / "clean.csv"
    full = mb.write_mbox(tmp_path / "full.mbox", messages)
    run_strip(full, clean_out, clean_inv, tmp_path / "clean.json")

    resumed_out = tmp_path / "resumed.mbox"
    resumed_inv = tmp_path / "resumed.csv"
    cp = tmp_path / "resumed.json"
    partial = mb.write_mbox(tmp_path / "partial.mbox", messages[:1])
    run_strip(partial, resumed_out, resumed_inv, cp)
    run_strip(mb.write_mbox(partial, messages), resumed_out, resumed_inv, cp)

    assert len(read_inventory(resumed_inv)) == 1
    assert resumed_inv.read_bytes() == clean_inv.read_bytes()
    assert resumed_out.read_bytes() == clean_out.read_bytes()


def single_part_message_with_headers(content_type_lines, mid="hdrs",
                                     date="Tue, 13 Jan 2026 09:00:00 +0000",
                                     payload=bytes(range(256))):
    """A single-part base64 attachment whose Content-Type lines are given verbatim."""
    encoded = base64.b64encode(payload).decode()
    return f"""{mb.SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: Header variants
{content_type_lines}Content-Disposition: attachment; filename="a.pdf"
Content-MD5: Q2hlY2sgSW50ZWdyaXR5IQ==
Content-Transfer-Encoding: base64

{encoded}
"""


def test_attachment_with_missing_or_invalid_content_type_is_still_stripped(tmp_path):
    """compat32 reports text/plain for a missing or invalid Content-Type; only a declared
    text/* type is exempt, so these attachments are still inventoried and replaced."""
    messages = [
        single_part_message_with_headers("", mid="missing"),
        single_part_message_with_headers("Content-Type: application\n", mid="invalid"),
    ]
    mbox = mb.write_mbox(tmp_path / "in.mbox", messages)
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    assert [r["Filename"] for r in rows] == ["a.pdf", "a.pdf"]
    assert out.read_bytes().count(b"[attachment removed: a.pdf,") == 2


def test_placeholder_is_one_unwrapped_line_that_greps_to_the_inventory_hash(tmp_path):
    """The SHA-256 from the inventory appears whole in the raw stripped mbox, and the
    now-false Content-MD5 and every duplicate Content-Type are gone."""
    ct = "Content-Type: application/pdf\nContent-Type: image/png\n"
    mbox = mb.write_mbox(tmp_path / "in.mbox", [single_part_message_with_headers(ct)])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    raw = out.read_bytes()
    line = f"[attachment removed: a.pdf, {rows[0]['Size']} bytes, sha256 {rows[0]['SHA256']}]"
    assert line.encode("ascii") in raw
    stripped = parse_first_message(out)
    assert stripped.get_all("Content-Type") == ['text/plain; charset="utf-8"']
    assert stripped.get("Content-MD5") is None
