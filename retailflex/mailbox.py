"""
Gmail helpers for RetailFlex AI.

- send_reply():      sends an email (tries port 587 first, then 465)
- fetch_unread():    reads unread emails from the inbox over IMAP
- mark_as_read():    marks an email as read so it is not processed twice
- should_skip():     protects against reply loops (own emails, auto-replies, no-reply)

Gmail needs an *App Password* (not your normal password):
Google Account -> Security -> 2-Step Verification ON -> App passwords.
"""

from __future__ import annotations

import email
import imaplib
import smtplib
import ssl
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

import markdown

SMTP_HOST = "smtp.gmail.com"
IMAP_HOST = "imap.gmail.com"
TIMEOUT = 30  # seconds


@dataclass
class IncomingEmail:
    uid: str
    sender: str          # plain address, e.g. ali@gmail.com
    sender_name: str
    subject: str
    body: str
    message_id: str
    references: str
    auto_submitted: str
    precedence: str


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #
def split_subject(reply_markdown: str, default: str = "Your RetailFlex AI schedule") -> tuple[str, str]:
    """The agent's reply starts with 'Subject: ...'. Split it from the body."""
    lines = reply_markdown.strip().splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        return lines[0].split(":", 1)[1].strip() or default, "\n".join(lines[1:]).strip()
    return default, reply_markdown.strip()


def build_message(gmail_user: str, to_addr: str, subject: str, body_md: str,
                  in_reply_to: str = "", references: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"RetailFlex AI <{gmail_user}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    if in_reply_to:  # keeps the reply in the same Gmail conversation thread
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = f"{references} {in_reply_to}".strip()
    msg["Auto-Submitted"] = "auto-replied"  # tells other robots not to auto-reply to us

    msg.set_content(body_md)  # plain-text version
    html = markdown.markdown(body_md, extensions=["tables"])
    msg.add_alternative(
        f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5">
<style>table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:6px 10px}}th{{background:#f3f4f6}}</style>
{html}</body></html>""",
        subtype="html",
    )
    return msg


def send_message(gmail_user: str, app_password: str, msg: EmailMessage) -> None:
    """Send via Gmail. Tries port 587 (STARTTLS) and then 465 (SSL)."""
    app_password = app_password.replace(" ", "")  # app passwords are often copied with spaces
    context = ssl.create_default_context()
    errors = []

    try:
        with smtplib.SMTP(SMTP_HOST, 587, timeout=TIMEOUT) as server:
            server.starttls(context=context)
            server.login(gmail_user, app_password)
            server.send_message(msg)
            return
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError(
            "Gmail rejected the login. Check GMAIL_ADDRESS and that GMAIL_APP_PASSWORD is a "
            "16-character App Password (not your normal Gmail password)."
        )
    except Exception as e:
        errors.append(f"port 587: {type(e).__name__}: {e}")

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=TIMEOUT, context=context) as server:
            server.login(gmail_user, app_password)
            server.send_message(msg)
            return
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError("Gmail rejected the login. Check your App Password.")
    except Exception as e:
        errors.append(f"port 465: {type(e).__name__}: {e}")

    raise RuntimeError(
        "Could not reach Gmail's mail server. The hosting network is probably blocking email "
        "ports. Details: " + " | ".join(errors)
    )


def send_reply(gmail_user: str, app_password: str, to_addr: str, reply_markdown: str,
               original: IncomingEmail | None = None) -> None:
    subject, body = split_subject(reply_markdown)
    in_reply_to = references = ""
    if original:
        subject = original.subject if original.subject.lower().startswith("re:") else f"Re: {original.subject}"
        in_reply_to, references = original.message_id, original.references
    send_message(gmail_user, app_password,
                 build_message(gmail_user, to_addr, subject, body, in_reply_to, references))


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def _decode(value: str | None) -> str:
    return str(make_header(decode_header(value))) if value else ""


def _plain_body(msg: email.message.Message) -> str:
    """Return the plain-text body, ignoring attachments and quoted reply text."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                break
        else:
            text = ""
    else:
        payload = msg.get_payload(decode=True) or b""
        text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

    # Drop the quoted previous conversation ("On ... wrote:" and lines starting with ">")
    clean = []
    for line in text.splitlines():
        if line.strip().startswith(">") or (line.strip().startswith("On ") and line.strip().endswith("wrote:")):
            break
        clean.append(line)
    return "\n".join(clean).strip()[:5000]


def fetch_unread(gmail_user: str, app_password: str, limit: int = 5) -> list[IncomingEmail]:
    """Fetch up to `limit` unread emails from the inbox (they stay unread until marked)."""
    app_password = app_password.replace(" ", "")
    results = []
    with imaplib.IMAP4_SSL(IMAP_HOST, 993, timeout=TIMEOUT) as imap:
        imap.login(gmail_user, app_password)
        imap.select("INBOX")
        _, data = imap.uid("search", None, "UNSEEN")
        uids = data[0].split()[:limit]
        for uid in uids:
            _, msg_data = imap.uid("fetch", uid, "(BODY.PEEK[])")  # PEEK = don't mark as read yet
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            name, addr = parseaddr(_decode(msg.get("From")))
            results.append(
                IncomingEmail(
                    uid=uid.decode(),
                    sender=addr.lower(),
                    sender_name=name,
                    subject=_decode(msg.get("Subject")) or "(no subject)",
                    body=_plain_body(msg),
                    message_id=msg.get("Message-ID", ""),
                    references=msg.get("References", ""),
                    auto_submitted=(msg.get("Auto-Submitted") or "").lower(),
                    precedence=(msg.get("Precedence") or "").lower(),
                )
            )
    return results


def mark_as_read(gmail_user: str, app_password: str, uid: str) -> None:
    with imaplib.IMAP4_SSL(IMAP_HOST, 993, timeout=TIMEOUT) as imap:
        imap.login(gmail_user, app_password.replace(" ", ""))
        imap.select("INBOX")
        imap.uid("store", uid, "+FLAGS", "(\\Seen)")


def should_skip(mail: IncomingEmail, own_address: str) -> str | None:
    """Return a reason to skip this email, or None if it should be answered."""
    s = mail.sender
    if not s or s == own_address.lower():
        return "sent by RetailFlex itself"
    if any(k in s for k in ("no-reply", "noreply", "do-not-reply", "mailer-daemon", "postmaster")):
        return "automated sender"
    if mail.auto_submitted and mail.auto_submitted != "no":
        return "auto-generated email"
    if mail.precedence in ("bulk", "list", "junk"):
        return "bulk/mailing-list email"
    if len(mail.body) < 15:
        return "empty email"
    return None
