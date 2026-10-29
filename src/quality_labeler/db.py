"""SQLite storage: one `series` row per series, one `labels` row per (series, labeler)."""

import csv
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .inference import HeaderInfo, is_interpolated
from .schema import FLAGS, SCALES, SCHEMA_VERSION, Labels

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
    rows INTEGER,
    columns INTEGER,
    acquired_rows INTEGER,
    acquired_columns INTEGER,
    pixel_spacing_row REAL,
    pixel_spacing_column REAL,
    slice_thickness REAL,
    slice_spacing REAL,               -- measured from slice positions when available
    interpolated INTEGER,             -- stored matrix larger than the acquired one
    num_slices INTEGER,
    num_files INTEGER,
    load_error TEXT,
    guess_plane TEXT,
    guess_region TEXT,
    guess_weight TEXT,
    guess_weight_reason TEXT
);

CREATE TABLE IF NOT EXISTS labels (
    series_key TEXT NOT NULL REFERENCES series(series_key),  -- last known path, for reference
    series_uid TEXT,                     -- the identity: SeriesInstanceUID, or nouid:<path>
    labeler TEXT NOT NULL,
    quality INTEGER NOT NULL,            -- 1 (best) .. 5 (worst)
    noise INTEGER NOT NULL,              -- the graded findings below are 1 (none) .. 3 (severe)
    motion INTEGER NOT NULL,
    field_inhomogeneity INTEGER NOT NULL,
    clipping INTEGER NOT NULL,
    hardware INTEGER NOT NULL,
    misc_artifact INTEGER NOT NULL,
    improper_acquisition INTEGER NOT NULL,   -- 0/1
    fat_suppression INTEGER NOT NULL,        -- 0/1
    region TEXT NOT NULL,
    plane TEXT NOT NULL,
    weight TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    expected_weight TEXT,                -- --weight passed at runtime (NULL for auto)
    seconds_spent REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (series_key, labeler)   -- kept for compatibility; identity is the index below
);

CREATE UNIQUE INDEX IF NOT EXISTS labels_by_uid ON labels (series_uid, labeler);
CREATE INDEX IF NOT EXISTS series_by_uid ON series (series_uid);

-- Remembers each folder's SeriesInstanceUID so startup need not re-read every header.
CREATE TABLE IF NOT EXISTS uid_cache (
    root TEXT NOT NULL,
    series_key TEXT NOT NULL,
    series_uid TEXT NOT NULL,
    dir_mtime REAL NOT NULL,
    PRIMARY KEY (root, series_key)
);
"""

_LABEL_COLS = Labels.field_names()
_BOOL_COLS = {f.name for f in FLAGS}
_INT_COLS = {s.name for s in SCALES}


class SchemaMismatch(RuntimeError):
    """The database on disk was written with a different set of labels."""


class AmbiguousHistory(RuntimeError):
    """Older path-keyed rows that collapse onto one series once keyed by UID."""


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
        self._migrate_to_uid_keys()
        self.conn.executescript(SCHEMA)
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _migrate_to_uid_keys(self):
        """Give an older, path-keyed database the series_uid column, in place.

        Only adds a column and backfills it, so a database stays readable by builds
        that still key on the path.
        """
        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "labels" not in tables:
            return  # new file; the schema script creates it with the column
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(labels)")}
        if "series_uid" in columns:
            return
        with self.conn:
            self.conn.execute("ALTER TABLE labels ADD COLUMN series_uid TEXT")
            # The series table already recorded each path's UID when it was labeled.
            self.conn.execute(
                "UPDATE labels SET series_uid = coalesce("
                "  (SELECT s.series_uid FROM series s WHERE s.series_key = labels.series_key),"
                "  'nouid:' || labels.series_key)"
                " WHERE series_uid IS NULL"
            )
        clashes = self.conn.execute(
            "SELECT series_uid, labeler, count(*) AS n, group_concat(series_key, ' + ') AS paths"
            " FROM labels GROUP BY series_uid, labeler HAVING n > 1 LIMIT 5"
        ).fetchall()
        if clashes:
            detail = "; ".join(f"{r['labeler']} labeled {r['paths']}" for r in clashes)
            raise AmbiguousHistory(
                "This database has the same series labeled at more than one path, so its "
                f"rows cannot be keyed by SeriesInstanceUID without losing one: {detail}. "
                "Resolve the duplicates (keep one row per series and labeler), then reopen."
            )

    def close(self):
        self.conn.close()

    def upsert_series(
        self,
        key: str,
        root: Path,
        info: HeaderInfo,
        *,
        series_uid: str | None = None,
        num_slices: int,
        num_files: int,
        load_error: str | None,
        guesses: dict[str, str | None],
    ):
        row = {
            "series_key": key,
            "root": str(root),
            "series_uid": series_uid or info.series_uid,
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
            "rows": info.rows,
            "columns": info.columns,
            "acquired_rows": info.acquired[0] if info.acquired else None,
            "acquired_columns": info.acquired[1] if info.acquired else None,
            "pixel_spacing_row": info.pixel_spacing[0] if info.pixel_spacing else None,
            "pixel_spacing_column": info.pixel_spacing[1] if info.pixel_spacing else None,
            "slice_thickness": info.slice_thickness,
            "slice_spacing": info.slice_spacing,
            "interpolated": int(is_interpolated(info)),
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
        series_uid: str,
        labeler: str,
        labels: Labels,
        *,
        series_key: str,
        expected_weight: str | None,
        seconds_spent: float | None,
    ):
        """Store one person's labels for one series, identified by its UID.

        series_key travels along as the last known path, so a series that moved on
        disk updates its path instead of becoming a second row.
        """
        row = {
            "series_key": series_key,
            "series_uid": series_uid,
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
            if c not in ("series_uid", "labeler", "created_at", "seconds_spent")
        )
        with self.conn:
            self.conn.execute(
                f"INSERT INTO labels ({cols}) VALUES ({params}) "
                f"ON CONFLICT(series_uid, labeler) DO UPDATE SET {updates}, "
                "seconds_spent = coalesce(seconds_spent, 0) + coalesce(excluded.seconds_spent, 0)",
                row,
            )

    def get_labels(self, series_uid: str, labeler: str) -> Labels | None:
        row = self.conn.execute(
            "SELECT * FROM labels WHERE series_uid = ? AND labeler = ?", (series_uid, labeler)
        ).fetchone()
        if row is None:
            return None
        def value(column):
            if column in _BOOL_COLS:
                return bool(row[column])
            return int(row[column]) if column in _INT_COLS else row[column]

        return Labels(**{c: value(c) for c in _LABEL_COLS})

    def labeled_uids(self, labeler: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT series_uid FROM labels WHERE labeler = ? AND series_uid IS NOT NULL",
            (labeler,),
        )
        return {r[0] for r in rows}

    def cached_uids(self, root: Path) -> dict[str, tuple[str, float]]:
        """What the last scan found, so unchanged folders need not be read again."""
        rows = self.conn.execute(
            "SELECT series_key, series_uid, dir_mtime FROM uid_cache WHERE root = ?", (str(root),)
        )
        return {r["series_key"]: (r["series_uid"], r["dir_mtime"]) for r in rows}

    def remember_uids(self, root: Path, found: dict[str, tuple[str, float]]):
        with self.conn:
            self.conn.executemany(
                "INSERT INTO uid_cache (root, series_key, series_uid, dir_mtime)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(root, series_key) DO UPDATE SET"
                " series_uid = excluded.series_uid, dir_mtime = excluded.dir_mtime",
                [(str(root), key, uid, mtime) for key, (uid, mtime) in found.items()],
            )

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
