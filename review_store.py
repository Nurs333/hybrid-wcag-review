"""SQLite review storage for benchmark cases and individual website scans."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


DATABASE = Path(__file__).resolve().parent / "human_reviews.db"


def initialize():
    with closing(sqlite3.connect(DATABASE)) as connection, connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                page TEXT PRIMARY KEY, decision TEXT NOT NULL, notes TEXT NOT NULL,
                ai_decision TEXT NOT NULL, response_id TEXT NOT NULL,
                reviewed_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS website_reviews (
                scan_id TEXT NOT NULL, image_key TEXT NOT NULL,
                decision TEXT NOT NULL, notes TEXT NOT NULL,
                assessment_id TEXT NOT NULL, reviewed_at TEXT NOT NULL,
                PRIMARY KEY (scan_id, image_key)
            )
        """)


def benchmark_reviews():
    with closing(sqlite3.connect(DATABASE)) as connection:
        rows = connection.execute("SELECT page, decision, notes FROM reviews").fetchall()
    return {row[0]: {"decision": row[1], "notes": row[2]} for row in rows}


def save_benchmark_review(page, decision, notes, result):
    if decision not in {"pass", "issue", "uncertain"}:
        raise ValueError("Choose a review decision.")
    with closing(sqlite3.connect(DATABASE)) as connection, connection:
        connection.execute("""
            INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(page) DO UPDATE SET
                decision=excluded.decision, notes=excluded.notes,
                ai_decision=excluded.ai_decision, response_id=excluded.response_id,
                reviewed_at=excluded.reviewed_at
        """, (page, decision, notes, result["decision"], result["response_id"], datetime.now(timezone.utc).isoformat()))


def website_reviews(scan_id):
    with closing(sqlite3.connect(DATABASE)) as connection:
        rows = connection.execute(
            "SELECT image_key, decision, notes, assessment_id FROM website_reviews WHERE scan_id=?",
            (scan_id,),
        ).fetchall()
    return {row[0]: {"decision": row[1], "notes": row[2], "assessment_id": row[3]} for row in rows}


def save_website_review(scan_id, image_key, decision, notes, assessment_id):
    if decision not in {"pass", "issue", "uncertain"}:
        raise ValueError("Choose a review decision.")
    with closing(sqlite3.connect(DATABASE)) as connection, connection:
        connection.execute("""
            INSERT INTO website_reviews VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(scan_id, image_key) DO UPDATE SET
                decision=excluded.decision, notes=excluded.notes,
                assessment_id=excluded.assessment_id, reviewed_at=excluded.reviewed_at
        """, (scan_id, image_key, decision, notes, assessment_id, datetime.now(timezone.utc).isoformat()))
