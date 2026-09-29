"""Worker loop entry point.

A single loop that runs each job in its own transaction on a fixed interval -
and, between cycles, WAKES EARLY when a reminder comes due. Every few seconds
it asks one cheap question (is a reminder due now? two indexed EXISTS
queries); when the answer is yes it runs the cycle at once. So a reminder
fires within seconds of its time instead of up to a whole interval late
(60s in production), and its email goes out in the same cycle.

Kept deliberately thin: all logic lives in jobs.py so it can be driven directly
from tests without sleeping or spawning a process.
"""
import logging
import os
import signal
import time

from ..app import create_app
from .jobs import REMINDER_JOBS, reminders_due, run_once

log = logging.getLogger("academicai.worker")
_stop = False

# How often, between cycles, the loop asks whether a reminder is due.
REMINDER_CHECK_SECONDS = 2


def _handle_signal(_signum, _frame):  # pragma: no cover - signal path
    global _stop
    _stop = True


def wait_for_next_cycle(interval, due, step=REMINDER_CHECK_SECONDS,
                        sleep=time.sleep, stopped=lambda: _stop):
    """Wait up to `interval` seconds, asking `due()` every `step` seconds.

    Returns "due" as soon as a reminder is due, "interval" when the full wait
    elapsed, or "stopped" on shutdown. `sleep` and `stopped` are seams for
    tests; the loop uses the real ones.
    """
    waited = 0.0
    while waited < interval:
        if stopped():
            return "stopped"
        pause = min(step, interval - waited)
        sleep(pause)
        waited += pause
        try:
            if due():
                return "due"
        except Exception:  # a failed check is not a reason to stop the loop
            log.exception("worker: could not check for due reminders")
    return "interval"


def run_forever(interval_seconds=None, app=None, max_iterations=None):  # pragma: no cover
    interval = interval_seconds or int(os.environ.get("ACADEMICAI_WORKER_INTERVAL", "60"))
    app = app or create_app()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    def due():
        with app.app_context():
            return reminders_due()

    iterations = 0
    while not _stop:
        with app.app_context():
            results = run_once()
            log.info("worker cycle: %s", results)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        # A reminder job that just failed would still see its row as due, and
        # waking early for it would re-run a failing cycle every few seconds.
        # Then the loop waits the plain interval, as it always did.
        reminder_failed = any(isinstance(results.get(name), dict) and "error" in results[name]
                              for name in REMINDER_JOBS)
        if reminder_failed:
            time.sleep(interval)
        else:
            wait_for_next_cycle(interval, due)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    run_forever()
