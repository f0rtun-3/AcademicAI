"""Worker loop entry point.

A single loop that runs each job in its own transaction on a fixed interval.
Kept deliberately thin: all logic lives in jobs.py so it can be driven directly
from tests without sleeping or spawning a process.
"""
import logging
import os
import signal
import time

from ..app import create_app
from .jobs import run_once

log = logging.getLogger("academicai.worker")
_stop = False


def _handle_signal(_signum, _frame):  # pragma: no cover - signal path
    global _stop
    _stop = True


def run_forever(interval_seconds=None, app=None, max_iterations=None):  # pragma: no cover
    interval = interval_seconds or int(os.environ.get("ACADEMICAI_WORKER_INTERVAL", "60"))
    app = app or create_app()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    iterations = 0
    while not _stop:
        with app.app_context():
            results = run_once()
            log.info("worker cycle: %s", results)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        time.sleep(interval)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    run_forever()
