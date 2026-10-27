# F13 reply-link migration (testing)

The local `backend/oeis.db` snapshot was backed up to `/home/dishan/oeis-f13-backup-20261027.db` without changing the source. This is not the port-10002 MVP database. An isolated copy was upgraded to `0020` and downgraded to `0019`.

| Measure | Before | After `0020` |
| --- | ---: | ---: |
| Pending | 5 | 5 |
| Replied | 44 | 44 |
| Ignored | 129 | 129 |
| Credited replies | 44 | 44 |
| Persisted reply links | unavailable | 0 |

Migration `0020` adds nullable reply ID and link-source fields; it does not infer historical links or change status, credit, or timestamps. A subsequent controlled sync can populate automatic links. Until then, candidate diagnostics may show historical replies without a saved link. Manually linking a candidate records the original and reply IDs in the audit log and recalculates the original's status and responder credit. The link persists across later reconciliation.

Before applying to a test database, stop synchronization, make a consistent backup, and export status, reply-credit, and report counts. Run `alembic upgrade 0020`, compare counts, then run controlled sync and inspect candidate diagnostics. To roll back, stop synchronization and run `alembic downgrade 0019`; this drops saved links, so retain the backup and audit export if manual links were made. Do not migrate the port-10002 MVP database without separate review and approval.
