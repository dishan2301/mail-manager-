# Phase 1 and Phase 2 test-deployment validation

Validated 27 October 2026 on the isolated `oeis-test` deployment at port 8080. Its `oeis-data` volume is separate from the port-10002 MVP `oeis-test-data` volume. The test volume was backed up before migration, credential transfer, and live sync. The scheduler stayed disabled throughout validation.

No credential values or customer content are recorded here. Mailbox ID 2 connection configuration and the saved AI provider configuration were copied from the MVP into the isolated test volume at the owner's request. The MVP database was mounted read-only for the transfer and was not migrated or edited.

## Phase 1 acceptance

- F1: one live mailbox synchronized successfully. A temporary stale mailbox verified that a stale mailbox warns independently while the live mailbox remains fresh. Running the alert processor twice produced one alert event and one delivery attempt. The temporary mailbox and alert log were removed.
- F2: the live sync stored 400 physical messages: 34 pending obligations, 16 replied messages, 40 observer copies, and 310 classification/human ignored messages. Observer copies did not inflate ignored. With one connected mailbox there were no direct duplicate copies in this sample.
- F5: the copied key and model completed a real synthetic provider request. The successful result, model, and timestamp were persisted. No model change occurred.

## Phase 2 acceptance

- F6: all 16 replied messages had a distinct responder identity and reply credit. Repository totals were 16 replied, 34 pending, and 50 actionable customer messages. Historical rehearsal had already preserved all 44 credits and every `replied_at` timestamp from the local snapshot.
- F3: live data contained a conversation with multiple actionable customer messages. The deployed synthetic two-round fixture showed 2 customer messages, 1 conversation, 2 completed rounds, 0 pending obligations, and separate responder credit for each round. Mailbox-local grouping displays the partial-grouping warning.
- F13: the deployed synthetic fixture found an unmatched employee reply using subject/time evidence, manually linked it, recorded original and reply IDs in the audit log, recalculated responder credit, and retained the link through reconciliation. The fixture and audit row were removed.

## Verification

- Relevant Phase 1/2 backend tests: 37 passed after the mailbox-primary regression fix.
- Broader backend suite: 115 passed; one pre-existing authentication test received HTTP 429 from the persisted login throttle and is unrelated to these phases.
- Frontend production build passed.
- Test API health returned HTTP 200 on schema `0020`.

Phase 1 and Phase 2 acceptance checks are complete on `testing`. Release to `main` and port 10002 still requires review and explicit approval.
