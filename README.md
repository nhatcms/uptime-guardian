# Uptime Guardian

A self-hosted, full-stack website monitoring system that watches a list of your
personal project URLs. It polls each target on a schedule, detects downtime,
slow responses, and SSL certificate problems, and sends alerts to your Telegram
chat. A Vue 3 dashboard shows real-time status and historical metrics.

## Features

- HTTP health checks with response-time tracking and 200–299 up/down
  classification.
- SSL certificate expiry checking for HTTPS targets, with a warning when fewer
  than 14 days remain.
- Scheduled per-monitor polling (APScheduler), plus an on-demand "Check Now".
- Telegram alerts for downtime (up → down transitions) and SSL expiry, with
  cooldowns to avoid alert spam.
- Check history and aggregate statistics (uptime %, avg/min/max response time,
  failed checks) over a configurable window.
- Vue 3 dashboard: per-monitor cards, uptime bars, response-time charts, and a
  detail view with the 50 most recent results.
- Single-user authentication. A default `admin` / `admin` account is seeded on
  first run (change it after logging in).

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy (SQLite), APScheduler, httpx,
  pydantic-settings.
- **Frontend:** Vue 3, Vite, TailwindCSS, Pinia, vue-router, Chart.js
  (vue-chartjs).

## Prerequisites

- Python 3.11 or newer.
- Node.js 20+ and [pnpm](https://pnpm.io/) (for the frontend).
- A Telegram bot and chat ID (see below).
- Optional: Docker and Docker Compose to run everything in containers.

### Create a Telegram bot (BotFather)

1. In Telegram, open a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts (choose a name and a username ending
   in `bot`).
3. BotFather replies with a **bot token** like `123456789:ABC-DEF...`. This is
   your `TELEGRAM_BOT_TOKEN`.
4. Find your **chat ID**:
   - Send any message to your new bot first.
   - Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
     and look for `"chat":{"id":...}`. That number is your `TELEGRAM_CHAT_ID`.
   - Alternatively, message [@userinfobot](https://t.me/userinfobot) to get your
     ID.

## Configuration

Copy the example env file at the repo root and fill in your values:

```bash
cp .env.example .env
```

| Variable                 | Required | Default                  | Description                                              |
| ------------------------ | -------- | ------------------------ | -------------------------------------------------------- |
| `DATABASE_URL`           | no       | `sqlite:///./uptime.db`  | SQLAlchemy database URL.                                 |
| `TELEGRAM_BOT_TOKEN`     | **yes**  | —                        | Bot token from BotFather.                                |
| `TELEGRAM_CHAT_ID`       | **yes**  | —                        | Chat ID that alerts are sent to.                         |
| `CHECK_INTERVAL_MINUTES` | no       | `5`                      | Default polling interval (positive integer).             |
| `ALERT_COOLDOWN_MINUTES` | no       | `10`                     | Minimum minutes between repeated down alerts.            |
| `AUTH_SECRET_KEY`        | **yes**  | —                        | Secret used to sign login tokens. Use a long random value. |

The backend refuses to start if a required value is missing.

## Local Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Ensure the .env file at the repo root is filled in (see Configuration).
# The backend loads .env from its working directory; either run from a dir
# that has .env or copy it into backend/.
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

On first start the backend creates the SQLite schema, seeds two example
monitors (Google and GitHub) and the default `admin` / `admin` user, and starts
the scheduler. The API is available at `http://localhost:8000` (interactive docs
at `http://localhost:8000/docs`).

### Frontend

```bash
cd frontend
cp .env.example .env             # sets VITE_API_BASE_URL=http://localhost:8000
pnpm install
pnpm dev
```

The dev server runs at `http://localhost:5173` (the backend's CORS is configured
for this origin). The frontend talks to the backend at the URL in
`VITE_API_BASE_URL` (default `http://localhost:8000`); requests are sent to its
`/api/...` routes.

Log in with `admin` / `admin`.

### Add your first monitor (via the UI)

1. Open the dashboard at `http://localhost:5173` and log in.
2. Click the floating **+** button (bottom-right) to open the Add Monitor form.
3. Enter a **name**, a fully qualified **URL** (e.g. `https://example.com`), and
   pick a **check interval** (5, 10, 15, or 30 minutes).
4. Submit. The monitor appears on the dashboard and is polled automatically; use
   **Check Now** on the detail view to run an immediate check.

## Run with Docker Compose

A `docker-compose.yml` at the repo root builds and runs both services.

```bash
cp .env.example .env             # fill in Telegram + AUTH_SECRET_KEY values
docker compose up --build
```

- **Backend:** `http://localhost:8000` (built from `./backend`). The SQLite
  database is stored on the named `sqlite_data` volume at `/data/uptime.db`, so
  history survives restarts. Compose overrides `DATABASE_URL` to
  `sqlite:////data/uptime.db` for this purpose.
- **Frontend:** `http://localhost:3000` (built from `./frontend`, served by
  nginx). The API base URL is baked in at build time via the
  `VITE_API_BASE_URL` build arg (default `http://localhost:8000`). If you deploy
  the backend on a different host/port, set that build arg accordingly and
  rebuild.

Stop the stack with `Ctrl+C`, or run `docker compose down`. To also remove the
stored database, run `docker compose down -v`.

## Project Structure

```
.
├── backend/          # FastAPI app, scheduler, checker, alerter, persistence
│   └── Dockerfile
├── frontend/         # Vue 3 + Vite dashboard
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── .env.example
└── README.md
```
