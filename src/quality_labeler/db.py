"""SQLite storage: one `series` row per series, one `labels` row per (series, labeler)."""

import csv
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .inference import HeaderInfo
from .schema import FLAGS, SCHEMA_VERSION, Labels

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    series_key TEXT PRIMARY KEY,         -- path relative to the labeling root
    root TEXT NOT NULL,
    series_uid TEXT,
    study_uid TEXT,
    series_description TEXT,
    protocol_name TEXT,
    body_part TEXT,
    scanning_sequence TEXT,
    echo_time REAL,
    repetition_time REAL,
    inversion_time REAL,
    flip_angle REAL,
    field_strength REAL,
    num_slices INTEGER,
    num_files INTEGER,
    load_error TEXT,
    guess_plane TEXT,
    guess_region TEXT,
    guess_weight TEXT,
    guess_weight_reason TEXT
);

CREATE TABLE IF NOT EXISTS labels (
    series_key TEXT NOT NULL REFERENCES series(series_key),
    labeler TEXT NOT NULL,
    quality TEXT NOT NULL,
    noise TEXT NOT NULL,
    motion INTEGER NOT NULL,
    field_inhomogeneity INTEGER NOT NULL,
    clipping INTEGER NOT NULL,
    hardware INTEGER NOT NULL,
    misc_artifact INTEGER NOT NULL,
    improper_acquisition INTEGER NOT NULL,
    region TEXT NOT NULL,
    plane TEXT NOT NULL,
    weight TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    expected_weight TEXT,                -- --weight passed at runtime (NULL for auto)
    seconds_spent REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (series_key, labeler)
);
"""

_LABEL_COLS = Labels.field_names()
_BOOL_COLS = {f.name for f in FLAGS}


class SchemaMismatch(RuntimeError):
    """The database on disk was written with a different set of labels."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LabelStore:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        existing = self.conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'labels'"
        ).fetchone()[0]
        if existing and version != SCHEMA_VERSION:
            raise SchemaMismatch(
                f"{path} was written with label schema v{version}, this is v{SCHEMA_VERSION}. "
                "Label into a new database file."
            )
        self.conn.executescript(SCHEMA)
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self):
        self.conn.close()

    def upsert_series(
        self,
        key: str,
        root: Path,
        info: HeaderInfo,
        *,
        num_slices: int,
        num_files: int,
        load_error: str | None,
        guesses: dict[str, str | None],
    ):
        row = {
            "series_key": key,
            "root": str(root),
            "series_uid": info.series_uid,
            "study_uid": info.study_uid,
            "series_description": info.series_description,
            "protocol_name": info.protocol_name,
            "body_part": info.body_part,
            "scanning_sequence": info.scanning_sequence,
            "echo_time": info.echo_time,
            "repetition_time": info.repetition_time,
            "inversion_time": info.inversion_time,
            "flip_angle": info.flip_angle,
            "field_strength": info.field_strength,
            "num_slices": num_slices,
            "num_files": num_files,
            "load_error": load_error,
            **guesses,
        }
        cols = ", ".join(row)
        params = ", ".join(f":{c}" for c in row)
        updates = ", ".join(f"{c}=excluded.{c}" for c in row if c != "series_key")
        with self.conn:
            self.conn.execute(
                f"INSERT INTO series ({cols}) VALUES ({params}) "
                f"ON CONFLICT(series_key) DO UPDATE SET {updates}",
                row,
            )

    def save_labels(
        self,
        key: str,
        labeler: str,
        labels: Labels,
        *,
        expected_weight: str | None,
        seconds_spent: float | None,
    ):
        row = {
            "series_key": key,
            "labeler": labeler,
            **{k: int(v) if k in _BOOL_COLS else v for k, v in asdict(labels).items()},
            "expected_weight": expected_weight,
            "seconds_spent": seconds_spent,
            "created_at": _now(),
            "updated_at": _now(),
        }
        cols = ", ".join(row)
        params = ", ".join(f":{c}" for c in row)
        # On relabel keep created_at and add to the time already spent.
        updates = ", ".join(
            f"{c}=excluded.{c}"
            for c in row
            if c not in ("series_key", "labeler", "created_at", "seconds_spent")
        )
        with self.conn:
            self.conn.execute(
                f"INSERT INTO labels ({cols}) VALUES ({params}) "
                f"ON CONFLICT(series_key, labeler) DO UPDATE SET {updates}, "
                "seconds_spent = coalesce(seconds_spent, 0) + coalesce(excluded.seconds_spent, 0)",
                row,
            )

    def get_labels(self, key: str, labeler: str) -> Labels | None:
        row = self.conn.execute(
            "SELECT * FROM labels WHERE series_key = ? AND labeler = ?", (key, labeler)
        ).fetchone()
        if row is None:
            return None
        return Labels(**{c: bool(row[c]) if c in _BOOL_COLS else row[c] for c in _LABEL_COLS})

    def labeled_keys(self, labeler: str) -> set[str]:
        rows = self.conn.execute("SELECT series_key FROM labels WHERE labeler = ?", (labeler,))
        return {r[0] for r in rows}

    def export_csv(self, out: Path) -> int:
        cur = self.conn.execute(
            "SELECT l.*, s.* FROM labels l JOIN series s USING (series_key) "
            "ORDER BY l.series_key, l.labeler"
        )
        names = list(dict.fromkeys(d[0] for d in cur.description))
        rows = cur.fetchall()
        with open(out, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(names)
            for r in rows:
                writer.writerow([r[n] for n in names])
        return len(rows)
