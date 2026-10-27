from datetime import datetime, timezone

from app.models.entities import Mailbox


def mailbox_freshness(mailbox: Mailbox, stale_after_seconds: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    last = mailbox.last_synced_at
    if last and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    stale = bool(last and (now - last).total_seconds() > stale_after_seconds)
    return {"id": mailbox.id, "address": mailbox.address, "last_successful_sync": last,
            "stale": stale, "never_synced": last is None,
            "sync_error": bool(mailbox.last_sync_error)}
