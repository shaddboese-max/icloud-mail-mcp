import imaplib
import email
import os
import json
import uvicorn
from email.header import decode_header
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

RAILWAY_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "icloud-mail-mcp-production.up.railway.app")

mcp = FastMCP(
    "iCloud Mail",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[RAILWAY_DOMAIN, "localhost", "127.0.0.1"],
        allowed_origins=[f"https://{RAILWAY_DOMAIN}"],
    ),
)

IMAP_HOST = "imap.mail.me.com"
IMAP_PORT = 993
EMAIL_ADDRESS = os.environ.get("ICLOUD_EMAIL", "shaddboese2023@icloud.com")
APP_PASSWORD = os.environ.get("ICLOUD_APP_PASSWORD", "")



def connect():
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(EMAIL_ADDRESS, APP_PASSWORD)
    return mail


def decode_str(s):
    if s is None:
        return ""
    parts = decode_header(s)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def get_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return body[:4000]


@mcp.tool()
def list_folders() -> str:
    """List all mailbox folders in iCloud Mail."""
    mail = connect()
    _, folders = mail.list()
    mail.logout()
    result = []
    for f in folders:
        if isinstance(f, bytes):
            result.append(f.decode())
    return "\n".join(result)


@mcp.tool()
def search_emails(query: str, folder: str = "INBOX", max_results: int = 10) -> str:
    """Search emails in iCloud Mail. Query examples: 'Oregon', 'FROM oregon.gov', 'SUBJECT LLC'."""
    mail = connect()
    mail.select(folder)

    if " " not in query and not query.startswith(("FROM", "TO", "SUBJECT", "BODY", "ALL")):
        search_query = f'TEXT "{query}"'
    else:
        search_query = query

    _, data = mail.uid("search", None, search_query)
    if not data or not data[0]:
        mail.logout()
        return "No emails found."
    uids = data[0].split()
    uids = uids[-max_results:]

    results = []
    for uid in reversed(uids):
        _, msg_data = mail.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
        raw = None
        for part in msg_data:
            if isinstance(part, tuple):
                raw = part[1]
                break
        if raw is None:
            continue
        msg = email.message_from_bytes(raw)
        results.append({
            "uid": uid.decode(),
            "from": decode_str(msg.get("From", "")),
            "subject": decode_str(msg.get("Subject", "")),
            "date": msg.get("Date", ""),
        })

    mail.logout()
    return json.dumps(results, indent=2) if results else "No emails found."


@mcp.tool()
def read_email(uid: str, folder: str = "INBOX") -> str:
    """Read the full content of an email by its UID."""
    mail = connect()
    mail.select(folder)
    typ, msg_data = mail.uid("fetch", uid, "(BODY.PEEK[])")
    mail.logout()

    if typ != "OK" or not msg_data:
        return f"Email not found (status: {typ})."

    raw = None
    for part in msg_data:
        if isinstance(part, tuple):
            raw = part[1]
            break
    if raw is None:
        return f"Email not found (response had {len(msg_data)} parts, none were tuples)."

    msg = email.message_from_bytes(raw)

    return json.dumps({
        "from": decode_str(msg.get("From", "")),
        "to": decode_str(msg.get("To", "")),
        "subject": decode_str(msg.get("Subject", "")),
        "date": msg.get("Date", ""),
        "body": get_body(msg),
    }, indent=2)


@mcp.tool()
def list_recent_emails(folder: str = "INBOX", count: int = 20) -> str:
    """List the most recent emails in a folder."""
    mail = connect()
    mail.select(folder)
    _, data = mail.uid("search", None, "ALL")
    uids = data[0].split()
    uids = uids[-count:]

    results = []
    for uid in reversed(uids):
        _, msg_data = mail.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
        raw = None
        for part in msg_data:
            if isinstance(part, tuple):
                raw = part[1]
                break
        if raw is None:
            continue
        msg = email.message_from_bytes(raw)
        results.append({
            "uid": uid.decode(),
            "from": decode_str(msg.get("From", "")),
            "subject": decode_str(msg.get("Subject", "")),
            "date": msg.get("Date", ""),
        })

    mail.logout()
    return json.dumps(results, indent=2)


if __name__ == "__main__":
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
