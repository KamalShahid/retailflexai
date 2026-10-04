"""
RetailFlex AI — Streamlit app.
Run locally with:  streamlit run app.py
"""

# --- SQLite fix for Streamlit Cloud (CrewAI's dependency chromadb needs a new SQLite) ---
try:
    __import__("pysqlite3")
    import sys

    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass  # On Windows/Mac the built-in sqlite3 is fine
# -----------------------------------------------------------------------------------------

import os
import smtplib
from datetime import date, timedelta
from email.message import EmailMessage

import pandas as pd
import streamlit as st

from retailflex.agent import run_retailflex

st.set_page_config(page_title="RetailFlex AI", page_icon="⚡", layout="wide")


def get_secret(name: str, default: str = "") -> str:
    """Read a value from Streamlit secrets, then environment variables."""
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except Exception:  # no secrets.toml file
        return os.getenv(name, default)


SAMPLE_EMAIL = """Hello RetailFlex,

I need to use the washing machine for 2 hours, dishwasher for 2 hours, water pump for 1 hour, and air conditioner for 6 hours tomorrow. The washing machine can operate between 9 AM and 6 PM, the dishwasher after 6 PM, and the water pump anytime between 6 AM and 10 PM. The AC is needed between 12 PM and midnight.

Thanks,
Ali"""

# ------------------------------- Sidebar ------------------------------- #
with st.sidebar:
    st.header("⚙️ Settings")
    groq_key = get_secret("GROQ_API_KEY")
    if groq_key:
        st.success("Groq API key loaded from secrets.")
    else:
        groq_key = st.text_input("Groq API key", type="password", help="Get a free key at console.groq.com")

    target_date = st.date_input("Schedule date", value=date.today() + timedelta(days=1))

    st.divider()
    st.markdown(
        "**How it works**\n\n"
        "1. 📧 Agent reads the email\n"
        "2. 🔎 Looks up missing power ratings (DuckDuckGo)\n"
        "3. 📈 GridSense-A & GridSense-B forecast 24-h prices\n"
        "4. 🧮 Optimizer finds the cheapest schedules\n"
        "5. ✍️ Agent writes the reply email"
    )
    st.caption("Model: openai/gpt-oss-120b on Groq · GridSense prices are simulated.")

# ------------------------------- Main ------------------------------- #
st.title("⚡ RetailFlex AI")
st.subheader("Agentic AI for appliance scheduling & retail electricity cost optimization")

email_text = st.text_area("Consumer email", value=SAMPLE_EMAIL, height=230)

if st.button("🚀 Run RetailFlex AI", type="primary", width="stretch"):
    if not groq_key:
        st.error("Please add your Groq API key in the sidebar.")
        st.stop()
    if len(email_text.strip()) < 20:
        st.error("Please write a longer email describing your appliances.")
        st.stop()
    with st.spinner("RetailFlex AI agent is working… (usually 15–60 seconds)"):
        try:
            st.session_state["output"] = run_retailflex(email_text, target_date, groq_key)
        except Exception as e:
            st.error(f"Something went wrong: {e}")
            st.stop()

output = st.session_state.get("output")
if output:
    data = output["data"]
    tab_email, tab_prices, tab_sched = st.tabs(["📧 Reply email", "📈 Price forecasts", "🗓️ Schedules & costs"])

    with tab_email:
        st.markdown(output["email"])
        st.download_button("⬇️ Download reply (.md)", output["email"], file_name="retailflex_reply.md")

        # Optional: send the reply with Gmail (needs secrets, see README)
        gmail_user, gmail_pass = get_secret("GMAIL_ADDRESS"), get_secret("GMAIL_APP_PASSWORD")
        with st.expander("📤 Send this reply by email (optional)"):
            if not (gmail_user and gmail_pass):
                st.info("Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to your secrets to enable sending.")
            else:
                to_addr = st.text_input("Consumer email address")
                if st.button("Send email") and to_addr:
                    lines = output["email"].splitlines()
                    subject = "Your RetailFlex AI schedule"
                    if lines and lines[0].lower().startswith("subject:"):
                        subject, lines = lines[0].split(":", 1)[1].strip(), lines[1:]
                    msg = EmailMessage()
                    msg["From"], msg["To"], msg["Subject"] = gmail_user, to_addr, subject
                    msg.set_content("\n".join(lines).strip())
                    try:
                        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                            server.login(gmail_user, gmail_pass)
                            server.send_message(msg)
                        st.success(f"Email sent to {to_addr}")
                    except Exception as e:
                        st.error(f"Could not send email: {e}")

    if data is None:
        st.warning("The agent did not call the optimizer, so no numbers are available. Try running again.")
    else:
        with tab_prices:
            df = pd.DataFrame(
                {
                    "Supplier A ($/kWh)": [r["price_per_kwh"] for r in data["forecasts"]["A"]],
                    "Supplier B ($/kWh)": [r["price_per_kwh"] for r in data["forecasts"]["B"]],
                },
                index=[f"{h:02d}:00" for h in range(24)],
            )
            st.markdown(f"**GridSense next-day price forecasts for {data['target_date']}**")
            st.line_chart(df)
            with st.expander("See GridSense details (load, solar, net load, grid stress)"):
                for k in ("A", "B"):
                    st.markdown(f"**GridSense-{k}**")
                    st.dataframe(pd.DataFrame(data["forecasts"][k]), hide_index=True)

        with tab_sched:
            res = data["results"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Supplier A — daily cost", f"${res['A']['total_cost']:.2f}",
                      delta=f"-${res['A']['baseline_cost'] - res['A']['total_cost']:.2f} vs unoptimized",
                      delta_color="inverse")
            c2.metric("Supplier B — daily cost", f"${res['B']['total_cost']:.2f}",
                      delta=f"-${res['B']['baseline_cost'] - res['B']['total_cost']:.2f} vs unoptimized",
                      delta_color="inverse")
            c3.metric(f"Recommended: Supplier {data['recommended']}", f"${data['daily_saving']:.2f}/day",
                      help="Monthly figure is a 30-day extrapolation, not a guarantee.")
            st.caption(f"≈ ${data['daily_saving'] * 30:.2f}/month (estimate)")

            table = pd.DataFrame(
                {
                    "Appliance": [s["appliance"] for s in res["A"]["schedules"]],
                    "Power (kW)": [s["power_kw"] for s in res["A"]["schedules"]],
                    "Hours": [s["hours"] for s in res["A"]["schedules"]],
                    "Supplier A schedule": [s["time_slots"] for s in res["A"]["schedules"]],
                    "Cost A ($)": [round(s["cost"], 2) for s in res["A"]["schedules"]],
                    "Supplier B schedule": [s["time_slots"] for s in res["B"]["schedules"]],
                    "Cost B ($)": [round(s["cost"], 2) for s in res["B"]["schedules"]],
                }
            )
            st.dataframe(table, hide_index=True, width="stretch")
