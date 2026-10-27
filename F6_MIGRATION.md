# F6 responder backfill (testing)

The local `backend/oeis.db` snapshot was read without modification and backed up to `/home/dishan/oeis-f6-backup-20261026.db`. This is a local `0014` database, not the port-10002 MVP volume. An isolated copy was upgraded through `0019`, compared, and downgraded to `0018`.

| Measure | Before | After `0019` on rehearsal copy |
| --- | ---: | ---: |
| Replied messages | 44 | 44 |
| Credited replies | 44 (assigned owner) | 44 (responder) |
| Replied rows with timestamp | 44 | 44 |
| Employees with reply credit | 3 | 3 |

Every historical replied row's responder equals its pre-migration assigned employee. Per-employee credit counts and every saved `replied_at` value matched exactly before and after. The migration does not rewrite assignment or timestamps. It adds `responder_employee_id` and an `assignment_overridden` flag; new manual assignment changes ownership only. A replied message with unknown sender identity has no invented employee credit.

Before deployment to a test database, stop synchronization, make a consistent database backup, and export replied counts, per-employee credited replies, and timestamps. Run `alembic upgrade 0019` and compare those measures. For rollback, stop synchronization and run `alembic downgrade 0018`; restoring the backup is the complete fallback if new mail was processed. Do not migrate the port-10002 MVP database without separate review and approval.
