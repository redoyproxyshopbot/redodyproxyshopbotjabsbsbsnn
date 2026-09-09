# Telegram Bot on Render

This bot uses long polling for Telegram updates and starts a small Flask
health-check server on `0.0.0.0:$PORT`. Payment references are **not** checked
through the Binance API. A user submits an Order ID / TxID, the request is
saved as `Pending`, and an admin approves or rejects it from inline buttons.

## Required Render environment variables

Set these in the Render service's **Environment** tab:

| Variable | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `OWNER_ID` | Owner's numeric Telegram user ID (or set `ADMIN_ID` only) |
| `ADMIN_ID` | Admin's numeric Telegram user ID; can equal `OWNER_ID` |
| `BINANCE_PAY_ID` | Binance Pay ID shown to users |

Optional variables:

| Variable | Default |
| --- | --- |
| `OWNER_USERNAME` | `@your_username` |
| `UPDATE_CHANNEL` | `https://t.me/` |

Do **not** add `BINANCE_API_KEY` or `BINANCE_SECRET_KEY`; this version does
not use them.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="paste-your-token-here"
export OWNER_ID="123456789"
export ADMIN_ID="123456789"
export BINANCE_PAY_ID="your-pay-id"
python gxprivetbot.py
```

## Deploy to Render

1. Push `gxprivetbot.py`, `requirements.txt`, `Procfile`, and `.gitignore` to
   the GitHub repository.
2. In Render, choose **New + → Web Service**, connect GitHub, and select that
   repository.
3. Use these settings:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python gxprivetbot.py`
   - **Health Check Path:** `/`
4. Add the required environment variables above, deploy, and open the
   generated `https://...onrender.com/` URL. It should return `OK`.

## UptimeRobot

Create an HTTP(s) monitor for the Render URL, for example
`https://your-service.onrender.com/`, with a five-minute monitoring interval.
The root route returns HTTP 200 and is suitable for the monitor.

UptimeRobot can wake a sleeping free service and may help keep it warm, but it
is not a contractual guarantee of 24/7 uptime. For guaranteed always-on
operation, use a paid Render instance or another always-on hosting plan.

## Important data note

The included SQLite database and uploaded files live on the service
filesystem. Render restarts and some redeploys can erase files on plans
without persistent storage. For production subscriptions and uploads, use a
Render persistent disk (where available) or migrate the database and file
storage to durable services.