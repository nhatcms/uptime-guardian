# Requirements Document

## Introduction

This feature refactors the existing single-user "Uptime Guardian" / NCMS Monitor application into a multi-tenant Software-as-a-Service (SaaS) platform. The current system supports one account, a single global Telegram alert channel, and unrestricted monitor creation. The refactor introduces subscription plans (Free, Pro, Enterprise), per-user data ownership and isolation, plan-based enforcement of monitor limits and feature gating, per-user Telegram alert channels, bot protection via Cloudflare Turnstile on authentication flows, and paid plan upgrades via SePay (Vietnamese bank-transfer payment gateway). The frontend gains a public marketing landing page, Turnstile-protected auth pages, a self-service user dashboard for plan and alert configuration, and an administrative console for managing plans, users, and payment records.

The refactor must preserve the existing monitoring, checking, scheduling, and alerting behavior for migrated data and must remain backward compatible so that existing monitors continue to be checked after migration.

## Glossary

- **Platform**: The complete multi-tenant SaaS system, comprising backend, scheduler, and frontend.
- **API**: The FastAPI backend that exposes REST endpoints under the `/api` prefix.
- **Tenant_User**: An authenticated end-user account that owns its own monitors, alert configuration, and subscription. Stored in the `users` table.
- **Admin_User**: A Tenant_User whose `is_admin` flag is true, granting access to administrative endpoints and the administrative console.
- **Plan**: A subscription tier record (Free, Pro, or Enterprise) stored in the `plans` table, defining price and feature limits.
- **Max_Monitors**: The integer attribute of a Plan defining the maximum number of monitors a Tenant_User on that Plan may own.
- **Min_Interval_Minutes**: The integer attribute of a Plan defining the smallest permitted monitor check interval in whole minutes for a Tenant_User on that Plan.
- **SSL_Check_Enabled**: The boolean attribute of a Plan controlling whether SSL certificate checking is performed for a Tenant_User's monitors.
- **Plan_Expires_At**: The timestamp after which a Tenant_User's paid Plan is no longer active.
- **Monitor**: A configured monitoring target owned by exactly one Tenant_User. Stored in the `monitors` table.
- **Check_Result**: A persisted record of a single check performed against a Monitor.
- **Transaction**: A persisted record of a SePay payment attempt or confirmation, stored in the `transactions` table.
- **Scheduler**: The APScheduler-based component that polls active monitors on their configured intervals.
- **Alerter**: The component that dispatches Telegram notifications for down and SSL events.
- **Telegram_Chat_Id**: The per-Tenant_User Telegram chat identifier to which that user's alerts are sent.
- **Turnstile**: Cloudflare Turnstile, a bot-detection challenge presented on the registration and login pages.
- **Turnstile_Token**: The client-side token produced by the Turnstile widget and submitted to the API for server-side verification.
- **SePay**: The Vietnamese bank-transfer payment gateway (https://developer.sepay.vn/vi) used for paid Plan upgrades.
- **SePay_Webhook**: The API endpoint `/api/payments/sepay-webhook` that receives payment confirmations from SePay.
- **Webhook_Signature**: The authentication value supplied by SePay with a webhook request, used to verify the request originates from SePay.
- **Auth_Token**: A signed JWT issued on successful authentication that identifies the Tenant_User.
- **Landing_Page**: The public marketing page served at the root route `/`.
- **Admin_Console**: The administrative frontend served at the route `/admin`.

## Requirements

### Requirement 1: Subscription Plan Model

**User Story:** As a Platform operator, I want subscription plans stored as data records, so that pricing tiers and feature limits can be managed without code changes.

#### Acceptance Criteria

1. THE Platform SHALL persist each Plan with the attributes id, name, price, Max_Monitors, SSL_Check_Enabled, and Min_Interval_Minutes.
2. THE Platform SHALL store the Plan price as a number from 0 to 999,999.99 inclusive, where a value of 0 designates a free Plan.
3. THE Platform SHALL store Min_Interval_Minutes as an integer from 1 to 1440 inclusive.
4. THE Platform SHALL store Max_Monitors as an integer from 0 to 100000 inclusive.
5. THE Platform SHALL store SSL_Check_Enabled as a boolean value (true or false).
6. THE Platform SHALL store each Plan name as a non-empty string of 1 to 100 characters that is unique across all Plans, compared case-insensitively.
7. IF a request to create or update a Plan supplies a name that matches an existing Plan name (case-insensitive), or supplies any attribute that violates the bounds in criteria 2 through 6, THEN THE Platform SHALL reject the operation, leave all existing Plan records unchanged, and return an error response indicating the specific attribute that failed validation.
8. WHEN the Platform initializes a database that contains no Plan records, THE Platform SHALL seed a single Free Plan with name "Free", price 0, Max_Monitors 1, SSL_Check_Enabled false, and Min_Interval_Minutes 5.

### Requirement 2: Tenant User Model

**User Story:** As a developer, I want each user record to carry identity, alert, and subscription attributes, so that the Platform can support many isolated accounts.

#### Acceptance Criteria

1. THE Platform SHALL persist each Tenant_User with the attributes id, username, email, hashed_password, Telegram_Chat_Id, plan_id, Plan_Expires_At, and is_admin.
2. THE Platform SHALL enforce uniqueness of the Tenant_User username, where the username is between 1 and 255 characters in length.
3. THE Platform SHALL enforce uniqueness of the Tenant_User email, where the email is between 3 and 320 characters in length.
4. THE Platform SHALL store the Tenant_User password only as a hashed value.
5. WHEN a Tenant_User is created without an assigned Plan, THE Platform SHALL assign the Free Plan to that Tenant_User.
6. THE Platform SHALL allow Telegram_Chat_Id to be empty for a Tenant_User that has not configured alerts.
7. THE Platform SHALL allow Plan_Expires_At to be empty for a Tenant_User on the Free Plan.
8. WHEN a Tenant_User is created without a specified is_admin value, THE Platform SHALL set is_admin to false.
9. IF a Tenant_User is created or updated with a username or email that matches an existing Tenant_User, THEN THE Platform SHALL reject the operation, return an error indicating which attribute violated uniqueness, and preserve all existing Tenant_User records unchanged.
10. IF a Tenant_User is created or updated with an email that does not match the format local-part@domain, THEN THE Platform SHALL reject the operation and return an error indicating the email format is invalid.

### Requirement 3: Monitor Ownership

**User Story:** As a Tenant_User, I want my monitors associated with my account, so that my monitoring data is separated from other users' data.

#### Acceptance Criteria

1. THE Platform SHALL associate each Monitor with exactly one owning Tenant_User through a non-null user_id reference.
2. WHEN a Tenant_User creates a Monitor, THE API SHALL set the Monitor's owner to the authenticated Tenant_User derived from the request credentials.
3. WHEN a Tenant_User is deleted, THE Platform SHALL delete all Monitors owned by that Tenant_User and their associated Check_Results atomically, such that either all are deleted or none are deleted.
4. WHEN an authenticated Tenant_User requests Monitor data, THE API SHALL return only the Monitors owned by that Tenant_User.
5. IF an authenticated Tenant_User attempts to access or modify a Monitor owned by a different Tenant_User, THEN THE API SHALL reject the request and SHALL leave the targeted Monitor unchanged.
6. IF an unauthenticated request attempts to create, modify, or delete a Monitor, THEN THE API SHALL reject the request and SHALL NOT create, modify, or delete any Monitor.

### Requirement 4: Tenant Data Isolation

**User Story:** As a Tenant_User, I want to access only my own monitors and results, so that my data remains private from other tenants.

#### Acceptance Criteria

1. WHEN an authenticated Tenant_User requests a list of Monitors, THE API SHALL return only the Monitors owned by that Tenant_User.
2. WHEN an authenticated Tenant_User requests a list of Monitors and that Tenant_User owns zero Monitors, THE API SHALL return an empty list with HTTP status 200.
3. WHEN an authenticated Tenant_User requests a Monitor owned by that Tenant_User, THE API SHALL return that Monitor with HTTP status 200.
4. IF an authenticated Tenant_User requests a Monitor owned by a different Tenant_User, THEN THE API SHALL respond with HTTP status 404 and SHALL exclude any attribute values of that Monitor from the response body.
5. IF an authenticated Tenant_User requests a Monitor identifier that does not exist, THEN THE API SHALL respond with HTTP status 404, using a response indistinguishable from the response for a Monitor owned by a different Tenant_User.
6. IF an authenticated Tenant_User requests Check_Results for a Monitor owned by a different Tenant_User, THEN THE API SHALL respond with HTTP status 404 and SHALL exclude any Check_Results data from the response body.
7. IF an authenticated Tenant_User attempts to update or delete a Monitor owned by a different Tenant_User, THEN THE API SHALL respond with HTTP status 404 and SHALL leave the targeted Monitor and its associated Check_Results unchanged.

### Requirement 5: Monitor Count Limit Enforcement

**User Story:** As a Platform operator, I want monitor creation limited by the user's plan, so that plan tiers have meaningful value.

#### Acceptance Criteria

1. WHEN an authenticated Tenant_User requests creation of a Monitor and the Tenant_User has an active Plan and the count of Monitors the Tenant_User owns is strictly less than the Max_Monitors of that active Plan, THE API SHALL create the Monitor and SHALL respond with HTTP status 201 and a response body representing the created Monitor.
2. IF an authenticated Tenant_User requests creation of a Monitor and the Tenant_User has an active Plan and the count of Monitors the Tenant_User owns is equal to or greater than the Max_Monitors of that active Plan, THEN THE API SHALL reject the request with HTTP status 403, SHALL NOT create the Monitor, and SHALL return a response body indicating that the monitor limit has been reached and stating the Max_Monitors value of the active Plan.
3. IF an authenticated Tenant_User requests creation of a Monitor and the Tenant_User has no active Plan, THEN THE API SHALL reject the request with HTTP status 403, SHALL NOT create the Monitor, and SHALL return a response body indicating that no active Plan is in effect.
4. WHILE two or more creation requests from the same Tenant_User are processed concurrently, THE API SHALL enforce the Max_Monitors limit atomically such that the count of Monitors the Tenant_User owns never exceeds the Max_Monitors of the active Plan.

### Requirement 6: Check Interval Limit Enforcement

**User Story:** As a Platform operator, I want check intervals bounded by the user's plan, so that higher-frequency monitoring is reserved for paid plans.

#### Acceptance Criteria

1. WHEN an authenticated Tenant_User requests creation of a Monitor with a check interval that is a positive integer number of minutes greater than or equal to the Min_Interval_Minutes of the Tenant_User's active Plan, THE API SHALL create the Monitor with the requested interval, comparing the requested interval directly against Min_Interval_Minutes.
2. IF an authenticated Tenant_User requests creation of a Monitor with a check interval less than the Min_Interval_Minutes of the Tenant_User's active Plan, THEN THE API SHALL reject the request with HTTP status 403 and SHALL NOT create the Monitor.
3. WHEN an authenticated Tenant_User requests an update that changes a Monitor's check interval to a value greater than or equal to the Min_Interval_Minutes of the Tenant_User's active Plan, THE API SHALL apply the requested interval to the Monitor.
4. WHEN an authenticated Tenant_User requests an update that changes a Monitor's check interval to a value less than the Min_Interval_Minutes of the Tenant_User's active Plan, THE API SHALL reject the request with HTTP status 403 and SHALL leave the Monitor's stored interval unchanged.
5. IF an authenticated Tenant_User requests creation or update of a Monitor with a check interval that is missing, null, non-numeric, zero, or negative, THEN THE API SHALL reject the request with an error response indicating the interval value is invalid and SHALL NOT create or modify the Monitor.
6. IF an authenticated Tenant_User requests creation or update of a Monitor and no active Plan can be resolved for the Tenant_User, THEN THE API SHALL reject the request with HTTP status 403 and SHALL NOT create or modify the Monitor.

### Requirement 7: SSL Check Feature Gating

**User Story:** As a Platform operator, I want SSL checking gated by plan, so that certificate monitoring is a differentiating feature.

#### Acceptance Criteria

1. WHILE the active Plan of a Monitor's owning Tenant_User has SSL_Check_Enabled set to false, THE Scheduler SHALL record all SSL fields as empty for that Monitor's Check_Results from the next check cycle onward.
2. WHILE the active Plan of a Monitor's owning Tenant_User has SSL_Check_Enabled set to false, THE Scheduler SHALL leave Check_Results stored before the next check cycle unchanged.
3. WHILE the active Plan of a Monitor's owning Tenant_User has SSL_Check_Enabled set to true and the Monitor URL uses the https scheme, THE Scheduler SHALL perform SSL certificate checking and record the resulting SSL fields in Check_Results from the next check cycle onward.
4. IF the active Plan of a Monitor's owning Tenant_User has SSL_Check_Enabled set to true and the Monitor URL does not use the https scheme, THEN THE Scheduler SHALL record all SSL fields as empty and SHALL NOT perform SSL certificate checking.
5. WHILE the active Plan of a Monitor's owning Tenant_User has SSL_Check_Enabled set to false, THE Alerter SHALL NOT dispatch SSL warnings for that Monitor.

### Requirement 8: Plan-Aware Scheduling

**User Story:** As a Platform operator, I want the scheduler to honor each user's plan interval, so that polling frequency matches the user's entitlements.

#### Acceptance Criteria

1. WHEN the Scheduler registers a Monitor for polling, THE Scheduler SHALL set the effective polling interval to the greater of the Monitor's configured interval and the Min_Interval_Minutes of the Monitor owner's active Plan.
2. IF a Monitor's owning Tenant_User has no active Plan, THEN THE Scheduler SHALL skip registration of that Monitor and SHALL record a log entry indicating the reason.
3. WHILE a Monitor's is_active flag is true, THE Scheduler SHALL include that Monitor in polling.
4. WHILE a Monitor's is_active flag is false, THE Scheduler SHALL exclude that Monitor from polling.
5. WHEN a Tenant_User's Plan changes, THE Scheduler SHALL apply the new Plan's Min_Interval_Minutes to that Tenant_User's Monitors within 60 seconds without requiring a Platform restart, recomputing the effective polling interval for each affected Monitor.

### Requirement 9: Per-User Telegram Alerting

**User Story:** As a Tenant_User, I want alerts delivered to my own Telegram chat, so that I receive notifications for my monitors only.

#### Acceptance Criteria

1. WHEN the Alerter dispatches an alert for a Monitor, THE Alerter SHALL send the alert only to the Telegram_Chat_Id of the Monitor's owning Tenant_User and SHALL NOT send the alert to the Telegram_Chat_Id of any other Tenant_User.
2. IF the Monitor's owning Tenant_User has a Telegram_Chat_Id that is empty, unset, or contains only whitespace, THEN THE Alerter SHALL skip dispatching the alert and SHALL record a log entry indicating the skip together with the Monitor identifier and the reason (missing Telegram_Chat_Id).
3. IF dispatching a Telegram alert fails due to a network error, a non-success response from Telegram, or the dispatch attempt exceeding the 10-second timeout, THEN THE Alerter SHALL record a log entry indicating the failure together with the Monitor identifier, SHALL NOT raise an exception into the caller, and SHALL continue the check cycle for remaining Monitors.
4. WHEN the Alerter dispatches an alert for a Monitor, THE Alerter SHALL complete the dispatch attempt within 10 seconds and SHALL treat any attempt exceeding 10 seconds as a dispatch failure.

### Requirement 10: Self-Service Telegram Configuration

**User Story:** As a Tenant_User, I want to set my Telegram chat identifier from my dashboard, so that I control where my alerts are delivered.

#### Acceptance Criteria

1. WHEN an authenticated Tenant_User submits a non-empty Telegram_Chat_Id value that is 1 to 32 characters long and matches the valid format (a numeric identifier optionally prefixed with a single minus sign), THE API SHALL store that value on the requesting Tenant_User's record and return a success response confirming the stored value.
2. WHEN an authenticated Tenant_User requests dashboard settings, THE API SHALL return the requesting Tenant_User's current Telegram_Chat_Id and active Plan limits.
3. WHEN an authenticated Tenant_User submits an empty Telegram_Chat_Id value, THE API SHALL clear the stored Telegram_Chat_Id on the requesting Tenant_User's record and return a success response indicating the value is now empty.
4. IF a submitted Telegram_Chat_Id value is non-empty and either exceeds 32 characters or does not match the valid format, THEN THE API SHALL reject the request, return an error response indicating the value format is invalid, and preserve the previously stored Telegram_Chat_Id unchanged.
5. IF a request to set or read the Telegram_Chat_Id is not authenticated, THEN THE API SHALL reject the request with an authentication error response and SHALL NOT read or modify any Tenant_User's stored Telegram_Chat_Id.

### Requirement 11: Registration with Turnstile Verification

**User Story:** As a Platform operator, I want registration protected by a bot challenge, so that automated signups are prevented.

#### Acceptance Criteria

1. WHEN a registration request is received with a username, email, password, and Turnstile_Token, THE API SHALL verify the Turnstile_Token with the Turnstile verification service within 10 seconds before creating the Tenant_User.
2. IF the Turnstile_Token verification fails, THEN THE API SHALL reject the registration with HTTP status 400, return an error indication, and SHALL NOT create the Tenant_User.
3. IF a registration request omits the Turnstile_Token or supplies an empty Turnstile_Token, THEN THE API SHALL reject the registration with HTTP status 400, return an error indication, and SHALL NOT create the Tenant_User.
4. IF the Turnstile verification service is unreachable or does not respond within 10 seconds, THEN THE API SHALL respond with HTTP status 503, return an error indication, and SHALL NOT create the Tenant_User.
5. WHEN a registration request passes Turnstile_Token verification and the username and email are not already in use, THE API SHALL create the Tenant_User on the Free Plan and SHALL store the password as a hashed value.
6. IF a registration request passes Turnstile_Token verification but the username or email is already in use, THEN THE API SHALL reject the registration with HTTP status 409, return an error indication, and SHALL leave all existing Tenant_User records unchanged.

### Requirement 12: Login with Turnstile Verification

**User Story:** As a Platform operator, I want login protected by a bot challenge, so that credential-stuffing attacks are deterred.

#### Acceptance Criteria

1. WHEN a login request is received with credentials and a Turnstile_Token, THE API SHALL verify the Turnstile_Token with the Turnstile verification service within 10 seconds before validating the credentials.
2. IF a login request omits the Turnstile_Token or supplies an empty Turnstile_Token, THEN THE API SHALL reject the login with HTTP status 400, SHALL NOT validate the credentials, and SHALL NOT issue an Auth_Token.
3. IF the Turnstile_Token verification fails, THEN THE API SHALL reject the login with HTTP status 400 and SHALL NOT issue an Auth_Token.
4. IF the Turnstile verification service is unreachable or does not respond within 10 seconds, THEN THE API SHALL respond with HTTP status 503, return an error indication, and SHALL NOT issue an Auth_Token.
5. WHEN a login request passes Turnstile_Token verification and the submitted credentials match a stored Tenant_User, THE API SHALL issue an Auth_Token that identifies the Tenant_User for use in tenant isolation.
6. IF a login request passes Turnstile_Token verification but the submitted credentials do not match any stored Tenant_User, THEN THE API SHALL reject the login with HTTP status 401 and SHALL NOT issue an Auth_Token.

### Requirement 13: SePay Payment Initiation

**User Story:** As a Tenant_User, I want to generate a payment QR code for a plan, so that I can pay to upgrade my subscription.

#### Acceptance Criteria

1. WHEN an authenticated Tenant_User requests payment initiation for a selected paid Plan with a price greater than 0, THE API SHALL create a Transaction in a pending state recording the Tenant_User identifier, the selected Plan identifier, the Plan price, a unique payment reference code, and the creation timestamp.
2. WHEN the API creates a pending Transaction for payment initiation, THE API SHALL return, within 3 seconds, a SePay payment QR code reference that encodes the Plan price and the unique payment reference code created in criterion 1.
3. IF an authenticated Tenant_User requests payment initiation for a Plan that does not exist, THEN THE API SHALL respond with HTTP status 404 and an error indication that the Plan was not found, and SHALL NOT create a Transaction.
4. IF an authenticated Tenant_User requests payment initiation for a Plan with price 0, THEN THE API SHALL respond with HTTP status 400 and an error indication that the Plan is not payable, and SHALL NOT create a Transaction.
5. IF an authenticated Tenant_User requests payment initiation for a Plan for which a pending Transaction already exists for that Tenant_User, THEN THE API SHALL return the existing pending Transaction and its payment reference code and SHALL NOT create an additional Transaction.

### Requirement 14: SePay Webhook and Plan Upgrade

**User Story:** As a Tenant_User, I want my plan upgraded automatically after payment, so that I gain access to paid features without manual steps.

#### Acceptance Criteria

1. WHEN the SePay_Webhook receives a payment confirmation, THE API SHALL verify the Webhook_Signature before processing the confirmation.
2. IF the Webhook_Signature verification fails, THEN THE API SHALL reject the request with HTTP status 401 and SHALL NOT modify any Transaction or Tenant_User.
3. WHEN the SePay_Webhook receives a payment confirmation with a valid Webhook_Signature that matches a pending Transaction AND the paid amount equals that Transaction's amount, THE API SHALL set that Transaction's status to completed.
4. WHEN a Transaction's status is set to completed, THE API SHALL set the associated Tenant_User's plan_id to the Transaction's Plan and SHALL set Plan_Expires_At to the completion timestamp plus the duration defined by the Transaction's Plan.
5. WHEN the SePay_Webhook receives a payment confirmation with a valid Webhook_Signature for a Transaction that is already completed, THE API SHALL leave the Transaction status and the Tenant_User Plan unchanged.
6. IF the SePay_Webhook receives a payment confirmation with a valid Webhook_Signature that matches no known Transaction, THEN THE API SHALL respond with HTTP status 404 and SHALL NOT modify any Tenant_User.
7. IF the SePay_Webhook receives a payment confirmation with a valid Webhook_Signature that matches a pending Transaction but the paid amount does not equal that Transaction's amount, THEN THE API SHALL reject the request with HTTP status 400, SHALL leave the Transaction status unchanged, and SHALL NOT modify any Tenant_User.

### Requirement 15: Transaction Record Persistence

**User Story:** As an Admin_User, I want payment history stored, so that I can audit subscription revenue and resolve disputes.

#### Acceptance Criteria

1. THE Platform SHALL persist each Transaction with the attributes id, user_id, plan_id, amount, status, created_at, and updated_at, setting created_at to the Transaction creation time and updated_at to the time of the most recent modification.
2. THE Platform SHALL record each Transaction amount as a decimal value between 0.01 and 999,999,999.99 inclusive.
3. THE Platform SHALL record each Transaction status as one of pending, completed, or failed.
4. WHEN a SePay payment confirmation references payment metadata that matches an existing Transaction, THE Platform SHALL store the SePay payment reference code on the matching Transaction.
5. THE Platform SHALL ensure each stored SePay payment reference code is unique across all Transactions.
6. IF a SePay payment confirmation references payment metadata that matches no existing Transaction, THEN THE Platform SHALL reject the confirmation without creating or modifying any Transaction and record an error indicating that no matching Transaction was found.

### Requirement 16: Plan Expiry Handling

**User Story:** As a Platform operator, I want expired paid plans to revert to the free tier, so that entitlements match active payments.

#### Acceptance Criteria

1. WHILE a Tenant_User's Plan_Expires_At holds a value that is earlier than or exactly equal to the current UTC time, THE Platform SHALL treat the Tenant_User's active Plan as the Free Plan for all limit and feature decisions.
2. WHILE a Tenant_User's Plan_Expires_At holds a value that is later than the current UTC time, THE Platform SHALL treat the Tenant_User's active Plan as the Plan referenced by the Tenant_User's plan_id for all limit and feature decisions.
3. WHILE a Tenant_User's Plan_Expires_At is empty, THE Platform SHALL treat the Tenant_User's active Plan as the Free Plan for all limit and feature decisions and SHALL NOT apply any expiry evaluation to that Tenant_User.
4. IF a Tenant_User's Plan_Expires_At is later than the current UTC time but the Tenant_User's plan_id does not reference an existing Plan, THEN THE Platform SHALL treat the Tenant_User's active Plan as the Free Plan for all limit and feature decisions and SHALL record an indication that the referenced Plan could not be resolved.
5. WHEN the Platform evaluates a Tenant_User's active Plan for a limit or feature decision, THE Platform SHALL complete the active-Plan determination within 200 milliseconds.

### Requirement 17: Administrative Plan Management

**User Story:** As an Admin_User, I want to manage subscription plans, so that I can adjust pricing, features, and limits over time.

#### Acceptance Criteria

1. WHEN an Admin_User requests creation of a Plan with name (1 to 100 characters), price (0.00 to 999,999.99), Max_Monitors (1 to 100,000), SSL_Check_Enabled (true or false), and Min_Interval_Minutes (1 to 1440), THE API SHALL create the Plan, assign it a unique identifier, and return the created Plan with HTTP status 201 within 2 seconds.
2. IF an Admin_User requests creation or update of a Plan with any field missing, outside its specified bounds, of the wrong type, or with a name that duplicates an existing Plan, THEN THE API SHALL respond with HTTP status 400, SHALL include an error indication identifying the invalid field, and SHALL NOT create or modify any Plan.
3. WHEN an Admin_User requests an update to an existing Plan, THE API SHALL apply the requested changes to the Plan, retain the associations of all existing subscribers to that Plan, apply the updated limits to those subscribers going forward, and return the updated Plan with HTTP status 200 within 2 seconds.
4. WHEN an Admin_User requests the list of Plans, THE API SHALL return all Plans as a collection with HTTP status 200, returning an empty collection if no Plans exist.
5. WHEN an Admin_User requests deletion of a Plan that has no active subscribers, THE API SHALL delete the Plan and respond with HTTP status 200.
6. IF an Admin_User requests deletion of a Plan that has one or more active subscribers, THEN THE API SHALL respond with HTTP status 409, SHALL include an error indication that the Plan has active subscribers, and SHALL retain the Plan unchanged.
7. IF a Tenant_User who is not an Admin_User requests any administrative Plan management endpoint, THEN THE API SHALL respond with HTTP status 403 and SHALL NOT include any Plan management data in the response body.

### Requirement 18: Administrative User and Transaction Visibility

**User Story:** As an Admin_User, I want to view registered users and payment logs, so that I can administer the Platform.

#### Acceptance Criteria

1. WHEN an Admin_User requests the list of registered users, THE API SHALL return each Tenant_User with exactly the username, email, and active Plan name, within 2 seconds for up to 100 records.
2. THE API SHALL NOT expose any Tenant_User credential fields, including hashed passwords and password reset tokens, in any user listing response.
3. WHEN an Admin_User requests the list of Transactions, THE API SHALL return each Transaction with exactly the user, plan, amount, and status, within 2 seconds.
4. WHEN an Admin_User requests a user or Transaction listing that yields no records, THE API SHALL respond with HTTP status 200 and an empty list.
5. THE API SHALL return at most 100 records per user or Transaction listing response.
6. IF a Tenant_User who is not an Admin_User requests an administrative user or Transaction listing endpoint, THEN THE API SHALL respond with HTTP status 403 and SHALL NOT include any user or Transaction data in the response body.
7. IF an unauthenticated request is made to an administrative user or Transaction listing endpoint, THEN THE API SHALL respond with HTTP status 401 and SHALL NOT include any user or Transaction data in the response body.

### Requirement 19: Landing Page

**User Story:** As a prospective customer, I want a marketing page with pricing, so that I can understand the offering and sign up.

#### Acceptance Criteria

1. WHEN a visitor navigates to the Landing_Page route, THE Platform SHALL display a pricing table containing one row or card per active Plan stored in the database, where each entry shows the Plan name, price amount, billing period, and the list of included features.
2. WHEN a visitor navigates to the Landing_Page route, THE Platform SHALL render the pricing table fully within 3 seconds under normal load.
3. IF no active Plans exist in the database, THEN THE Platform SHALL display the Landing_Page with a placeholder pricing section that contains a text message indicating that pricing is not currently available and omits the pricing table.
4. IF the Plans data cannot be retrieved from the database, THEN THE Platform SHALL display the Landing_Page with the placeholder pricing section and an error indication that pricing could not be loaded, while keeping all other Landing_Page content visible.
5. THE Landing_Page SHALL present a single primary call-to-action control that is visible without scrolling on a viewport width of at least 1024 pixels.
6. WHEN a visitor activates the primary call-to-action control, THE Platform SHALL navigate to the registration page.

### Requirement 20: Authentication Pages with Turnstile Widget

**User Story:** As a Tenant_User, I want login and registration forms with the bot challenge, so that I can authenticate securely.

#### Acceptance Criteria

1. WHEN a visitor opens the registration page, THE Platform SHALL display a username field, an email field, a password field, and the Turnstile widget, each field initially empty.
2. WHEN a visitor opens the login page, THE Platform SHALL display an identifier field, a password field, and the Turnstile widget, each field initially empty.
3. WHEN a visitor submits an authentication form and a Turnstile_Token is present, THE Platform SHALL include that Turnstile_Token in the request sent to the API.
4. IF a visitor attempts to submit an authentication form while the Turnstile widget has not produced a Turnstile_Token, THEN THE Platform SHALL block the request from being sent to the API and SHALL display an indication that the bot challenge must be completed.
5. IF a visitor attempts to submit an authentication form while any required field is empty, THEN THE Platform SHALL block the request from being sent to the API and SHALL display an indication identifying each empty required field, while preserving all entered field values except the password.
6. WHEN the API returns an error response to an authentication request (including invalid credentials and duplicate user), THE Platform SHALL display an error message reflecting the returned error, SHALL retain the visitor on the same authentication page, and SHALL reset the Turnstile widget so that a new Turnstile_Token is required before the next submission.

### Requirement 21: User Dashboard Plan and Upgrade Section

**User Story:** As a Tenant_User, I want my dashboard to show my plan limits and an upgrade option, so that I can manage my subscription.

#### Acceptance Criteria

1. WHEN an authenticated Tenant_User opens the dashboard settings, THE Platform SHALL display the Tenant_User's current Plan name, Max_Monitors, Min_Interval_Minutes, and SSL_Check_Enabled within 3 seconds of the settings view loading.
2. WHEN an authenticated Tenant_User opens the dashboard settings, THE Platform SHALL display the Tenant_User's current monitor usage as a count of active monitors relative to Max_Monitors (formatted as "used of total").
3. WHILE the authenticated Tenant_User's current Plan is a paid Plan, THE Platform SHALL display the Plan expiry date in the dashboard settings.
4. WHEN an authenticated Tenant_User opens the dashboard settings, THE Platform SHALL display a Telegram_Chat_Id configuration field populated with the stored value, displaying an empty field when no value is stored.
5. WHEN an authenticated Tenant_User selects a paid Plan upgrade, THE Platform SHALL display the SePay payment QR code returned by the API within 5 seconds of the selection.
6. IF the SePay payment QR code request fails or returns no QR code within 5 seconds, THEN THE Platform SHALL retain the current Plan unchanged and display an error indication that the payment QR code could not be retrieved, with the option to retry.

### Requirement 22: Administrative Console

**User Story:** As an Admin_User, I want an administrative console, so that I can manage plans, users, and payments through a graphical interface.

#### Acceptance Criteria

1. WHEN an authenticated Admin_User navigates to the Admin_Console route, THE Platform SHALL display Plan management controls that include a control for creating a new Plan and a control for updating an existing Plan within 2 seconds.
2. WHEN an authenticated Admin_User navigates to the Admin_Console route, THE Platform SHALL display the list of registered users, each row showing the user's identifier and the name of that user's currently active Plan, within 2 seconds.
3. WHILE the registered user list contains zero users, THE Platform SHALL display an empty-state indication in place of the user list rather than an empty or blank region.
4. WHEN an authenticated Admin_User navigates to the Admin_Console route, THE Platform SHALL display the list of Transactions within 2 seconds, and WHILE the Transaction list contains zero Transactions THE Platform SHALL display an empty-state indication in place of the list.
5. IF an authenticated Tenant_User who is not an Admin_User navigates to the Admin_Console route, THEN THE Platform SHALL withhold rendering of all administrative controls (Plan management, user list, and Transaction list) and SHALL display an access-denied indication informing the user that the route requires Admin_User privileges.
6. IF an unauthenticated visitor navigates to the Admin_Console route, THEN THE Platform SHALL redirect the visitor to the login route without rendering any administrative controls.

### Requirement 23: Data Migration from Single-User Setup

**User Story:** As a Platform operator, I want existing data migrated, so that the prior single-user deployment continues working after the upgrade.

#### Acceptance Criteria

1. WHEN the Platform migrates an existing single-user database, THE Platform SHALL assign every existing Monitor to the migrated existing Tenant_User without modifying any Monitor's configuration data, including the case where zero existing Monitors are present.
2. WHEN the Platform migrates an existing single-user database, THE Platform SHALL set the migrated existing Tenant_User's is_admin flag to true.
3. WHEN the Platform migrates an existing single-user database, IF the global Telegram chat identifier is present and non-empty, THEN THE Platform SHALL copy it to the migrated existing Tenant_User's Telegram_Chat_Id.
4. WHEN the Platform migrates an existing single-user database, IF the global Telegram chat identifier is absent or empty, THEN THE Platform SHALL leave the migrated existing Tenant_User's Telegram_Chat_Id unset.
5. WHEN the Platform migrates an existing single-user database, THE Platform SHALL assign exactly one default Plan to the migrated existing Tenant_User.
6. IF any step of the migration fails, THEN THE Platform SHALL roll back the entire migration, SHALL leave all existing data unchanged, and SHALL report an error indicating that the migration failed.
7. IF the Platform initiates migration on a database that has already been migrated, THEN THE Platform SHALL make no further changes to existing data and SHALL report that the database is already migrated.

### Requirement 24: Backward-Compatible Monitoring Behavior

**User Story:** As a Tenant_User with migrated monitors, I want monitoring to behave as before, so that the upgrade does not disrupt my existing checks.

#### Acceptance Criteria

1. WHEN the Scheduler polls a migrated Monitor, THE Scheduler SHALL classify the Monitor as up when the HTTP response status code is in the range 200 through 299 and as down otherwise, applying a request timeout of 10 seconds.
2. IF a check against a migrated Monitor fails due to a connection failure or the request exceeding the 10-second timeout, THEN THE Scheduler SHALL classify the Monitor as down, record no status code, and record an error description.
3. WHEN a migrated Monitor transitions from up to down and its owning Tenant_User has a configured Telegram_Chat_Id, THE Alerter SHALL dispatch a down alert, where the alert cooldown equals the Monitor's configured interval in minutes measured since the last down alert, or is not in effect when no prior down alert exists.
4. IF a migrated Monitor transitions from up to down and the cooldown has not elapsed since the last down alert, THEN THE Alerter SHALL suppress the down alert.
5. IF a migrated Monitor transitions from up to down and its owning Tenant_User has no configured Telegram_Chat_Id, THEN THE Alerter SHALL NOT dispatch a down alert and SHALL leave Check_Result persistence unaffected.
6. WHEN the Scheduler persists a Check_Result for a migrated Monitor, THE Platform SHALL store the check timestamp, the HTTP status code or empty when none, the response time in milliseconds, the up or down classification, the SSL validity, the SSL days remaining, and the error description.

## Correctness Properties for Property-Based Testing

The following properties are candidates for Hypothesis-based property tests. They are expressed independently of implementation so they can guide test design during the design phase.

- **Tenant isolation invariant**: For any set of Tenant_Users and Monitors, a list-monitors request by a Tenant_User returns exactly the Monitors whose user_id equals that Tenant_User's id, and never another tenant's Monitor (Requirement 4).
- **Monitor count limit invariant**: For any Plan and any sequence of create-monitor requests by a Tenant_User, the number of Monitors owned by that Tenant_User never exceeds the Plan's Max_Monitors (Requirement 5).
- **Interval limit invariant**: For any created or updated Monitor, the stored check interval is greater than or equal to the owning Tenant_User's active Plan Min_Interval_Minutes (Requirement 6).
- **SSL gating invariant**: For any Check_Result produced for a Monitor whose owner's active Plan has SSL_Check_Enabled false, the SSL fields are empty (Requirement 7).
- **Scheduler interval bound**: For any registered Monitor, the effective polling interval is greater than or equal to the owning Tenant_User's active Plan Min_Interval_Minutes (Requirement 8).
- **Alert routing**: For any dispatched alert, the destination Telegram_Chat_Id equals the owning Tenant_User's Telegram_Chat_Id (Requirement 9).
- **Webhook idempotence**: For any payment confirmation applied to an already-completed Transaction, applying the confirmation again leaves the Transaction status and the Tenant_User Plan unchanged (Requirement 14).
- **Signature rejection (error condition)**: For any webhook request with an invalid Webhook_Signature, no Transaction and no Tenant_User is modified (Requirement 14).
- **Plan upgrade consistency**: For any completed Transaction, the associated Tenant_User's plan_id equals the Transaction's plan_id and Plan_Expires_At is in the future (Requirement 14).
- **Webhook amount-match (error condition)**: For any payment confirmation with a valid Webhook_Signature matching a pending Transaction, the Transaction is set to completed only when the paid amount equals the Transaction's amount; when the amount differs, the Transaction status and the Tenant_User Plan remain unchanged (Requirement 14).
- **SePay reference uniqueness invariant**: For any set of Transactions, every stored SePay payment reference code is unique across all Transactions (Requirement 15).
- **Payment initiation single-pending invariant**: For any sequence of payment-initiation requests by a Tenant_User for the same Plan, at most one pending Transaction exists for that Tenant_User and Plan, and a repeated request returns the existing pending Transaction without creating another (Requirements 13, 15).
- **Plan deletion subscriber protection (error condition)**: For any Plan that has one or more active subscribers, a deletion request leaves the Plan and all subscriber associations unchanged (Requirement 17).
- **Admin listing credential secrecy**: For any administrative user listing response, no Tenant_User credential field (hashed password or password reset token) appears in the response (Requirement 18).
- **Monitor deletion cascade atomicity**: For any Tenant_User deletion, either all Monitors owned by that Tenant_User and their Check_Results are deleted or none are, and no other Tenant_User's Monitors are affected (Requirement 3).
- **Plan expiry resolution**: For any Tenant_User, the resolved active Plan is the Free Plan when Plan_Expires_At is in the past and the referenced Plan when Plan_Expires_At is in the future (Requirement 16).
- **Registration password secrecy**: For any successful registration, the stored password value differs from the submitted plaintext password and verifies against it (Requirement 11).
