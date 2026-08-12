"""Exercises label_matching_emails_via_imap.py against a real IMAP server, skipped unless one is configured.

Everything else in the suite runs against a stub. These tests are the only ones
that prove the tool authenticates and searches on a live server, so they exist,
but they never run by default: they need credentials and they touch a real
mailbox.

To run them, point EET_LIVE_ENV_FILE at a file holding the connection details
and run pytest as usual:

    EET_LIVE_ENV_FILE=path/to/.env pytest tests/test_live_imap.py

The file is read directly, never passed on a command line, so the password does
not appear in a process listing or a shell history. Recognized keys, with the
PROTON_BRIDGE_* spellings accepted so an existing bridge configuration works
unchanged:

    IMAP_HOST / PROTON_BRIDGE_HOST      default 127.0.0.1
    IMAP_PORT / PROTON_BRIDGE_PORT      default 1143
    IMAP_USER / PROTON_BRIDGE_USER      required
    IMAP_PASS / PROTON_BRIDGE_PASS      required
    IMAP_MAILBOX                        default "All Mail"

Every test here is read-only. The one test that writes to the mailbox, applying
a label, additionally requires EET_LIVE_LABEL_TARGET to name the folder it may
create, so a run cannot modify a real mailbox by accident.

Expect these to be slow. Against a large All Mail behind Proton Bridge the read-
only set took about fifteen minutes, nearly all of it in the fast-scan test:
that is four server-side HEADER searches over the whole archive, which is the
same cost the tool pays in normal use.
"""

import os
import ssl
from argparse import Namespace
from pathlib import Path

import pytest

import label_matching_emails_via_imap as labeler

LIVE_ENV_FILE = os.getenv("EET_LIVE_ENV_FILE", "").strip()
LABEL_TARGET = os.getenv("EET_LIVE_LABEL_TARGET", "").strip()

pytestmark = pytest.mark.skipif(
    not LIVE_ENV_FILE,
    reason="set EET_LIVE_ENV_FILE to a file with IMAP credentials to run the live tests",
)


def _read_env_file(path: Path) -> dict:
    """Parse a KEY=value file, ignoring comments and surrounding quotes."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@pytest.fixture(scope="module")
def live_config():
    path = Path(LIVE_ENV_FILE)
    if not path.exists():
        pytest.skip(f"EET_LIVE_ENV_FILE points at {path}, which does not exist")
    env = _read_env_file(path)

    def pick(*names, default=None):
        for name in names:
            if env.get(name):
                return env[name]
        return default

    user = pick("IMAP_USER", "PROTON_BRIDGE_USER")
    password = pick("IMAP_PASS", "PROTON_BRIDGE_PASS")
    if not user or not password:
        pytest.skip(f"{path} has no IMAP_USER/IMAP_PASS or PROTON_BRIDGE_USER/PASS")

    return {
        "host": pick("IMAP_HOST", "PROTON_BRIDGE_HOST", default="127.0.0.1"),
        "port": int(pick("IMAP_PORT", "PROTON_BRIDGE_PORT", default="1143")),
        "user": user,
        "password": password,
        "mailbox": pick("IMAP_MAILBOX", default='"All Mail"'),
    }


@pytest.fixture
def configured(live_config, monkeypatch):
    """Apply the live connection details to the labeler's module globals."""
    for name, value in (
        ("IMAP_HOST", live_config["host"]), ("IMAP_PORT", live_config["port"]),
        ("IMAP_USER", live_config["user"]), ("IMAP_PASS", live_config["password"]),
        ("MAILBOX", live_config["mailbox"]), ("USE_SSL", False),
        ("USE_STARTTLS", False), ("VERIFY_TLS", True), ("DEBUG_MATCHES", False),
    ):
        monkeypatch.setattr(labeler, name, value)
    return live_config


def test_authenticates_over_the_auto_transport(configured):
    """The default path for this host: plaintext to a loopback bridge, then LOGIN."""
    resolved = labeler.resolve_transport(Namespace(
        imap_host=configured["host"], imap_port=configured["port"],
        ssl="auto", starttls=False,
    ))
    labeler.USE_SSL, labeler.USE_STARTTLS = resolved

    connection = labeler.connect()
    try:
        typ, _ = connection.select(configured["mailbox"], readonly=True)
        assert typ == "OK"
    finally:
        connection.logout()


