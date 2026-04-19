# Requirements Document

## Introduction

Personal Uptime Guardian is a self-hosted, full-stack website monitoring system that proactively watches a list of personal project URLs. The system polls each monitored URL on a fixed schedule, detects downtime, slow responses, and SSL certificate problems, and dispatches alerts through the Telegram Bot API. A Vue 3 dashboard presents real-time status and historical metrics.

This document specifies the requirements for a 3-day MVP. The technology stack and project structure are fixed: a Python 3.11+ backend (FastAPI, SQLAlchemy with SQLite, APScheduler, httpx, pydantic-settings) and a Vue 3 frontend (Vite, TailwindCSS, Pinia, Chart.js via vue-chartjs). The system is single-user: the dashboard and all data endpoints are protected by a login session, with a default credential of username "admin" and password "admin" seeded on first run. Requirements prioritize correctness, reliability, and clarity.

## Glossary

- **Uptime_Guardian**: The complete self-hosted monitoring system, comprising backend and frontend.
- **Monitor**: A configured monitoring target consisting of a name, URL, active flag, check interval, creation timestamp, and failure-notification flag.
- **Check_Result**: A persisted record of a single check, holding status code, response time, up/down state, SSL validity, SSL days remaining, error message, and timestamp.
- **Checker**: The backend component that performs HTTP and SSL checks for a Monitor and returns a Check_Result.
- **Scheduler**: The backend component (APScheduler AsyncIOScheduler) that runs checks on a per-Monitor interval.
- **Alerter**: The backend component that formats and dispatches Telegram messages.
- **API_Layer**: The FastAPI REST interface consumed by the frontend.
- **Dashboard**: The Vue 3 frontend application.
- **Telegram_API**: The external Telegram Bot API endpoint used to deliver alerts.
- **User**: The single account record holding a username and a securely hashed password used to authenticate to the system.
- **Auth_Token**: A signed credential issued on successful login and required to access protected endpoints.
- **Auth_Component**: The backend component that verifies credentials, hashes passwords, and issues and validates Auth_Tokens.
- **Protected_Endpoint**: Any API_Layer route under /api/monitors or /api/results, each of which requires a valid Auth_Token.
- **Up**: A Monitor state where the most recent Check_Result has an HTTP status code in the range 200 to 299 inclusive.
- **Down**: A Monitor state where the most recent Check_Result has a status code outside 200 to 299, or no status code due to a connection failure.
- **Alert_Cooldown**: The minimum number of minutes, defined by ALERT_COOLDOWN_MINUTES, between repeated alerts for the same Monitor.
- **SSL_Warning_Threshold**: 14 days remaining before SSL certificate expiry, below which an SSL warning is dispatched.
- **Settings**: Configuration values loaded from a .env file via pydantic-settings.

## Requirements

### Requirement 1: Monitor Configuration Management

**User Story:** As a site owner, I want to create, view, update, and delete monitoring targets, so that I can control which URLs the system watches.

#### Acceptance Criteria

1. WHEN a client sends a create request with a name, a URL, and a check interval, THE API_Layer SHALL persist a new Monitor with is_active set to true and respond with HTTP status code 201.
2. WHEN a client sends a create request with a malformed URL, THE API_Layer SHALL reject the request and respond with HTTP status code 422.
3. IF persisting a new Monitor fails due to a database error, THEN THE API_Layer SHALL respond with HTTP status code 500.
3. WHEN a client requests the monitor list, THE API_Layer SHALL return all Monitor records with the latest Check_Result embedded for each Monitor.
4. WHEN a client requests a single Monitor by identifier that exists, THE API_Layer SHALL return that Monitor with its 50 most recent Check_Result records.
5. IF a client requests a single Monitor by identifier that does not exist, THEN THE API_Layer SHALL respond with HTTP status code 404.
6. WHEN a client sends an update request for an existing Monitor with name, URL, active flag, and interval, THE API_Layer SHALL apply the changes and return the updated Monitor.
7. WHEN a client sends a delete request for an existing Monitor, THE API_Layer SHALL delete that Monitor and all Check_Result records associated with that Monitor.

### Requirement 2: HTTP Health Checking

**User Story:** As a site owner, I want each monitored URL checked over HTTP, so that I know whether the site is reachable and how fast it responds.

#### Acceptance Criteria

1. WHEN the Checker checks a Monitor, THE Checker SHALL send an HTTP request using an asynchronous client with a request timeout of 10.0 seconds.
2. WHEN the Checker receives an HTTP response, THE Checker SHALL record the elapsed time from request start to response receipt as response_time_ms in milliseconds.
3. WHEN the Checker receives an HTTP response with a status code in the range 200 to 299 inclusive, THE Checker SHALL set is_up to true in the Check_Result.
4. WHEN the Checker receives an HTTP response with a status code outside the range 200 to 299, THE Checker SHALL set is_up to false in the Check_Result.
5. IF the Checker encounters a connection failure, a timeout, or any other request exception, THEN THE Checker SHALL set status_code to null, set is_up to false, and store the exception description in error_message.
6. THE Checker SHALL return a Check_Result object without persisting it.

