"""Scheduled SQLite backup (spec 32).

Uses SQLite's online backup API, which is safe to run against a live database
in WAL mode - unlike copying the file. Keeps the newest N backups.

    python backup_db.py --dest ./backups --keep 14
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone


def backup(source_path, dest_dir, keep=14):
    if not os.path.exists(source_path):
        raise SystemExit(f"Database not found: {source_path}")
    os.makedirs(dest_dir, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = os.path.join(dest_dir, f"academicai-{stamp}.db")

    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(target)
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()

    _prune(dest_dir, keep)
    return target


def _prune(dest_dir, keep):
    backups = sorted(
        (f for f in os.listdir(dest_dir)
         if f.startswith("academicai-") and f.endswith(".db")),
        reverse=True,
    )
    for stale in backups[keep:]:
        os.unlink(os.path.join(dest_dir, stale))


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description="Back up the AcademicAI SQLite database.")
    parser.add_argument("--source", default=os.environ.get(
        "ACADEMICAI_DB_PATH", "instance/academicai.db"))
    parser.add_argument("--dest", default=os.environ.get(
        "ACADEMICAI_BACKUP_DIR", "backups"))
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    path = backup(args.source, args.dest, args.keep)
    print(f"Backup written to {path}", file=sys.stderr)
