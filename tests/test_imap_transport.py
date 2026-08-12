"""Covers TLS selection and resume-state keying in label_matching_emails_via_imap.py."""

import imaplib
import ssl
from argparse import Namespace

import pytest

import label_matching_emails_via_imap as labeler


def args(host="127.0.0.1", port=1143, ssl="auto", starttls=False):
    return Namespace(imap_host=host, imap_port=port, ssl=ssl, starttls=starttls)


def test_auto_uses_plaintext_for_a_local_bridge():
    """Proton Bridge listens in plaintext on loopback; forcing TLS would break it."""
    assert labeler.resolve_transport(args()) == (False, False)


@pytest.mark.parametrize("host", ["imap.gmail.com", "outlook.office365.com", "192.0.2.10"])
def test_auto_uses_tls_for_any_remote_host(host):
    """The default must never put a password on the wire in the clear."""
    assert labeler.resolve_transport(args(host=host, port=143)) == (True, False)


def test_auto_uses_tls_on_the_imaps_port_even_locally():
    assert labeler.resolve_transport(args(port=993)) == (True, False)


def test_explicit_off_is_honoured_and_warns_for_remote_hosts(capsys):
    assert labeler.resolve_transport(args(host="imap.example.com", ssl="off")) == (False, False)
    assert "in the clear" in capsys.readouterr().out


def test_starttls_selects_a_plaintext_socket_to_upgrade():
    assert labeler.resolve_transport(args(host="imap.example.com", starttls=True)) == (False, True)


def test_starttls_with_implicit_tls_is_rejected():
    with pytest.raises(SystemExit):
        labeler.resolve_transport(args(ssl="on", starttls=True))


def test_state_file_differs_per_target():
    """One shared filename let a run skip messages another run had recorded."""
    base = ("127.0.0.1", 1143, '"All Mail"', "Labels/Evidence", {"example.com"})
    assert labeler.default_state_file(*base) == labeler.default_state_file(*base)

    variants = [
        ("imap.gmail.com", 993, '"All Mail"', "Labels/Evidence", {"example.com"}),
        ("127.0.0.1", 1143, "INBOX", "Labels/Evidence", {"example.com"}),
        ("127.0.0.1", 1143, '"All Mail"', "Labels/Other", {"example.com"}),
        ("127.0.0.1", 1143, '"All Mail"', "Labels/Evidence", {"other.test"}),
    ]
    names = {labeler.default_state_file(*v) for v in variants}
    assert labeler.default_state_file(*base) not in names
    assert len(names) == len(variants)


def test_state_file_ignores_domain_ordering():
    """The domain set is unordered; its filename must not depend on iteration order."""
    a = labeler.default_state_file("h", 1, "m", "l", {"b.test", "a.test"})
    b = labeler.default_state_file("h", 1, "m", "l", {"a.test", "b.test"})
    assert a == b


def test_split_domains_normalizes_input():
    assert labeler.split_domains(" @Example.COM , example.org ,") == {"example.com", "example.org"}


def test_tls_context_verifies_by_default():
    """imaplib's own default context sets check_hostname=False and CERT_NONE.

    Relying on it gives an encrypted but unauthenticated session, which any host
    able to answer for the address can terminate with its own certificate and
    read the password out of.
    """
    context = labeler.tls_context()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_tls_context_can_be_downgraded_explicitly(capsys):
    context = labeler.tls_context(verify=False)
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE
    assert "not authenticated" in capsys.readouterr().out


class _FakeIMAP:
    """Records how the connection was constructed instead of opening a socket."""

    last = {}

    def __init__(self, host, port, ssl_context=None):
        _FakeIMAP.last = {"host": host, "port": port, "ssl_context": ssl_context}

    def login(self, user, password):
        _FakeIMAP.last["login"] = (user, password)

    def starttls(self, ssl_context=None):
        _FakeIMAP.last["starttls_context"] = ssl_context


@pytest.fixture
def connection_globals(monkeypatch):
    for name, value in (("IMAP_HOST", "imap.example.com"), ("IMAP_PORT", 993),
                        ("IMAP_USER", "user"), ("IMAP_PASS", "secret"),
                        ("VERIFY_TLS", True)):
        monkeypatch.setattr(labeler, name, value)


def test_implicit_tls_passes_a_verifying_context(connection_globals, monkeypatch):
    monkeypatch.setattr(labeler, "USE_SSL", True)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeIMAP)
    labeler.connect()

    context = _FakeIMAP.last["ssl_context"]
    assert context is not None, "imaplib would fall back to its unverified default"
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_starttls_passes_a_verifying_context(connection_globals, monkeypatch):
    monkeypatch.setattr(labeler, "USE_SSL", False)
    monkeypatch.setattr(labeler, "USE_STARTTLS", True)
    monkeypatch.setattr(imaplib, "IMAP4", _FakeIMAP)
    labeler.connect()

    context = _FakeIMAP.last["starttls_context"]
    assert context is not None, "imaplib would fall back to its unverified default"
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
