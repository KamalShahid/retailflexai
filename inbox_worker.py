"""
RetailFlex AI inbox worker — answers new emails automatically.

GitHub Actions runs this every few minutes (see .github/workflows/retailflex-inbox.yml).
You can also run it on your own computer:  python inbox_worker.py

It needs three settings (environment variables / GitHub secrets):
  GROQ_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD
"""

# SQLite fix (same as in app.py) — harmless where it is not needed
try:
    __import__("pysqlite3")
    import sys

    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import os
import sys

from retailflex.inbox import process_inbox


def main() -> int:
    missing = [k for k in ("GROQ_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD") if not os.getenv(k)]
    if missing:
        print(f"Missing settings: {', '.join(missing)}")
        return 1

    summary = process_inbox(
        gmail_user=os.environ["GMAIL_ADDRESS"],
        app_password=os.environ["GMAIL_APP_PASSWORD"],
        groq_key=os.environ["GROQ_API_KEY"],
    )
    errors = [s for s in summary if s["status"].startswith("error")]
    print(f"Done: {len(summary)} email(s) checked, {len(errors)} error(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
