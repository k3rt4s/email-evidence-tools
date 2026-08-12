"""Runs a minimal in-process IMAP server so the labeler's full session can be tested without a live mailbox.

Speaks just enough of RFC 3501 for `label_matching_emails_via_imap.py`: greeting,
CAPABILITY, LOGIN, SELECT, CREATE, UID SEARCH, UID FETCH and UID COPY. It records
every command it receives, so a test can assert what the client actually sent
rather than only what it returned.
"""

import socket
import threading

CRLF = b"\r\n"


def _redact(line: str) -> str:
    """Blank the credentials out of a recorded command line.

    LOGIN carries the password in band. A test helper that keeps a verbatim
    transcript would put it in an assertion message, a pytest failure dump, or
    CI output the moment a test breaks.
    """
    parts = line.split()
    if len(parts) > 2 and parts[1].upper() in ("LOGIN", "AUTHENTICATE"):
        return " ".join(parts[:3] + ["<redacted>"] * (len(parts) - 3))
    return line


class StubIMAPServer:
    """A one-connection IMAP server backed by a dict of {uid: raw message bytes}."""

    def __init__(self, messages, search_results=None):
        self.messages = {str(k): v.encode() if isinstance(v, str) else v
                         for k, v in messages.items()}
        # UIDs returned for a SEARCH, defaulting to every message held.
        self.search_results = search_results or sorted(self.messages, key=int)
        self.commands = []          # every command line received, decoded
        self.copied = []            # (uid, mailbox) for each UID COPY
        self.created = []           # mailbox names passed to CREATE
        self.logins = []            # usernames only; passwords are never recorded
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.host, self.port = self._sock.getsockname()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._stop = threading.Event()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(conn,), daemon=True).start()

    def _session(self, conn):
        """Handle one client connection until LOGOUT or disconnect."""
        with conn, conn.makefile("rwb") as stream:
            stream.write(b"* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] stub ready" + CRLF)
            stream.flush()
            while True:
                line = stream.readline()
                if not line:
                    return
                self.commands.append(_redact(line.decode("utf-8", "replace").strip()))
                try:
                    if not self._dispatch(stream, line):
                        return
                except Exception:
                    return

    def _dispatch(self, stream, line) -> bool:
        """Answer one command. Returns False when the session should close."""
        parts = line.decode("utf-8", "replace").strip().split()
        tag, command = parts[0], parts[1].upper()
        args = parts[2:]

        def send(*lines):
            for item in lines:
                stream.write(item if isinstance(item, bytes) else item.encode())
                stream.write(CRLF)
            stream.flush()

        if command == "CAPABILITY":
            send("* CAPABILITY IMAP4rev1 AUTH=PLAIN", f"{tag} OK CAPABILITY completed")
        elif command == "LOGIN":
            self.logins.append(args[0].strip('"'))
            send(f"{tag} OK LOGIN completed")
        elif command == "SELECT":
            send(f"* {len(self.messages)} EXISTS",
                 "* OK [UIDVALIDITY 1] UIDs valid",
                 f"{tag} OK [READ-WRITE] SELECT completed")
        elif command == "CREATE":
            self.created.append(" ".join(args).strip('"'))
            send(f"{tag} OK CREATE completed")
        elif command == "UID":
            return self._dispatch_uid(send, tag, args)
        elif command == "LOGOUT":
            send("* BYE stub closing", f"{tag} OK LOGOUT completed")
            return False
        else:
            send(f"{tag} OK {command} completed")
        return True

    def _dispatch_uid(self, send, tag, args) -> bool:
        """Answer the UID SEARCH / FETCH / COPY forms the labeler uses."""
        sub = args[0].upper()
        if sub == "SEARCH":
            send("* SEARCH " + " ".join(self.search_results),
                 f"{tag} OK UID SEARCH completed")
        elif sub == "FETCH":
            uid = args[1]
            raw = self.messages.get(uid, b"")
            send(f"* 1 FETCH (UID {uid} RFC822 {{{len(raw)}}}".encode() + CRLF + raw + b")",
                 f"{tag} OK UID FETCH completed")
        elif sub == "COPY":
            self.copied.append((args[1], " ".join(args[2:]).strip('"')))
            send(f"{tag} OK [COPYUID 1 {args[1]} {args[1]}] UID COPY completed")
        else:
            send(f"{tag} OK UID {sub} completed")
        return True
