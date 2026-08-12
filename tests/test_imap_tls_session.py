"""Drives the labeler over implicit TLS against a stub server with a real certificate.

The unit tests check that a verifying context is handed to imaplib, and the live
bridge covers STARTTLS. Neither opens an implicit-TLS session, which is what
`--ssl on` uses against a hosted provider on port 993. These tests do, with an
ephemeral certificate generated for the run, so both the success path and the
rejection path are exercised without an account anywhere.
"""

import datetime
import ipaddress
import ssl

import pytest

import label_matching_emails_via_imap as labeler
from imap_stub import StubIMAPServer

cryptography = pytest.importorskip("cryptography", reason="pip install -r requirements-dev.txt")

from cryptography import x509                                    # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa         # noqa: E402
from cryptography.x509.oid import NameOID                         # noqa: E402

MESSAGE = (
    "Message-ID: <tls@example.com>\r\n"
    "Date: Mon, 05 Jan 2026 09:00:00 +0000\r\n"
    "From: a@example.com\r\n"
    "To: person@target.test\r\n"
    "Subject: Subject\r\n"
    "\r\n"
    "Body text.\r\n"
)


def _make_certificate(out_dir, common_name, sans, prefix="cert"):
    """Write a self-signed certificate and key for `common_name`, returning both paths."""
    cert_path = out_dir / f"{prefix}.pem"
    key_path = out_dir / f"{prefix}.key"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    return cert_path, key_path


@pytest.fixture(scope="module")
def certificate(tmp_path_factory):
    """A certificate valid for the address the tests connect to."""
    return _make_certificate(
        tmp_path_factory.mktemp("tls"), "localhost",
        [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))],
    )


@pytest.fixture(scope="module")
def wrong_name_certificate(tmp_path_factory):
    """A trusted certificate issued for a name the tests do not connect to."""
    return _make_certificate(
        tmp_path_factory.mktemp("tls-wrong"), "not-this-host.example",
        [x509.DNSName("not-this-host.example")], prefix="wrong",
    )


@pytest.fixture
def tls_server(certificate):
    """A stub IMAP server speaking implicit TLS, as a server on port 993 does."""
    cert_path, key_path = certificate
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    with StubIMAPServer({1: MESSAGE}, ssl_context=context) as server:
        yield server


@pytest.fixture
def configured(tls_server, monkeypatch):
    """Point the labeler at the TLS stub, addressing it by a name the certificate covers."""
    for name, value in (
        ("IMAP_HOST", "localhost"), ("IMAP_PORT", tls_server.port),
        ("IMAP_USER", "user"), ("IMAP_PASS", "secret"),
        ("MAILBOX", "INBOX"), ("TARGET_LABEL", "Labels/Evidence"),
        ("TARGET_DOMAINS", {"target.test"}),
        ("USE_SSL", True), ("USE_STARTTLS", False), ("VERIFY_TLS", True),
    ):
        monkeypatch.setattr(labeler, name, value)
    return tls_server


def _trusting_context(cert_path):
    """A verifying context that happens to trust the test certificate."""
    context = ssl.create_default_context(cafile=str(cert_path))
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def test_implicit_tls_session_completes(configured, certificate, monkeypatch):
    """A full login over implicit TLS, the path --ssl on takes to a hosted provider."""
    cert_path, _ = certificate
    monkeypatch.setattr(labeler, "tls_context", lambda verify=True: _trusting_context(cert_path))

    connection = labeler.connect()
    try:
        assert connection.sock.version().startswith("TLS")
        typ, _ = connection.select("INBOX", readonly=True)
        assert typ == "OK"
    finally:
        connection.logout()

    assert configured.logins == ["user"]


def test_labels_over_implicit_tls(configured, certificate, monkeypatch, tmp_path):
    """The whole job, encrypted end to end, not just the handshake."""
    cert_path, _ = certificate
    monkeypatch.setattr(labeler, "tls_context", lambda verify=True: _trusting_context(cert_path))
    monkeypatch.setattr(labeler, "STATE_FILE", str(tmp_path / "state.txt"))

    labeler.process_uids(labeler.fetch_uids_full(), resume=False)

    assert [uid for uid, _ in configured.copied] == ["1"]


def test_an_untrusted_certificate_is_refused(configured):
    """The default context uses the system roots, which do not include this certificate.

    This is the assertion that proves --ssl on is not quietly accepting whatever
    certificate it is handed, which is what imaplib does when left to its own
    defaults.
    """
    with pytest.raises(ssl.SSLCertVerificationError):
        labeler.connect()


def test_a_hostname_mismatch_is_refused(wrong_name_certificate, monkeypatch):
    """A certificate that is trusted, but issued for another name, must be refused.

    Chain validation alone is not enough. Encryption without hostname checking
    stops a passive listener and nothing else: anything that can answer for the
    address can present a certificate it legitimately holds for a different name.
    """
    cert_path, key_path = wrong_name_certificate
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

    with StubIMAPServer({1: MESSAGE}, ssl_context=server_context) as server:
        for name, value in (
            ("IMAP_HOST", "localhost"), ("IMAP_PORT", server.port),
            ("IMAP_USER", "user"), ("IMAP_PASS", "secret"),
            ("USE_SSL", True), ("USE_STARTTLS", False), ("VERIFY_TLS", True),
        ):
            monkeypatch.setattr(labeler, name, value)
        # Trust the certificate itself, so the only thing left to reject it on
        # is the name it was issued for.
        monkeypatch.setattr(labeler, "tls_context",
                            lambda verify=True: _trusting_context(cert_path))

        with pytest.raises(ssl.SSLCertVerificationError):
            labeler.connect()


def test_tls_no_verify_still_connects(configured, monkeypatch, capsys):
    """The documented escape hatch for a bridge with a self-signed certificate."""
    monkeypatch.setattr(labeler, "VERIFY_TLS", False)

    connection = labeler.connect()
    try:
        assert connection.sock.version().startswith("TLS")
    finally:
        connection.logout()
    assert "not authenticated" in capsys.readouterr().out
