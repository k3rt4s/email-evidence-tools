# email-evidence-tools theory

What a session needs to believe before it changes anything here. Not architecture and not a plan: this is the working mental model that the code does not say out loud. Format and pruning rules: `ai_development/docs/readme-standards.md` R10.

## Invariants

- Resume is a property of the outputs, not of the position. Both checkpointed tools record the byte length of every file they write alongside their place in the input, and truncate those files back to that length before appending. Any new output a resumable tool starts writing must join that record-and-truncate discipline. A file left out of it gains duplicates on every interrupted run, and nothing downstream can tell a duplicated evidence row from a real one.
- A checkpoint that carries no output byte lengths is refused, not resumed. Rescanning costs time; resuming from a stale position costs an exhibit that is wrong and looks right.
- The scanner normalizes once, then both matches and quotes from that same normalized text. Matching against whitespace-collapsed text while quoting from raw text silently discards every hit whose keyword crosses a line break: the term is in the body, in no sentence, and no row is written.
- A message body is not just its first `text/plain` part. HTML-only multipart mail is ordinary, and treating a missing plain part as an empty body means the message is scanned as blank and can never produce a hit no matter what it says.
- Attachment stripping prunes the MIME tree in place and keeps its containers. Collecting the surviving leaves and re-attaching them at the top level flattens a `multipart/alternative` into siblings, so a reader renders the plain and HTML versions one after the other and the evidence copy stops reading like the message that was sent.

## Load-bearing constraints

- Only `extract_messages_by_address.py` streams. `scan_mbox_for_evidence.py` and `strip_attachments_from_mbox.py` instantiate `mailbox.mbox`, and `render_mbox_to_markdown.py` holds every parsed message in memory because it sorts chronologically. On a large archive, run the extractor first and point the others at its much smaller output.
- The stripped mbox is a re-serialization, not a byte copy. Each message is rewritten through `BytesGenerator` and the `From` separator is synthetic, so digests taken over a stripped message do not match the source. Use the original archive hash or the renderer's per-message SHA-256 when source identity matters.
- The extractor's checkpoint holds byte offsets of `From` separator lines in one specific input, keyed by resolved path. Moving, appending to, or rewriting an input invalidates them, and the tool cannot detect that.
- `imaplib` can report a refused command by returning `('NO', ...)`, not by raising. Any call whose result is discarded therefore succeeds as far as the code is concerned, which is how this tool once printed how many messages it had labeled after creating no folder and copying nothing. Check the response type of every command that matters. Related: a server can require a namespace prefix on a new mailbox, so `Labels/Evidence` is accepted where `Evidence` is refused, and Proton Bridge is one such server.
- `imaplib` does not validate TLS certificates unless it is handed a context that does. Both `IMAP4_SSL()` and `starttls()` fall back to `ssl._create_stdlib_context()`, which sets `check_hostname=False` and `verify_mode=CERT_NONE`, so a default connection is encrypted but unauthenticated and anything able to answer for the address can present its own certificate and take the password. Every TLS path here passes `ssl.create_default_context()` explicitly; never drop that argument on the assumption the library default is safe.
- This repository is public, and it is the kind of tool people run from inside a checkout. The extraction, stripping and scanning outputs default beside their inputs, and the renderer requires an explicit output directory, so routine runs do not write evidence into the current directory by accident. `.gitignore` is the second line of defence, not the first: a default that writes into the current directory puts real correspondence one `git add -A` away from a public push.

## Decisions that look wrong

- The extractor implements its own mbox splitter instead of using `mailbox.mbox`. It reads line by line and yields one raw message at a time, which is precisely what a tens-of-gigabyte Thunderbird archive needs.
- The IMAP labeler sends plaintext to loopback hosts by default. A local mail bridge listens without TLS, so demanding TLS everywhere would break the common case; every non-loopback host gets TLS, and plaintext to one requires saying so explicitly.
- The labeler applies its label with `COPY`. Depending on the server, that may behave like adding a label or placing a second copy in a folder. Both are the intended outcome, which is why the tool names it "label or folder".

## Known soft spots

- A non-multipart message that is itself an attachment passes through the stripper untouched and is never inventoried. Only multipart messages are pruned.
- The scanner reads the message body and the `Subject` header, and each row's `location` column names which one the hit came from. It reads no other header, so a lure that lives in a display name, a `Reply-To` or a `Received` line produces no hit.
- The keyword categories are a default set tuned for security-operations triage. They are meant to be edited per case, not trusted as delivered, and a case that needs different language will silently find nothing until they are changed.
