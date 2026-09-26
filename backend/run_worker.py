"""Background worker entry point (spec 21).

Run this as a separate process from the API server:

    python run_worker.py
"""
import logging

from academicai.worker.worker import run_forever

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_forever()
