# F2 status migration record (testing)

The local `backend/oeis.db` snapshot was inspected read-only before migration. It is at Alembic `0014` and is **not** the port-10002 MVP volume. A SQLite backup was made at `/home/dishan/oeis-f2-backup-20261026.db`; the original was not migrated.

| Measure | Before | After `0017` on the rehearsal copy |
| --- | ---: | ---: |
| Stored messages | 178 | 178 |
| Pending | 5 | 5 |
| Replied | 44 | 44 |
| Ignored | 129 | 129 |
| Observer copies | 0 | 0 |
| Duplicate copies | 0 | 0 |
| Replied with assigned responder | 44 | 44 |
| Recipient records | unavailable at `0014` | 0 |

Of the 129 ignored rows, 87 have Customer classification, but **none** is an inbox row. The new migration deliberately leaves sent-folder Customer mail in `ignored`. Thus this snapshot has no historical rows eligible for relabeling. Synthetic migration tests cover an inbox observer and a direct duplicate, including downgrade.

Definitions: `ignored` is a classification-ignored message or a human ignored status; `observer_copy` is a customer inbox message that creates no To obligation in that mailbox; `duplicate_copy` is an additional direct-To mailbox copy of a message tracked on another copy. New human Ignore actions persist through sync via `manually_ignored`. The old schema did not record this intent separately, so the migration conservatively leaves assigned/credited ignored rows unchanged. The dashboard copy counters are all-time physical rows. Report `total_received` still counts physical inbox rows; pending and replied form the reply-rate denominator. Employee reply credit remains assigned to the actual responder on the primary row.

## Deployment and rollback

Before applying to a test deployment, stop its scheduler, back up its database using the database's consistent backup mechanism, and export status/classification and report counts. Run `alembic upgrade 0017` on the test database, compare counts, then start the test service. The migration changes only unassigned, uncredited ignored Customer inbox rows and stores each changed row's old/new status in `email_status_0017_rollback`.

To roll back the test database, stop the scheduler and run `alembic downgrade 0016`. The downgrade restores a row only if it still has the status assigned by the migration, then drops the audit table and manual-ignore column. Keep the pre-migration database backup for a full restore, especially if new mail was synchronized after upgrade. This downgrade was rehearsed on the snapshot copy and restored the original status counts. Do not apply this procedure to the port-10002 MVP deployment before review and approval.