def test_authenticates_over_starttls(configured, monkeypatch):
    """STARTTLS against a bridge needs --tls-no-verify for its self-signed certificate."""
    monkeypatch.setattr(labeler, "USE_SSL", False)
    monkeypatch.setattr(labeler, "USE_STARTTLS", True)
    monkeypatch.setattr(labeler, "VERIFY_TLS", False)

    connection = labeler.connect()
    try:
        assert connection.sock.version().startswith("TLS")
    finally:
        connection.logout()


def test_certificate_verification_rejects_a_self_signed_bridge(configured, monkeypatch):
    """Proof the verification added to this tool is actually doing something.

    A bridge presents a self-signed certificate, so a verifying STARTTLS must
    fail. If this ever passes against a bridge, verification has been disabled
    somewhere.
    """
    monkeypatch.setattr(labeler, "USE_SSL", False)
    monkeypatch.setattr(labeler, "USE_STARTTLS", True)
    monkeypatch.setattr(labeler, "VERIFY_TLS", True)

    if not labeler.is_local_host(configured["host"]):
        pytest.skip("only meaningful against a local bridge with a self-signed certificate")

    with pytest.raises(ssl.SSLCertVerificationError):
        labeler.connect()


def test_full_scan_enumerates_the_mailbox(configured):
    """Read-only: proves UID enumeration works against a real server."""
    uids = labeler.fetch_uids_full()
    assert isinstance(uids, list)
    assert all(uid.isdigit() for uid in uids)


def test_fast_scan_prefilters_server_side(configured, monkeypatch):
    """Read-only: proves the server accepts the HEADER search syntax the tool sends.

    A server that rejects it would otherwise fail silently as an empty result,
    which reads exactly like a mailbox with no matches.
    """
    monkeypatch.setattr(labeler, "TARGET_DOMAINS", {"invalid-domain-that-matches-nothing.test"})
    uids = labeler.fetch_uids_fast()
    assert uids == []


@pytest.mark.skipif(
    not LABEL_TARGET,
    reason="set EET_LIVE_LABEL_TARGET to a folder name to run the one test that writes",
)
def test_labels_a_matching_message(configured, monkeypatch, tmp_path):
    """The only live test that modifies the mailbox, hence its own opt-in.

    It creates EET_LIVE_LABEL_TARGET and copies at most one message into it,
    then deletes that folder again so the mailbox is left as it was found.
    Deleting the folder removes the label, not the message.

    Note that the target usually needs the server's namespace prefix, for
    instance Labels/Something on Proton Bridge. A bare top-level name is
    refused, and the tool now stops rather than reporting work it did not do.
    """
    monkeypatch.setattr(labeler, "TARGET_LABEL", LABEL_TARGET)
    monkeypatch.setattr(labeler, "STATE_FILE", str(tmp_path / "state.txt"))

    all_uids = labeler.fetch_uids_full()
    if not all_uids:
        pytest.skip("mailbox is empty")

    # Take one message and label it by its own sender domain, so exactly one
    # message can match and the blast radius is a single COPY.
    import email
    connection = labeler.connect()
    try:
        connection.select(configured["mailbox"], readonly=True)
        _, data = connection.uid("FETCH", all_uids[-1].decode(), "(RFC822)")
        message = email.message_from_bytes(data[0][1])
        domains = labeler.extract_domains(message)
    finally:
        connection.logout()

    if not domains:
        pytest.skip("the sampled message carries no parseable address domain")
    monkeypatch.setattr(labeler, "TARGET_DOMAINS", {sorted(domains)[0]})

    try:
        labeler.process_uids([all_uids[-1]], resume=False)

        connection = labeler.connect()
        try:
            typ, _ = connection.select(labeler.quote_mailbox(LABEL_TARGET), readonly=True)
            assert typ == "OK", f"{LABEL_TARGET} was not created"
        finally:
            connection.logout()
    finally:
        # Put the mailbox back. This runs even on failure, because a half-done
        # run still leaves a real folder behind in someone's account.
        connection = labeler.connect()
        try:
            connection.delete(labeler.quote_mailbox(LABEL_TARGET))
        finally:
            connection.logout()
