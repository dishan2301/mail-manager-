# OEIS — Office Email Intelligence System

Production-oriented single-tenant, multi-mailbox Microsoft 365 and Gmail SLA monitoring. The authoritative requirements are in `project.docx`.

## Stack

- FastAPI/Python 3.12, SQLAlchemy, Alembic, SQL Server
- Microsoft Graph delta queries using MSAL app-only authentication
- Redis and APScheduler (5-minute mailbox sync; 18:00 daily summary by default)
- React, TypeScript, Material UI, Chart.js
- Docker Compose for local and production-like deployment

## Local start

1. Copy `.env.example` to `.env`, set a strong `MSSQL_SA_PASSWORD`, database URL, JWT secret, and Azure values.
2. Register the Azure app and apply the mailbox restriction described below.
3. Run `docker compose up --build`.
4. Apply migrations: `docker compose exec backend alembic upgrade head`.
5. Open the production dashboard at `http://localhost:8080/` and Swagger at `http://localhost:8000/api/docs`.

The bootstrap Admin is created from `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`. Replace the example password before first start. Use the Admin API to create Manager users; never retain the development default in a deployed environment.

## Azure and Exchange setup

Create an Entra app registration, add Microsoft Graph **application** permissions `Mail.Read` and `Mail.Send`, and grant admin consent. The Exchange mailbox restriction below must cover both permissions. Delegated mailbox login requests `Mail.Read`, `Mail.Send`, and `User.Read`; existing connected accounts must sign in again to grant the send permission. Prefer a PEM certificate by setting `AZURE_CLIENT_CERTIFICATE_PATH` and `AZURE_CLIENT_CERTIFICATE_THUMBPRINT`; otherwise inject `AZURE_CLIENT_SECRET` from a secret manager. To rotate without downtime, deploy the new certificate/secret to one instance, verify token acquisition, roll it across remaining instances, and only then retire the previous credential.

Admins can use the in-app setup guidance from **Mailboxes → Add mailbox**. Provider credentials are deployment-only secrets: the API and UI do not accept or write client secrets. Configure them through the deployment secret store, restart the API, run the connection check, then start OAuth for the exact mailbox.

Tenant admin consent and the Exchange mailbox restriction are mandatory and cannot be bypassed by OEIS.

## Gmail setup

Admins can choose **Google Gmail** in **Mailboxes → Add mailbox**. Create a **Web application** OAuth client, add the exact `GOOGLE_REDIRECT_URI`, and configure Gmail read-only, Gmail send, and user-email scopes. Set `GMAIL_SCOPES` to `https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email` and inject the Client ID/secret through the deployment secret store. Existing connected accounts must sign in again to grant the send permission. Add the mailbox, select **Connect Gmail**, sign in with that exact account, and then run **Sync now**.

While the Google OAuth app is in testing, add each monitored Gmail account as a test user. Production deployments should publish or internally approve the consent app as appropriate and keep `GOOGLE_CLIENT_SECRET` in the deployment secret store.

## In-app reply assistant

Admins can open an incoming message, draft or edit a reply in the detail drawer, request an AI draft/grammar correction/rewrite, review the result, and explicitly send it from that same mailbox. AI assistance uses an OpenAI-compatible Chat Completions endpoint; configure `AI_API_KEY`, with optional `AI_API_BASE_URL` (default `https://api.openai.com/v1`) and `AI_MODEL` (default `gpt-4o`; use `openai/gpt-4o` through OpenRouter). Customer email content and the administrator's draft are sent to that configured AI service only when an AI action is used. Without an AI key, manual replies remain available. AI output is never sent automatically.

An app-only token is tenant-wide unless Exchange restricts it. In Exchange Online PowerShell:

```powershell
Connect-ExchangeOnline
New-DistributionGroup -Name "OEIS Allowed Mailboxes" -Type Security
Add-DistributionGroupMember -Identity "OEIS Allowed Mailboxes" -Member support@company.com
New-ApplicationAccessPolicy -AppId <AZURE_CLIENT_ID> -PolicyScopeGroupId "OEIS Allowed Mailboxes" -AccessRight RestrictAccess -Description "Restrict OEIS Graph access"
Test-ApplicationAccessPolicy -Identity support@company.com -AppId <AZURE_CLIENT_ID>
Test-ApplicationAccessPolicy -Identity unauthorized@company.com -AppId <AZURE_CLIENT_ID>
```

Verify the allowed mailbox returns `Granted` and an out-of-scope mailbox returns `Denied` before starting sync.

## Verification

```powershell
cd backend
python -m pip install --require-hashes -r requirements.lock
python -m pytest -q
pip-audit --disable-pip --no-deps -r requirements.lock
bandit -q -r app -x tests -lll
cd ../frontend
npm ci
npm audit --audit-level=high
npm run build
```

The highest-risk unit tests cover default-to-Customer classification, automatic-reply precedence, authoritative header reply matching, bounded fallback matching, business-calendar SLA calculation, and tier thresholds.

The production UI provides repository-backed KPIs, server-filtered pending email, employee performance, and department, employee, sender, and mailbox reports. Daily reports start at local midnight, weekly reports cover the last seven days, and monthly reports start on the first of the calendar month in `APP_TIMEZONE`. Employee reports can filter by department and employee, show sender counts, and export the selected scope as CSV/Excel/PDF. Reply rate is replied / (replied + pending); ignored mail is excluded. This is completion percentage, not a factual accuracy score.

An admin must explicitly enable scheduled AI coaching reviews. The background worker starts immediately with the scheduler and checks for changed conversations every 30 seconds throughout the day. Each conversation and employee is reviewed separately, and unchanged completed reviews are skipped. Provider failures wait five minutes before retrying unless a new message arrives. Changes received during analysis remain queued for the next pass. Monthly views load saved findings and show ready, waiting, and failed coverage. Long conversations are processed in sections of up to 40,000 characters or 200 messages, carrying prior findings into the next section. Every section must succeed before a conversation is marked ready. Separate findings are kept for employees sharing a thread. In-app replies wait for sent-mail synchronization before analysis. Reviews cover tone, professionalism, completeness, understandable explanations, and actionable next steps. Factual checks use conversation evidence; unsupported claims are marked unverified because no company policy reference is configured. Successful in-app AI requests record whether draft text was supplied and its word count, without storing that draft. These events do not prove that a suggestion was sent, that the actor was the assigned employee, or that external AI was used. OEIS stores findings and status, not message bodies, and instructs the model not to judge character or recommend salary decisions. `run-go.sh` applies migrations and enables the scheduler by default; set `SCHEDULER_ENABLED=false` to disable it. The UI also includes Microsoft 365 and Gmail mailbox administration, audit logs, configurable SLA/classification/business-calendar views, manual synchronization, and daily-summary testing.

## Production and rollback

Use HTTPS at Nginx/IIS/load balancer, managed SQL Server and Redis, a secret store, encrypted backups, centralized logs, signed digest-pinned container images, and MFA at the production identity layer. Set `SCHEDULER_ENABLED=true` on exactly one deployment and false on API replicas. Run migrations as a release job before traffic shifts. See `SECURITY_REMEDIATION_STATUS.md`; its manual gates are mandatory before release.
# mail-mannager
