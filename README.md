# NCMS Monitor (Uptime Guardian) — Multi-Tenant SaaS

A self-hosted, multi-tenant website monitoring platform. Each user owns their
own monitors, gets per-user Telegram alerts, and subscribes to a plan (Free /
Pro / Enterprise) that controls how many monitors they can run, how often
checks run, and whether SSL certificate monitoring is enabled. It ships with a
public landing page, bot-protected sign-up/login (Cloudflare Turnstile), a
self-service dashboard, paid upgrades via SePay (Vietnamese bank-transfer QR),
and an admin console.

This README focuses on **how to turn the system on and open the web interface**.

---

## TL;DR — fastest way to the web UI

You need **two processes running**: the backend API (port 8000) and the
frontend dev server (port 5173).

```bash
# 1. Configure (from the repo root)
cp .env.example .env          # then edit .env — see "Configuration" below

# 2. Start the backend (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env .                  # backend loads .env from its own working dir
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 3. Start the frontend (terminal 2)
cd frontend
cp .env.example .env          # sets VITE_API_BASE_URL=http://localhost:8000
pnpm install
pnpm dev
```

Then open the web interface at **http://localhost:5173**.

- Default admin login: **`admin` / `admin`** (seeded on first run; change it).
- Or click **Get started free** on the landing page to register a new account.

