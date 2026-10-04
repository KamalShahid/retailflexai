"""
Process the RetailFlex inbox: read each unread email, run the agent, send the reply.
Used by both the Streamlit app ("Check inbox now") and inbox_worker.py (automatic).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .agent import run_retailflex
from .mailbox import fetch_unread, mark_as_read, send_reply, should_skip

HELP_REPLY = """Subject: How to request a RetailFlex AI schedule

Hello,

Thank you for contacting RetailFlex AI. I could not find appliance details in your email.

Please reply with the appliances you want to run tomorrow, how long each needs to run,
and when each one is allowed to operate. For example:

"Washing machine for 2 hours between 9 AM and 6 PM, dishwasher for 2 hours after 6 PM,
water pump for 1 hour anytime between 6 AM and 10 PM."

Best regards,
RetailFlex AI"""


def tomorrow() -> date:
    """Tomorrow's date in the consumer's time zone (default: Pakistan)."""
    tz = ZoneInfo(os.getenv("RETAILFLEX_TIMEZONE", "Asia/Karachi"))
    return datetime.now(tz).date() + timedelta(days=1)


def process_inbox(gmail_user: str, app_password: str, groq_key: str,
                  limit: int = 5, log=print) -> list[dict]:
    """Answer up to `limit` unread emails. Returns a summary of what happened."""
    summary = []
    for mail in fetch_unread(gmail_user, app_password, limit=limit):
        item = {"from": mail.sender, "subject": mail.subject, "status": ""}
        reason = should_skip(mail, gmail_user)
        if reason:
            item["status"] = f"skipped ({reason})"
        else:
            try:
                log(f"Processing email from {mail.sender}: {mail.subject}")
                result = run_retailflex(mail.body, tomorrow(), groq_key)
                reply = result["email"] if result["data"] else HELP_REPLY
                send_reply(gmail_user, app_password, mail.sender, reply, original=mail)
                item["status"] = "replied with schedule" if result["data"] else "replied with help message"
            except Exception as e:
                item["status"] = f"error: {e}"
        # Mark as read even after an error, so one bad email is not retried forever
        mark_as_read(gmail_user, app_password, mail.uid)
        log(f"  -> {item['status']}")
        summary.append(item)
    if not summary:
        log("No unread emails.")
    return summary
