# ⚡ RetailFlex AI

**Agentic AI for intelligent appliance scheduling and retail electricity cost optimization.**

A consumer writes an email describing tomorrow's appliance needs. A single **CrewAI agent** (powered by `openai/gpt-oss-120b` on **Groq**):

1. 📧 reads the email and extracts appliances, power, hours and time windows
2. 🔎 looks up missing power ratings with free **DuckDuckGo** search
3. 📈 gets 24-hour price forecasts from **GridSense-A** and **GridSense-B** (two competing suppliers)
4. 🧮 runs a deterministic optimizer to find the cheapest schedule for each supplier
5. ✍️ writes a friendly reply email with schedules, costs and the recommended supplier

> The LLM handles language; math (forecasting and optimization) is done in Python, so numbers are exact.
> GridSense prices are **simulated** from forecasted load, solar, wind, net load and grid stress.

## Project structure

```
retailflex-ai/
├── app.py                        # Streamlit user interface
├── requirements.txt              # Python libraries (pinned versions)
├── README.md
├── .gitignore                    # keeps secrets out of GitHub
├── .streamlit/
│   └── secrets.toml.example      # template for your API keys
└── retailflex/
    ├── __init__.py
    ├── agent.py                  # the CrewAI agent + task
    ├── tools.py                  # GridSense optimizer tool + DuckDuckGo tool
    ├── gridsense.py              # GridSense-A / GridSense-B price forecasts
    └── optimizer.py              # appliance scheduling optimizer
```

## Run on your computer

Requires **Python 3.11, 3.12 or 3.13** (CrewAI does not support 3.14 yet).

```bash
cd retailflex-ai
python -m venv venv
# Windows:      venv\Scripts\activate
# Mac/Linux:    source venv/bin/activate
pip install -r requirements.txt
```

Create your secrets file: copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and paste your Groq key (free at <https://console.groq.com/keys>).

```bash
streamlit run app.py
```

## Deploy on Streamlit Cloud

1. Push this folder to a GitHub repository (the real `secrets.toml` is ignored automatically).
2. Go to <https://share.streamlit.io> → **Create app** → choose your repo, branch `main`, file `app.py`.
3. Click **Advanced settings** → Python version **3.12** → in **Secrets** paste:
   ```toml
   GROQ_API_KEY = "gsk_your_key"
   ```
4. Click **Deploy**. The first build takes ~3–5 minutes.

## Optional: send replies by Gmail

Turn on 2-Step Verification in your Google account, create an **App Password**
(Google Account → Security → App passwords), then add to your secrets:

```toml
GMAIL_ADDRESS = "yourname@gmail.com"
GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"
```

## Ideas for next versions

- Replace the simulated GridSense model in `gridsense.py` with a trained ML model on real data
- Read appliance lists from CSV/Excel attachments
- Poll a Gmail inbox automatically and reply without the UI
