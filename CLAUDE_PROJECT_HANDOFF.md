# OEIS handoff for Claude

This document describes the Office Email Intelligence System (OEIS) as implemented in this repository on 26 October 2026. Read it before suggesting changes. Use the linked source files to verify any detail that matters to an idea. This is a single-tenant product for Indian Infotech; some older repository documents describe earlier behavior and may be stale. This file contains no credentials or customer email content.

## What the product does

OEIS connects monitored Microsoft 365/Outlook and Gmail mailboxes, saves message metadata, identifies customer messages that need a reply, tracks who actually replies, calculates business-hours SLA, and presents dashboard, employee, and exportable reports. Admins can send manual replies and request AI writing help. An optional AI worker produces evidence-based coaching reviews of conversations.

The main deployment used by the owner is a single Docker container named `oeis-docker-test`, exposed at `http://192.168.1.36:10002/`. The repository also contains a separate Docker Compose setup. A source change does **not** reach the running container until it is rebuilt. `rebuild_docker_dashboard.sh` builds the single image, starts a replacement using the persistent volume, checks health, and keeps the previous container as a rollback. Do not treat a Docker Compose service on port 8080 as this port-10002 deployment.

## People, mailboxes, and permissions

- A **mailbox** is a connected account from which OEIS reads messages. The CEO's mailbox is used as a monitoring source because the CEO is often copied on company mail. An employee's own mailbox does not have to be connected for that employee's received work to appear when the message is visible in the CEO's mailbox.
- An **employee** is a person whose email address ends exactly in `@indianinfotech.org`, case-insensitively. The `Employee List` page sits above `Employee Performance` and shows active company employees with name, email, Edit, and Remove controls. Remove deactivates a record so its mail history is retained. A migration deactivates previously discovered addresses outside the company domain.
- During sync, incoming messages' **To** addresses can create missing company employee records. Existing addresses are reused. An address found only in **From** does not create an employee. CC recipients are observers: being in CC does not create a pending reply obligation. The CEO monitoring mailbox is not automatically the assignee merely because that mailbox received a CC copy.
- Admins manage mailboxes, employees, settings, and sending. Managers have scoped, read-oriented access to permitted mailboxes. See `backend/app/services/authorization.py` and the route dependencies in `backend/app/api/routes.py`.

## How email tracking works

1. The sync worker fetches deltas from each active mailbox. Microsoft Graph and Gmail adapters normalize provider messages into the fields used by `backend/app/services/sync.py`. A message can exist as a separate physical copy in several connected mailboxes.
2. The system stores IDs, sender, the To addresses, subject, timestamps, folder, selected headers, classification, reply status, assignee, and SLA values. Full message bodies are fetched on demand for detail views and AI reviews; they are not the main saved email record.
3. Classification rules can mark a message as Customer, Ignore, Auto Reply, Newsletter, Marketing, Spam, and other categories. Unmatched messages default to Customer. Customer messages delivered to an Inbox can become pending; other classifications and observer copies are generally represented with the existing `ignored` status. Consequently, an `ignored` row is not necessarily an unimportant email.
4. A customer message addressed to one or more company employees creates a response obligation for **every company employee in To**. CC employees receive none. The same physical message copied into multiple monitored mailboxes is represented once for reply tracking; the other copies remain saved.
5. A linked employee reply closes the pending obligation for all To recipients. The actual responder receives the reply credit. Other To recipients keep a received-mail record with a `replied_by_other` outcome. An employee who replied while in CC can earn credit without having been an original To recipient.
6. Reply matching first uses the original Internet Message ID against `In-Reply-To`/`References`. A fallback uses the provider conversation ID, normalized subject, time order, and a bounded 30-day window. Conversation IDs may be mailbox-specific; cross-mailbox matches rely on reply headers. OEIS has to see the reply in a connected mailbox to attribute it.
7. The response clock uses the applicable business calendar, timezone, workdays, holidays, and SLA rules. The main statuses are `pending`, `replied`, and `ignored`. The default SLA thresholds are 4 hours warning, 8 overdue, and 24 critical, subject to configured rules.