### Requirement 3: SSL Certificate Checking

**User Story:** As a site owner, I want SSL certificate expiry checked for HTTPS sites, so that I can renew certificates before they expire.

#### Acceptance Criteria

1. WHERE a Monitor URL begins with the scheme https, THE Checker SHALL retrieve the SSL certificate by connecting to the host on port 443 and compute ssl_days_remaining from the certificate notAfter field.
2. WHEN the Checker computes a positive ssl_days_remaining value from a certificate that passes validation, THE Checker SHALL set ssl_valid to true in the Check_Result.
3. IF the SSL check raises an exception OR the retrieved certificate fails validation, THEN THE Checker SHALL set ssl_valid to false, set ssl_days_remaining to 0, and complete the Check_Result without aborting the HTTP check outcome.
4. WHERE a Monitor URL does not begin with the scheme https, THE Checker SHALL set ssl_valid and ssl_days_remaining to null in the Check_Result.

### Requirement 4: Scheduled Polling

**User Story:** As a site owner, I want each active monitor polled automatically on its own interval, so that I get continuous monitoring without manual action.

#### Acceptance Criteria

1. WHEN the Uptime_Guardian starts, THE Scheduler SHALL load all active Monitor records and register one recurring job per Monitor using that Monitor's check_interval_minutes value.
2. WHEN a scheduled job runs, THE Scheduler SHALL invoke the Checker for the corresponding Monitor and persist the returned Check_Result.
3. WHEN a new Monitor is added through the API_Layer, THE Scheduler SHALL register a job for that Monitor without requiring a restart.
4. THE Scheduler SHALL execute checks without blocking the API_Layer event loop.
5. WHEN a client sends a check-now request for an existing Monitor, THE API_Layer SHALL trigger an immediate check for that Monitor outside the scheduled interval and persist the resulting Check_Result.

### Requirement 5: Downtime Alerting

**User Story:** As a site owner, I want a Telegram alert when a site goes down, so that I can respond quickly to outages.

#### Acceptance Criteria

1. WHEN a scheduled check produces a Check_Result with is_up false AND the immediately preceding Check_Result for the same Monitor had is_up true, THE Alerter SHALL dispatch a site-down Telegram message.
2. THE site-down Telegram message SHALL contain the Monitor name, the Monitor URL, the status code, the check timestamp in UTC, and the error description.
3. IF a Monitor received a down alert within the most recent Alert_Cooldown window, THEN THE Alerter SHALL suppress further down alerts for that Monitor until the window elapses.
4. WHERE a Monitor has notify_on_failure set to false, THE Alerter SHALL suppress down alerts for that Monitor.
5. IF a Telegram dispatch raises an exception, THEN THE Alerter SHALL record the failure in the log and allow the check cycle to continue.

### Requirement 6: SSL Expiry Alerting

**User Story:** As a site owner, I want a Telegram warning when a certificate is close to expiring, so that I can renew it in time.

#### Acceptance Criteria

1. WHEN a scheduled check produces a Check_Result with ssl_days_remaining below the SSL_Warning_Threshold of 14, THE Alerter SHALL dispatch an SSL-warning Telegram message.
2. THE SSL-warning Telegram message SHALL contain the Monitor name, the number of days remaining, and the Monitor URL.
3. IF an SSL warning was dispatched for a Monitor less than 24 hours earlier, measured by the absolute timestamp of the last SSL warning, THEN THE Alerter SHALL suppress further SSL warnings for that Monitor until 24 hours have elapsed.

### Requirement 7: Telegram Message Delivery

**User Story:** As a site owner, I want alert messages delivered to my Telegram chat, so that I receive notifications on my device.

#### Acceptance Criteria

1. WHEN the Alerter dispatches a message, THE Alerter SHALL send an HTTP POST to the Telegram_API sendMessage endpoint for the configured bot token, with a body containing the configured chat identifier, the message text, and parse_mode set to HTML.
2. THE Alerter SHALL read the bot token and the chat identifier from Settings.
3. IF the Telegram_API request fails for any reason, including network timeouts and malformed responses, THEN THE Alerter SHALL record the failure in the log and return without raising an exception to the caller.

### Requirement 8: Check History and Statistics

**User Story:** As a site owner, I want to query recent check history and aggregate statistics, so that I can understand a site's reliability over time.

#### Acceptance Criteria

