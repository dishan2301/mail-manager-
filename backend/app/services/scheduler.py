from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime,timezone
from app.core.config import get_settings
def build_scheduler(sync_job,summary_job,ai_review_job):
    settings=get_settings();scheduler=AsyncIOScheduler(timezone=settings.app_timezone)
    scheduler.add_job(sync_job,"interval",seconds=settings.sync_interval_seconds,id="mailbox-sync",max_instances=1,coalesce=True)
    scheduler.add_job(summary_job,"cron",hour=settings.summary_hour,minute=0,id="daily-summary",max_instances=1,coalesce=True)
    scheduler.add_job(ai_review_job,"interval",seconds=30,next_run_time=datetime.now(timezone.utc),id="conversation-ai-review",max_instances=1,coalesce=True)
    return scheduler

def apply_sync_settings(scheduler,sync_job,interval_seconds:int,enabled:bool)->None:
    job=scheduler.get_job("mailbox-sync")
    if job:
        scheduler.reschedule_job("mailbox-sync",trigger="interval",seconds=interval_seconds)
        (scheduler.resume_job if enabled else scheduler.pause_job)("mailbox-sync")
    elif enabled:
        scheduler.add_job(sync_job,"interval",seconds=interval_seconds,id="mailbox-sync",max_instances=1,coalesce=True)
