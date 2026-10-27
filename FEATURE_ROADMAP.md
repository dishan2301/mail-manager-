# OEIS feature roadmap for `testing`

Updated 26 October 2026. This plan covers ideas F1–F22 from the owner’s roadmap. It describes proposed work, not features already delivered. The source code, not the older handoff or competitor notes, is the baseline. `main` is the stable MVP; all development and validation happen on `testing` or a feature branch based on it. Merge tested work to `main` through a pull request.

## How to work through the phases

1. Implement one feature or a small related set on `testing` (or `feature/<name>` branched from it). Give each feature its own acceptance tests and short before/after notes.
2. For changes to stored data, take a database backup and document migration and rollback before testing against a copy of real data. Compare historical counts before and after.
3. Run relevant backend tests and the frontend build. For features using a mail provider or AI provider, test the integration with a controlled mailbox/account. Do not put credentials or real customer content in commits.
4. Validate the candidate in the **test deployment**. Do not rebuild the port-10002 MVP container just to test a feature. Release to that container only after the feature is accepted and merged to `main`.
5. Open a pull request from `testing` to `main`, review its exact diff and metric changes, then merge. Update `testing` from `main` before the next release.

There is no fixed calendar promise. Advance when each phase's acceptance checks pass. The labels below indicate dependencies, not a requirement to merge a whole phase as one release.

### Progress on `testing`

- Phase 0: an automated two-round, shared-To conversation fixture now protects the message and reply-credit baseline. Remaining baseline fixtures and a recorded before/after count export are still needed before a status migration.
- Phase 1 complete on `testing`: F1 independent freshness and alert deduplication, F2 status separation and counts, and F5 real synthetic-provider health were validated in the isolated test deployment.
- Phase 2 complete on `testing`: F6 immutable responder credit, F3 conversation rounds and partial grouping, and F13 audited manual linking were validated in the isolated test deployment.
- Validation evidence and count comparisons are recorded in [PHASE1_2_TEST_VALIDATION.md](PHASE1_2_TEST_VALIDATION.md). Merge and port-10002 release still require review and explicit approval.

## Phase 0 — Baseline and metric definitions

**Goal:** Know when the new features change numbers.

- Record representative test cases: CEO in CC; one and two employees in To; one responder; another employee replies; customer follow-up in the same conversation; duplicate copies across mailboxes; sync failure; missing AI evidence.
- Write down the current dashboard and employee-report counts for those cases. Define **customer messages**, **conversations**, **completed response rounds**, **pending obligations**, and **credited replies** separately.
- Decide which test mailbox and test Docker container are used for development. Keep the existing port-10002 container on the MVP until a release is approved.

**Exit:** Repeatable fixtures and baseline counts exist; no production mailbox data is copied into GitHub.

## Phase 1 — Trustworthy health and statuses

| ID | Work | Current baseline | Acceptance check |
| --- | --- | --- | --- |
| F5 | AI Settings: Test connection, model/API error, timestamp and retry guidance | Provider settings and review errors exist; connection test does not | An unavailable model reports its actual failure before reviews are enabled; no automatic paid-model change |
| F1 | Per-mailbox last successful sync, configurable stale threshold, dashboard banner and admin alert | Last sync/error and overall readiness exist | One stale mailbox warns even when another mailbox synced recently; alert is not repeatedly sent |
| F2 | Separate `observer_copy` and `duplicate_copy` from true classification `ignored` | Only pending/replied/ignored exist | CC and duplicate copies do not inflate ignored; To obligations and reply credit match the baseline; migration includes before/after counts |

Implement F5 and F1 independently. F2 needs a reviewed migration because historical ignored counts will change. Show old and new definitions clearly in dashboard and reports.

## Phase 2 — Conversations and auditable credit

| ID | Work | Current baseline | Acceptance check |
| --- | --- | --- | --- |
| F6 | Store responder identity separately from assignment; preserve existing `replied_at` | Assignment currently doubles as reply credit | Manual reassignment never transfers reply credit; historical backfill is checked against old reports |
| F3 | Read-only conversation view: customer messages, response rounds, handovers, per-round timing | Conversation IDs and AI conversation counts exist | P→A/B, A replies, P follows up, B replies displays 2 messages, 1 conversation, 2 completed rounds, credit A=1/B=1 |
| F13 | Unmatched-reply diagnostics and audited manual linking | Automatic matching exists | Admin sees match evidence and can link a reply; audit records actor, original and reply IDs; counts recalculate correctly |

Build F6 before extending assignment or manual reply linking. In F3, show a **partial grouping** label when provider IDs cannot safely connect mailbox copies. Do not invent a cross-mailbox conversation match.