1. WHEN a client requests results for a Monitor with a limit value, THE API_Layer SHALL return the most recent Check_Result records for that Monitor up to the requested limit.
2. WHEN a client requests statistics for a Monitor over a time window in hours, THE API_Layer SHALL return uptime_percentage, avg_response_time_ms, total_checks, failed_checks, min_response_time_ms, and max_response_time_ms computed over that window.
3. THE uptime_percentage SHALL equal the count of Check_Result records with is_up true divided by total_checks within the requested window, expressed as a percentage.
4. IF the requested window contains no Check_Result records, THEN THE API_Layer SHALL return zero values for total_checks and failed_checks without raising an error.

### Requirement 9: Configuration and Settings

**User Story:** As an operator, I want all environment-specific values loaded from configuration, so that no operational value is hardcoded.

#### Acceptance Criteria

1. THE Settings SHALL load DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_INTERVAL_MINUTES, ALERT_COOLDOWN_MINUTES, and AUTH_SECRET_KEY from a .env file.
2. IF TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is absent at startup, THEN THE Uptime_Guardian SHALL report a configuration error identifying the missing value.
3. WHERE CHECK_INTERVAL_MINUTES or ALERT_COOLDOWN_MINUTES is absent, THE Settings SHALL apply default values of 5 and 10 respectively.
4. IF a present CHECK_INTERVAL_MINUTES or ALERT_COOLDOWN_MINUTES value is not a positive integer, THEN THE Settings SHALL apply the corresponding default value.

### Requirement 10: Persistence and Initialization

**User Story:** As an operator, I want the database schema created automatically and example monitors seeded on first run, so that the system is usable immediately after startup.

#### Acceptance Criteria

1. WHEN the Uptime_Guardian starts, THE Uptime_Guardian SHALL create the database tables for Monitor and Check_Result records if they do not already exist.
2. IF database table creation fails at startup, THEN THE Uptime_Guardian SHALL halt startup and report the failure.
3. WHEN the Uptime_Guardian starts AND the Monitor table contains no records, THE Uptime_Guardian SHALL insert a Monitor named "Google" with URL "https://www.google.com" and interval 5, and a Monitor named "GitHub" with URL "https://github.com" and interval 5.
4. WHEN the Uptime_Guardian starts AND the User table contains no records, THE Uptime_Guardian SHALL insert a User with username "admin" and a securely hashed form of the password "admin".
5. WHEN the Uptime_Guardian shuts down, THE Scheduler SHALL stop all scheduled jobs.

### Requirement 11: Dashboard Display

**User Story:** As a site owner, I want a dashboard that shows current status and history, so that I can assess all my sites at a glance.

#### Acceptance Criteria

1. WHEN the Dashboard loads, THE Dashboard SHALL display the total Monitor count and the global uptime percentage over the most recent 24 hours.
2. THE Dashboard SHALL render one card per Monitor showing the Monitor name, URL, up-or-down status from the latest Check_Result, current response time, and SSL status.
3. WHILE the Dashboard is open, THE Dashboard SHALL refresh Monitor data every 30 seconds.
4. THE Dashboard SHALL render an uptime bar of the 30 most recent Check_Result records per Monitor, using distinct visual states for up, down, and no-data.
5. WHEN a site owner selects a Monitor card, THE Dashboard SHALL navigate to a detail view showing monitor information, 24-hour statistics, a response-time chart, and a table of the 50 most recent Check_Result records.
6. WHEN a site owner submits the add-monitor form with a name, a URL, and a selected interval, THE Dashboard SHALL send a create request to the API_Layer and refresh the Monitor list on success.
7. IF an API_Layer request returns an error, THEN THE Dashboard SHALL present an error indication and preserve the last successfully loaded data.
8. WHILE no valid Auth_Token is held by the Dashboard, THE Dashboard SHALL redirect navigation to protected views to the login view.
9. WHEN the Dashboard sends a request to a Protected_Endpoint, THE Dashboard SHALL attach the held Auth_Token to the request headers.

### Requirement 12: Single-User Authentication

**User Story:** As the system owner, I want the dashboard and data endpoints protected by a login, so that only I can view and manage my monitors.

#### Acceptance Criteria

1. WHEN a client submits a login request with a username and password that match the stored User credentials, THE Auth_Component SHALL issue an Auth_Token and respond with HTTP status code 200.
2. IF a client submits a login request with a username or password that does not match the stored User credentials, THEN THE Auth_Component SHALL respond with HTTP status code 401 and SHALL NOT issue an Auth_Token.
3. THE Auth_Component SHALL store and compare passwords only as secure cryptographic hashes, never as plaintext.
4. WHEN a client requests a Protected_Endpoint without a valid Auth_Token, THE API_Layer SHALL respond with HTTP status code 401 and SHALL NOT perform the requested operation.
5. WHEN a client requests a Protected_Endpoint with a valid Auth_Token, THE API_Layer SHALL authorize the request and perform the requested operation.
6. WHEN the Auth_Component validates an Auth_Token, THE Auth_Component SHALL verify the token signature and reject a token whose signature is invalid or whose validity period has elapsed.
