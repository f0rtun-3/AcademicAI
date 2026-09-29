"""Background jobs (spec 21).

Each job runs in its OWN transaction. A failure in one job must never roll back
work another job already completed, so run_once catches per-job failures and
keeps going. Every job is idempotent: running it twice must not promote a
candidate twice, duplicate a state transition, reopen a ballot, or send a
notification twice.
"""
import logging

from ..db.connection import transaction
from ..services import notification_service, reminder_service, removal_service, rep_service

log = logging.getLogger("academicai.worker")


def close_expired_nominations():
    with transaction() as conn:
        return rep_service.close_expired_ballots(conn=conn)


def close_expired_removals():
    with transaction() as conn:
        return removal_service.close_expired_ballots(conn=conn)


def process_event_reminders():
    with transaction() as conn:
        return reminder_service.process_due_event_reminders(conn=conn)


def process_personal_reminders():
    with transaction() as conn:
        return reminder_service.process_due_personal_reminders(conn=conn)


def dispatch_notifications():
    # Manages its own per-message transactions so one failed address does not
    # roll back deliveries that already succeeded.
    return notification_service.dispatch_pending()


JOBS = (
    ("close_expired_nominations", close_expired_nominations),
    ("close_expired_removals", close_expired_removals),
    ("process_event_reminders", process_event_reminders),
    ("process_personal_reminders", process_personal_reminders),
    ("dispatch_notifications", dispatch_notifications),
)


REMINDER_JOBS = frozenset({"process_event_reminders", "process_personal_reminders"})


def reminders_due():
    """True when a reminder is waiting to be processed now. A read, not a job:
    the loop asks it between cycles so a reminder fires as it comes due."""
    return reminder_service.any_due()


def run_once(jobs=JOBS):
    """Run every job once. Returns {job_name: result_or_error}."""
    results = {}
    for name, job in jobs:
        try:
            results[name] = job()
        except Exception as exc:  # one job failing must not stop the others
            log.exception("worker job failed: %s", name)
            results[name] = {"error": str(exc)}
    return results