Example: P sends a meeting request to A and B, with the CEO, X, and Y in CC. A and B each see one received/pending obligation. The CEO, X, and Y do not. A replies: both pending obligations clear; A gets one reply credit; B's report says the message was received and replied to by A. P sends another question in the same conversation: that **new customer message** creates a new obligation. If A replies again, there are two received customer messages and two completed response rounds for A, even though the discussion is one conversation.

The message-level reply state and the conversation-level AI review are distinct. Do not rename two received customer messages as two separate conversations. The current status model is per incoming message, not a richer open/closed case lifecycle.

## What the user sees

- **Dashboard:** today’s incoming count, pending, overdue, critical, average reply time, resolved today, ignored, growth and sender insights, and readiness/sync information.
- **Pending Emails:** a searchable and filterable table or board with status, SLA priority, sender, To, assignee, and time. Admins can inspect content, mark read, change assignment/status, request AI writing assistance, and send a reply from the connected mailbox.
- **Employee List:** active `@indianinfotech.org` records with names and addresses. Admins can add, edit, or deactivate employees.
- **Employee Performance:** received, pending, reply credit, reply time, SLA buckets, and `replied_by_other`. A resolved shared-To email can count as received for multiple people while crediting one responder.
- **Reports:** daily, weekly, and monthly views by employee, department, customer/sender, or mailbox. Employee mail-wise reports identify `Replied by you` versus `Not replied by you · Replied by <name>`. CSV, XLSX, and PDF export use the same report rows. Daily summary mail and escalation alerts are available when a delivery provider is configured.
- **Mailboxes, Users & Roles, Settings, AI Settings, Audit Logs:** connection and permission administration, sync and business settings, provider choice, and event visibility.

The overall reply rate counts **messages** with replied/pending status. An employee's credited reply rate excludes a shared-To message answered by someone else from that employee's reply numerator, while retaining it in their received history. Some dashboard aggregates and individual mailbox copies have different denominators; inspect the exact repository/API query before proposing a metric change.

## Continuing conversations and AI review

The mail providers supply a conversation or thread ID. OEIS also retains Internet Message IDs and reply headers. AI review groups current customer messages by `(mailbox, conversation key, assigned employee)`, then reads visible messages in that thread. It analyzes the discussion as one conversation, even if there are multiple customer messages and reply rounds. It recognizes an employee-authored message visible in the CEO's Inbox as an employee reply when its sender matches that employee's address.

AI reviews are opt-in and run in the background when enabled, a provider key is configured, and the scheduler is active. They store status (`pending`, `ready`, `failed`), analysis, a per-factor rubric, and an error code. The AI writing assistant can draft, correct, or rewrite an admin's text; a human reviews and sends it explicitly. Long conversations are processed in sections. Missing message bodies and missing attributable employee reply text must be reported as insufficient evidence rather than guessed at.

The coaching score has reply completion and speed factors plus professionalism, answer detail, clarity, ownership, and actionable-next-step factors. A full score is shown only when all required weighted factors have evidence. A conversation can be `ready` yet lack a full score because no employee reply is visible, the body was unavailable, or the rubric could not assess a factor. The score is a coaching indicator, not a factual accuracy or compensation measure. Recorded in-app AI assistance shows that an AI action was requested; it does not prove the suggested text was sent.

At the last live inspection on 26 October 2026, the chosen `gemini-2.5-flash-lite` model returned HTTP 404 for the configured API key; the provider recommended `gemini-3.5-flash-lite`. The owner must choose and save an available model in **AI Settings** for provider failures to clear. Treat this as a dated observation, not a permanent assertion about model availability. Never include provider keys, OAuth tokens, or customer message bodies in an idea document or test output.

## Technical map

