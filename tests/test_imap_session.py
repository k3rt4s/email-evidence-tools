"""Drives label_matching_emails_via_imap.py through a full session against a stub IMAP server.

The transport tests cover which mode is selected; these cover what the tool
actually does once connected: which messages it fetches, which it labels, what it
sends to the server, and what it records for resume.
"""

import pytest

import label_matching_emails_via_imap as labeler
from imap_stub import StubIMAPServer

MESSAGE_TEMPLATE = (
    "Message-ID: <{mid}@example.com>\r\n"
    "Date: Mon, 05 Jan 2026 09:00:00 +0000\r\n"
    "From: {frm}\r\n"
    "To: {to}\r\n"
    "Subject: {subject}\r\n"
    "\r\n"
    "Body text.\r\n"
)


def message(mid, frm="a@example.com", to="b@example.com", subject="Subject"):
    return MESSAGE_TEMPLATE.format(mid=mid, frm=frm, to=to, subject=subject)


@pytest.fixture
def session(monkeypatch, tmp_path):
    """Point the labeler's module globals at a stub server and a temp state file."""
    def _configure(server, domains, state_name="state.txt", label="Labels/Evidence"):
        for name, value in (
            ("IMAP_HOST", server.host), ("IMAP_PORT", server.port),
            ("IMAP_USER", "user"), ("IMAP_PASS", "secret"),
            ("MAILBOX", "INBOX"), ("TARGET_LABEL", label),
            ("TARGET_DOMAINS", domains), ("STATE_FILE", str(tmp_path / state_name)),
            ("USE_SSL", False), ("USE_STARTTLS", False), ("VERIFY_TLS", True),
            ("DEBUG_MATCHES", False),
        ):
            monkeypatch.setattr(labeler, name, value)
    return _configure


def test_only_matching_messages_are_labeled(session):
    messages = {
        1: message("hit", to="person@target.test"),
        2: message("miss", to="person@other.test"),
        3: message("hit2", frm="someone@target.test"),
    }
    with StubIMAPServer(messages) as server:
        session(server, {"target.test"})
        labeler.process_uids(labeler.fetch_uids_full(), resume=False)

        assert [uid for uid, _ in server.copied] == ["1", "3"]
        assert {mailbox for _, mailbox in server.copied} == {"Labels/Evidence"}


def test_target_folder_is_created_once_per_run(session):
    """It used to be created again on every single match."""
    messages = {n: message(f"m{n}", to="person@target.test") for n in range(1, 4)}
    with StubIMAPServer(messages) as server:
        session(server, {"target.test"})
        labeler.process_uids(labeler.fetch_uids_full(), resume=False)

        assert len(server.copied) == 3
        assert server.created == ["Labels/Evidence"]


def test_reply_to_and_cc_are_matched(session):
    """The domain can appear in headers other than From and To."""
    cc = message("cc").replace("Subject:", "Cc: watcher@target.test\r\nSubject:")
    reply_to = message("rt").replace("Subject:", "Reply-To: boss@target.test\r\nSubject:")
    with StubIMAPServer({1: cc, 2: reply_to, 3: message("plain")}) as server:
        session(server, {"target.test"})
        labeler.process_uids(labeler.fetch_uids_full(), resume=False)

        assert [uid for uid, _ in server.copied] == ["1", "2"]


def test_processed_uids_are_recorded_and_skipped_on_resume(session, tmp_path):
    messages = {1: message("a", to="p@target.test"), 2: message("b", to="p@target.test")}
    with StubIMAPServer(messages) as server:
        session(server, {"target.test"})
        labeler.process_uids(labeler.fetch_uids_full(), resume=False)
        assert len(server.copied) == 2

        state = (tmp_path / "state.txt").read_text().split()
        assert state == ["1", "2"]

        # A second pass with resume on must not touch anything already handled.
        labeler.process_uids(labeler.fetch_uids_full(), resume=True)
        assert len(server.copied) == 2


def test_fast_scan_queries_each_header_for_each_domain(session):
    """Fast mode is a server-side prefilter; it must ask about every header."""
    with StubIMAPServer({1: message("a", to="p@target.test")}) as server:
        session(server, {"target.test"})
        uids = labeler.fetch_uids_fast()

        searches = [c for c in server.commands if "SEARCH" in c]
        assert len(searches) == 4
        for header in ("From", "Reply-To", "To", "Cc"):
            assert any(f'HEADER {header} "@target.test"' in c for c in searches)
        assert uids == [b"1"]


def test_a_refused_folder_creation_stops_the_run(session):
    """imaplib returns NO rather than raising, so a swallowed result is a false success.

    Against a real server this printed "labeled 1" while creating nothing and
    copying nothing: the folder name was rejected, every COPY then failed into a
    folder that did not exist, and the run reported the messages as labeled.
    """
    messages = {1: message("hit", to="person@target.test")}
    with StubIMAPServer(messages, refuse=("CREATE",)) as server:
        session(server, {"target.test"})
        with pytest.raises(SystemExit) as excinfo:
            labeler.process_uids(labeler.fetch_uids_full(), resume=False)

        assert "Cannot create the target folder" in str(excinfo.value)
        assert server.copied == []


def test_a_refused_copy_stops_the_run(session):
    """A server that declines the COPY must not be reported as having labeled the message."""
    messages = {1: message("hit", to="person@target.test")}
    with StubIMAPServer(messages, refuse=("COPY",)) as server:
        session(server, {"target.test"})
        with pytest.raises(RuntimeError, match="refused to copy"):
            labeler.process_uids(labeler.fetch_uids_full(), resume=False)


def test_mailbox_names_are_quoted_on_the_wire(session):
    """An unquoted name with a space in it is parsed by the server as two arguments."""
    messages = {1: message("hit", to="person@target.test")}
    with StubIMAPServer(messages) as server:
        session(server, {"target.test"}, label="Labels/Evidence Review")
        labeler.process_uids(labeler.fetch_uids_full(), resume=False)

        assert server.created == ["Labels/Evidence Review"]
        assert [mailbox for _, mailbox in server.copied] == ["Labels/Evidence Review"]


def test_login_uses_the_configured_user(session):
    with StubIMAPServer({1: message("a")}) as server:
        session(server, {"target.test"})
        labeler.fetch_uids_full()
        assert server.logins == ["user"]
