"""Builds small synthetic mbox archives covering the message shapes the tools must handle."""

import base64
from pathlib import Path

SEPARATOR = "From nobody Thu Jan 01 00:00:00 1970"


def plain_message(mid="plain", subject="Plain", body="Hello there.", date="Mon, 05 Jan 2026 09:00:00 +0000",
                  to="b@example.com", frm="a@example.com"):
    """A single-part text/plain message."""
    return f"""{SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: {frm}
To: {to}
Subject: {subject}
Content-Type: text/plain; charset="utf-8"

{body}
"""


def html_only_message(mid="htmlonly", subject="HTML only", html="<html><body><p>Hello.</p></body></html>",
                      date="Tue, 06 Jan 2026 09:00:00 +0000"):
    """A multipart/alternative message carrying no text/plain part at all."""
    return f"""{SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: {subject}
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="BOUND1"

--BOUND1
Content-Type: text/html; charset="utf-8"

{html}
--BOUND1--
"""


def attachment_message(mid="att", filename="doc.bin", payload=b"attachment-bytes",
                       date="Wed, 07 Jan 2026 09:00:00 +0000", body="Body text."):
    """A multipart/mixed message with one text part and one attachment."""
    encoded = base64.b64encode(payload).decode()
    return f"""{SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: With attachment {mid}
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="BOUND2"

--BOUND2
Content-Type: text/plain; charset="utf-8"

{body}
--BOUND2
Content-Type: application/octet-stream; name="{filename}"
Content-Disposition: attachment; filename="{filename}"
Content-Transfer-Encoding: base64

{encoded}
--BOUND2--
"""


def transport_message(mid="transport", subject="Transport headers", body="Transport body.",
                      date="Mon, 05 Jan 2026 09:00:00 +0000",
                      received_1=None, received_2=None, return_path="<a@example.com>",
                      auth_results=None, dkim_signature=None):
    """A single-part text/plain message carrying transport headers."""
    received_1 = received_1 or (
        "from mx2.example.net (mx2.example.net [203.0.113.9]) "
        "by mail.example.org with ESMTPS id abc123; Mon, 05 Jan 2026 09:00:04 +0000"
    )
    received_2 = received_2 or (
        "from sender.example.com (sender.example.com [198.51.100.7]) "
        "by mx2.example.net with ESMTP id def456; Mon, 05 Jan 2026 09:00:01 +0000"
    )
    auth_results = auth_results or (
        "mx2.example.net; spf=pass smtp.mailfrom=example.com; "
        "dkim=pass header.d=example.com"
    )
    dkim_signature = dkim_signature or "v=1; a=rsa-sha256; d=example.com; s=sel; bh=AAAA; b=BBBB"
    return f"""{SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
Received: {received_1}
Received: {received_2}
Return-Path: {return_path}
Authentication-Results: {auth_results}
DKIM-Signature: {dkim_signature}
From: a@example.com
To: b@example.com
Subject: {subject}
Content-Type: text/plain; charset="utf-8"

{body}
"""


def nested_message(mid="nested", filename="nested.bin", payload=b"nested-bytes",
                   date="Thu, 08 Jan 2026 09:00:00 +0000"):
    """multipart/mixed wrapping a multipart/alternative, plus an attachment."""
    encoded = base64.b64encode(payload).decode()
    return f"""{SEPARATOR}
Message-ID: <{mid}@example.com>
Date: {date}
From: a@example.com
To: b@example.com
Subject: Nested structure
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="OUTER"

--OUTER
Content-Type: multipart/alternative; boundary="INNER"

--INNER
Content-Type: text/plain; charset="utf-8"

Plain version of the message.
--INNER
Content-Type: text/html; charset="utf-8"

<html><body><p>HTML version of the message.</p></body></html>
--INNER--
--OUTER
Content-Type: application/octet-stream; name="{filename}"
Content-Disposition: attachment; filename="{filename}"
Content-Transfer-Encoding: base64

{encoded}
--OUTER--
"""


def write_mbox(path: Path, messages) -> Path:
    """Write the given message strings to `path` as a single mbox archive."""
    path.write_text("\n".join(messages), encoding="utf-8")
    return path