| Area | Primary files |
| --- | --- |
| Frontend and navigation | `frontend/src/ProductionApp.tsx` |
| API, authentication gates, and reports | `backend/app/api/routes.py`, `backend/app/services/authorization.py` |
| Persistent entities | `backend/app/models/entities.py`, `backend/migrations/versions/` |
| Mailbox sync and recipient assignment | `backend/app/services/sync.py`, `backend/app/services/employees.py` |
| Microsoft and Gmail adapters | `backend/app/services/graph.py`, `backend/app/services/gmail.py` |
| Reply matching, classification, SLA | `backend/app/services/reply_detection.py`, `classification.py`, `sla.py` in the same directory |
| Performance and dashboard queries | `backend/app/repositories/email.py`, `backend/app/repositories/dashboard.py` |
| AI review and scoring | `backend/app/services/conversation_reviews.py`, `review_rubric.py`, `ai_provider.py`, `writing_assistant.py` |
| Jobs and startup | `backend/app/services/jobs.py`, `scheduler.py`, `backend/app/main.py` |
| Container deployment | `Dockerfile`, `docker/entrypoint.sh`, `rebuild_docker_dashboard.sh`, `docker-compose.yml` |

Backend: Python/FastAPI, SQLAlchemy, Alembic; the single-container build uses SQLite in a persistent Docker volume. The separate Compose design uses SQL Server and Redis. Frontend: React, TypeScript, Material UI, and Chart.js. The single image builds and serves the frontend through the backend. Scheduler jobs cover mailbox sync, daily summary, and AI review. OAuth credentials and AI keys are stored or supplied through the application's configured secret mechanisms; do not copy them into this document.

Key data relationships: `Mailbox` owns fetched `Email` rows; `Employee` represents a company address; `EmailRecipient` records every To employee for a tracked message; `Email.assigned_employee_id` is used for the current owner or credited responder; `ConversationAIReview` stores one employee's saved review of a mailbox conversation. The current schema does not contain a dedicated conversation/case table or a separate persisted response-round entity.

## Known limits to consider in product ideas

- Message counts and conversation counts answer different questions. A dashboard that labels them both as “emails” or “cases” can confuse the owner. A useful idea should name its denominator explicitly.
- Reply attribution depends on headers, conversation metadata, time, and visibility in a connected mailbox. Missing headers, forwarding, subject changes, and provider-specific thread IDs can make matching incomplete or ambiguous.
- CC observer copies currently use the broad `ignored` status in parts of the data model. A distinct `observer`/`duplicate copy` meaning would make the UI and ignored counts clearer.
- The stored `Email.receiver` field holds a comma-separated, length-limited To list. Very large recipient lists may need a normalized, lossless source alongside `EmailRecipient`.
- Manual assignment and actual reply credit currently share `assigned_employee_id`. A future change to ownership should preserve a distinct, immutable responder identity if reports need strong auditability.
- The AI worker reviews visible messages for one mailbox/employee grouping. A single conversation spanning several mailbox copies or missing message bodies can yield partial evidence. Full coaching scores intentionally remain absent when required evidence is missing.
- Model availability and quotas change. Ideas for provider selection or automatic fallback should show cost, quota, retry, and user-control implications; do not silently switch to a paid model.
- The current product is specialized to the exact `@indianinfotech.org` employee domain. A multi-tenant SaaS product would need tenant-specific domains, access boundaries, migrations, and tests before reuse.

## How to help the owner brainstorm

Start from the user's question, then inspect the relevant files above. Distinguish **what OEIS already does**, **the user's intended rule**, and **a proposed new feature**. For each idea, give a concrete example, the report or screen it changes, the expected benefit, and the smallest implementation that would work. Flag any change to reply credit, employee eligibility, historical counts, or AI model costs before suggesting rollout. Avoid using real customer emails or secrets in examples.

Example prompt to use with this file:

> Read `CLAUDE_PROJECT_HANDOFF.md` and verify relevant code. Suggest 5 practical improvements to the continuing-conversation and employee-performance reports. Use this example: a customer asks A and B about a meeting, A replies, the customer asks a follow-up in the same thread, and B replies. Show the message count, conversation count, pending state, and reply credit after each step. Separate current behavior from each proposal. Do not edit code yet.
