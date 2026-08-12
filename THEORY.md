# email-evidence-tools theory

What a session needs to believe before it changes anything here. Not architecture and not a plan: this is the working mental model that the code does not say out loud. Format and pruning rules: `ai_development/docs/readme-standards.md` R10.

## Invariants

- Resume is a property of the outputs, not of the position. Both checkpointed tools record the byte length of every file they write alongside their place in the input, and truncate those files back to that length before appending. Any new output a resumable tool starts writing must join that record-and-truncate discipline. A file left out of it gains duplicates on every interrupted run, and nothing downstream can tell a duplicated evidence row from a real one.
- A checkpoint that carries no output byte lengths is refused, not resumed. Rescanning costs time; resuming from a stale position costs an exhibit that is wrong and looks right.
- The scanner normalizes once, then both matches and quotes from that same normalized text. Matching against whitespace-collapsed text while quoting from raw text silently discards every hit whose keyword crosses a line break: the term is in the body, in no sentence, and no row is written.
- A message body is not just its first `text/plain` part. HTML-only multipart mail is ordinary, and treating a missing plain part as an empty body means the message is scanned as blank and can never produce a hit no matter what it says.
- Attachment stripping prunes the MIME tree in place and keeps its containers. Collecting the surviving leaves and re-attaching them at the top level flattens a `multipart/alternative` into siblings, so a reader renders the plain and HTML versions one after the other and the evidence copy stops reading like the message that was sent.

## Load-bearing constraints

- Only `extract_messages_by_address.py` streams. `scan_mbox_for_evidence.py` and `strip_attachments_from_mbox.py` go through `mailbox.mbox`, which indexes the whole archive before yielding anything, and `render_mbox_to_markdown.py` holds every parsed message in memory because it sorts chronologically. On a large archive, run the extractor first and point the others at its much smaller output.
- The stripped mbox is a re-serialization, not a byte copy. Each message is rewritten through `BytesGenerator` and the `From` separator is synthetic, so digests taken over a stripped message do not match the source. Hash the original archive or the renderer's per-message SHA-256, never the stripped copy.
- The extractor's checkpoint holds byte offsets of `From` separator lines in one specific input, keyed by resolved path. Moving, appending to, or rewriting an input invalidates them, and the tool cannot detect that.
- This repository is public. Every default output path is either outside the tree or covered by `.gitignore`. Anything new that writes beside the code leaks real correspondence.

## Decisions that look wrong

- The extractor implements its own mbox splitter instead of using `mailbox.mbox`. That module builds a table of contents for the entire file before the first message comes back, which is precisely what a tens-of-gigabyte Thunderbird archive cannot afford.
- The IMAP labeler sends plaintext to loopback hosts by default. A local mail bridge listens without TLS, so demanding TLS everywhere would break the common case; every non-loopback host gets TLS, and plaintext to one requires saying so explicitly.
- The labeler applies its label with `COPY`. On a Gmail-style server that adds a label to the same message; elsewhere it places a second copy in a folder. Both are the intended outcome, which is why the tool names it "label or folder".

## Known soft spots

- A non-multipart message that is itself an attachment passes through the stripper untouched and is never inventoried. Only multipart messages are pruned.
- The scanner reads bodies only. A lure that lives entirely in the `Subject` header produces no hit.
- The keyword categories are a default set tuned for security-operations triage. They are meant to be edited per case, not trusted as delivered, and a case that needs different language will silently find nothing until they are changed.