> Prefer containers? Jump to [Run with Docker Compose](#run-with-docker-compose)
> and open **http://localhost:3000**.

---

## Prerequisites

- Python **3.11+**
- Node.js **20+** and [pnpm](https://pnpm.io/) (`corepack enable` then
  `corepack prepare pnpm@9.15.4 --activate`)
- A Telegram bot token + chat ID (for alerts — see below)
- Optional: Docker + Docker Compose
- Optional: a Cloudflare Turnstile site/secret key and SePay credentials
  (both have safe dev fallbacks — you can run the whole UI without them)

---

## Configuration

Copy the example env file at the repo root and fill it in:

```bash
cp .env.example .env
```

### Required

| Variable             | Description                                              |
| -------------------- | -------------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather (alert delivery).               |
| `TELEGRAM_CHAT_ID`   | Legacy/global chat ID; copied to the migrated admin user. Per-user chat IDs are set in the dashboard. |
| `AUTH_SECRET_KEY`    | Secret used to sign login tokens — use a long random value. |

The backend refuses to start if a required value is missing.

### Common optional

| Variable                 | Default                  | Description                                          |
| ------------------------ | ------------------------ | ---------------------------------------------------- |
| `DATABASE_URL`           | `sqlite:///./uptime.db`  | SQLAlchemy database URL.                             |
| `CHECK_INTERVAL_MINUTES` | `5`                      | Default polling interval.                            |
| `ALERT_COOLDOWN_MINUTES` | `10`                     | Minimum minutes between repeated down alerts.        |
| `CORS_ALLOW_ORIGINS`     | `http://localhost:5173,http://localhost:3000` | Allowed browser origins (comma-separated, or `*`).  |

### Cloudflare Turnstile (bot protection on register/login)

| Variable                | Default                          | Description                                                |
| ----------------------- | -------------------------------- | ---------------------------------------------------------- |
| `TURNSTILE_SECRET_KEY`  | *(empty)*                        | Leave empty for **dev mode**: any non-empty token passes.  |
| `TURNSTILE_VERIFY_URL`  | Cloudflare siteverify URL        | Override only if needed.                                   |

In dev mode the login/register forms show a **"Complete bot challenge (dev)"**
button instead of the real widget — click it to produce a token, then submit.
For production, set a real `TURNSTILE_SECRET_KEY` on the backend and
`VITE_TURNSTILE_SITE_KEY` on the frontend (see below).

### SePay payments (optional — only needed for paid upgrades)

| Variable                | Description                                             |
| ----------------------- | ------------------------------------------------------- |
| `SEPAY_API_KEY`         | API key SePay sends on webhook calls (`Authorization: Apikey <key>`). |
| `SEPAY_WEBHOOK_SECRET`  | Shared secret for optional HMAC-SHA256 webhook verification. |
| `SEPAY_BANK_CODE`       | Receiving bank code encoded into the QR (e.g. `MBBank`).|
| `SEPAY_ACCOUNT_NUMBER`  | Receiving account number for the QR.                    |
| `SEPAY_QR_BASE_URL`     | SePay QR image base URL (default `https://qr.sepay.vn/img`). |

If neither `SEPAY_API_KEY` nor `SEPAY_WEBHOOK_SECRET` is set, webhook signature
verification is disabled (dev only).

> **Never commit real secrets.** Keep them in `.env` (git-ignored). The QR/
> payment flow is optional; the rest of the app works without SePay configured.

### Frontend env (`frontend/.env`)

| Variable                  | Default                  | Description                              |
| ------------------------- | ------------------------ | ---------------------------------------- |
| `VITE_API_BASE_URL`       | `http://localhost:8000`  | Backend base URL the browser calls.      |
| `VITE_TURNSTILE_SITE_KEY` | *(empty)*                | Cloudflare site key; empty = dev button. |

---

## Turning it on (local development)

### 1. Backend (API + scheduler) — port 8000

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env .                       # the backend reads .env from its cwd
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

On first start the backend will:
- create the SQLite schema,
- run the one-time multi-tenant migration (idempotent),
- seed the **Free** plan and the default **`admin` / `admin`** account (admin),
- seed two example monitors and start the scheduler.

Check it's up: open **http://localhost:8000/docs** (interactive API docs) or
**http://localhost:8000/api/plans** (public plan list).

### 2. Frontend (web interface) — port 5173

```bash
cd frontend
cp .env.example .env
pnpm install
pnpm dev
```

Open **http://localhost:5173**.

---

## Accessing the web interface

| Page                | URL (dev)                       | Who                          |
| ------------------- | ------------------------------- | ---------------------------- |
| Landing / pricing   | `http://localhost:5173/`        | Public                       |
| Register            | `http://localhost:5173/register`| Public                       |
| Login               | `http://localhost:5173/login`   | Public                       |
| Dashboard           | `http://localhost:5173/dashboard`| Logged-in users             |
| Admin console       | `http://localhost:5173/admin`   | Admins only (`is_admin`)     |

### First steps in the UI

1. **Landing page** (`/`) shows live pricing pulled from the database. Click
   **Get started free** to go to registration.
2. **Register** (`/register`): enter username, email, password, complete the
   bot challenge (the dev button in dev mode), and submit. New accounts start on
   the **Free** plan.
3. **Login** (`/login`): sign in (complete the bot challenge first). Use
   `admin` / `admin` for the seeded admin account.
4. **Dashboard** (`/dashboard`):
   - Add monitors with the floating **+** button (limited by your plan).
   - Open **Settings** to see your plan limits, "used of total" usage, set your
     **Telegram chat ID** (so alerts go to you), and **upgrade** to a paid plan
     (renders a SePay QR code).
   - Admins see an **Admin** link to the console.
5. **Admin console** (`/admin`, admins only): create/edit/delete plans, view all
   users, and view payment transactions.

### Get your Telegram chat ID (for alerts)

1. Message your bot once (the one whose token is in `TELEGRAM_BOT_TOKEN`).
2. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` and read
   `"chat":{"id":...}` — that number is your chat ID.
3. Paste it into **Dashboard → Settings → Telegram chat ID** and save. Alerts
   for your monitors are then delivered to your own chat.

---

## Run with Docker Compose

Builds and runs both services; the SQLite DB persists on a named volume.

```bash
cp .env.example .env               # fill in Telegram + AUTH_SECRET_KEY
docker compose up --build
```

- **Web interface:** **http://localhost:3000**
- **Backend API:** http://localhost:8000 (docs at `/docs`)

The frontend's API base URL is baked in at build time via the
`VITE_API_BASE_URL` build arg (default `http://localhost:8000`). If you deploy
the backend elsewhere, set that arg in `docker-compose.yml` and rebuild.

Stop with `Ctrl+C` or `docker compose down`. To also wipe the stored database,
`docker compose down -v`.

> Accessing over your LAN by IP? Set `CORS_ALLOW_ORIGINS=*` (or your specific
> origin) in `.env`, and point `VITE_API_BASE_URL` at the backend's reachable
> address.

---

## SePay payment webhook (optional)

For automatic paid-plan upgrades, configure SePay to POST payment confirmations
to:

```
POST http://<your-backend-host>:8000/api/payments/sepay-webhook
```

This is the only endpoint not protected by a login token; it is secured by the
`SEPAY_API_KEY` (or HMAC `SEPAY_WEBHOOK_SECRET`) signature and strict amount
matching. It must be reachable from the public internet for real payments.

---

## Tests

```bash
# Backend (from backend/, venv active)
python -m pytest

# Frontend (from frontend/)
pnpm test
```

---

## Project structure

```
.
├── backend/          # FastAPI app: routers, plans, tenancy, turnstile,
│   │                 # payments/, scheduler, checker, alerter, migration
│   └── Dockerfile
├── frontend/         # Vue 3 + Vite dashboard, admin console, landing page
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Troubleshooting

- **Backend won't start / "Missing required configuration value(s)":** set
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and `AUTH_SECRET_KEY` in `.env`, and
  make sure the backend can see that `.env` (copy it into `backend/` or run
  uvicorn from a directory that contains it).
- **Login/register button does nothing:** you must complete the bot challenge
  first (in dev mode, click the "Complete bot challenge (dev)" button).
- **CORS errors in the browser console:** add your frontend origin to
  `CORS_ALLOW_ORIGINS` (or use `*`) and restart the backend.
- **Can't reach the API from the frontend:** confirm `VITE_API_BASE_URL` in
  `frontend/.env` points at the backend, and restart `pnpm dev` after changing
  it.
- **No Telegram alerts:** set your per-user **Telegram chat ID** in Dashboard →
  Settings; a monitor must transition up → down (and respect the cooldown) to
  fire an alert.
```