## Phase 3 — Act before an SLA breach

| ID | Work | Current baseline | Acceptance check |
| --- | --- | --- | --- |
| F4 | Early assignee warning, manager/CEO escalation, quiet hours and deduplication | Manager/director threshold emails exist | A pending message generates each configured step once; a completed message stops later steps |
| F7 | Editable VIP sender/domain and keyword priority rules | SLA urgency exists, but no VIP rules | Rules show the reason for priority and can be overridden; no AI call is needed |
| F8 | SLA policy by customer group/category, applied to new mail | Global thresholds and calendars exist | VIP/retail messages use their own saved policy; old SLA outcomes do not silently change |
| F21 | OEIS composer warning when a reply has arrived meanwhile | Reply composer exists | Before sending, refresh the thread and warn about a newly observed reply; user explicitly decides whether to continue |

Start notifications with existing email delivery. Teams and WhatsApp are later channel integrations; confirm provider access, cost and recipient rules before adding them. F21 covers the OEIS composer only, not typing in Outlook or Gmail.

## Phase 4 — CEO insight and staff visibility

| ID | Work | Current baseline | Acceptance check |
| --- | --- | --- | --- |
| F9 | Configurable business-topic tags and weekly trends, starting with metadata rules | Classification exists, business topics do not | Every topic count names its message denominator; an uncertain match can remain untagged |
| F14 | Extend the existing daily summary into a concise CEO brief | Daily summary already exists | Brief shows urgent pending items, freshness and topic trends, with links to underlying mail |
| F20 | Employee self-view limited to that person's items and metrics | Admin/Manager roles exist | An employee cannot fetch another employee's data through UI or API |
| F22 | Volume and reply-rate anomaly alerts | Growth metrics exist | Alert compares like periods, states its baseline, and suppresses noise when sync is stale |
| F19 | Improve mobile web use; then assess installable PWA and push | Responsive layouts exist; PWA/push do not | Dashboard, pending list and brief work on narrow screens before any push capability is added |

Topic rules should be editable and measured against a small approved sample. Do not send message bodies to AI for topic tagging unless the owner separately chooses that scope and budget.

## Phase 5 — Follow-through and fair handling

| ID | Work | Current baseline | Acceptance check |
| --- | --- | --- | --- |
| F11 | Separate `awaiting_resolution` flag for acknowledgment-only replies | Any linked reply closes pending | Reply credit remains intact; unresolved follow-up is visible without relabeling the reply as unanswered |
| F12 | Employee leave dates, backup ownership and a documented SLA policy | Company calendars exist | Reports identify leave treatment; backup receives pending work; SLA changes are compared before/after |
| F10 | Opt-in promise tracker with human correction and due-date reminders | No promise tracking | An extracted promise includes source evidence, due date and confidence; false promises can be dismissed; no automatic performance penalty |

Decide whether leave pauses SLA or transfers ownership before coding F12. F10 and F11 affect how people are evaluated, so pilot with users and show the new measure separately from reply credit.

## Phase 6 — Customer-specific expansion

These are planned discovery and pilot items, not commitments to integrate every service before a customer needs it.

| ID | Work | First gate |
| --- | --- | --- |
| F17 | Hindi, Gujarati and Hinglish topic/sentiment evaluation | Obtain an approved, representative sample and measure accuracy before choosing rules or AI |
| F18 | Client-scoped SLA PDF/CSV | Prove a client can access only its own records, including exports and links |
| F15 | Shopify/WooCommerce order context | Select the first pilot's commerce system, permissions and retention rules |
| F16 | Natural-language questions over approved report queries | Start with read-only, predefined query templates and explicit source/count citations |

## SaaS readiness — separate product track

The current MVP is single tenant and uses a fixed `@indianinfotech.org` employee rule. Before selling a multi-tenant service: tenant-specific domains, strict data separation throughout API/jobs/storage, tenant-aware migrations and tests, production database/backup design, onboarding, billing, retention and employee-monitoring policy must be designed and validated. Do not market the single-tenant MVP as a multi-tenant SaaS before those gates pass.

## Decisions to record before dependent work

- F9/F10/F17: whether AI may read message bodies, which provider/model, monthly spending limit and data-retention policy.
- F11: whether `awaiting_resolution` appears only as a separate flag or also changes any report numerator.
- F12: leave behavior for ownership and SLA clock.
- F4: first delivery channel after email, and who receives each escalation.
- F15/F17: which customer segment and pilot account to optimize for first.

Keep missing evidence unscored, never auto-send AI replies, and do not change reply credit or historical counts without a documented before/after comparison in the pull request.
