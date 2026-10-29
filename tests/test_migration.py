"""Opening a database written by the previous, path-keyed build.

The schema below is v4 as it shipped: `labels` has no `series_uid` column and is
keyed on (series_key, labeler). Opening such a file must keep every label and make
it findable by UID, without the user having to start a new database.
"""

import sqlite3

import pytest

from quality_labeler.db import AmbiguousHistory, LabelStore
from quality_labeler.schema import SCHEMA_VERSION

OLD_SCHEMA = """
CREATE TABLE series (
    series_key TEXT PRIMARY KEY,
    root TEXT NOT NULL,
    series_uid TEXT,
    study_uid TEXT,
    series_description TEXT,
    num_slices INTEGER,
    num_files INTEGER,
    load_error TEXT,
    guess_plane TEXT,
    guess_region TEXT,
    guess_weight TEXT,
    guess_weight_reason TEXT
);
CREATE TABLE labels (
    series_key TEXT NOT NULL REFERENCES series(series_key),
    labeler TEXT NOT NULL,
    quality INTEGER NOT NULL,
    noise INTEGER NOT NULL,
    motion INTEGER NOT NULL,
    field_inhomogeneity INTEGER NOT NULL,
    clipping INTEGER NOT NULL,
    hardware INTEGER NOT NULL,
    misc_artifact INTEGER NOT NULL,
    improper_acquisition INTEGER NOT NULL,
    fat_suppression INTEGER NOT NULL,
    region TEXT NOT NULL,
    plane TEXT NOT NULL,
    weight TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    expected_weight TEXT,
    seconds_spent REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (series_key, labeler)
);
"""

LABEL_COLUMNS = (
    "series_key, labeler, quality, noise, motion, field_inhomogeneity, clipping, hardware,"
    " misc_artifact, improper_acquisition, fat_suppression, region, plane, weight, notes,"
    " created_at, updated_at"
)


def write_old_database(path, rows, series):
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.executemany(
        "INSERT INTO series (series_key, root, series_uid, series_description)"
        " VALUES (?, '/data', ?, 'SAG T2')",
        series,
    )
    conn.executemany(
        f"INSERT INTO labels ({LABEL_COLUMNS}) VALUES (?, ?, ?, 1, 1, 1, 1, 1, 1, 0, 0,"
        " 'lumbar', 'sagittal', 'T2', '', '2026-01-01', '2026-01-01')",
        rows,
    )
    conn.commit()
    conn.close()


def test_old_labels_are_kept_and_found_by_uid(tmp_path):
    path = tmp_path / "labels.db"
    write_old_database(
        path,
        rows=[("p1/s1", "alice", 3), ("p1/s2", "alice", 1), ("p1/s1", "bob", 2)],
        series=[("p1/s1", "1.2.840.1"), ("p1/s2", "1.2.840.2")],
    )

    store = LabelStore(path)   # migrates in place

    assert store.get_labels("1.2.840.1", "alice").quality == 3
    assert store.get_labels("1.2.840.1", "bob").quality == 2
    assert store.get_labels("1.2.840.2", "alice").quality == 1
    assert store.labeled_uids("alice") == {"1.2.840.1", "1.2.840.2"}
    # Nothing was lost or duplicated.
    assert store.conn.execute("SELECT count(*) FROM labels").fetchone()[0] == 3


def test_old_rows_whose_series_had_no_uid_fall_back_to_the_path(tmp_path):
    path = tmp_path / "labels.db"
    write_old_database(path, rows=[("p1/s1", "alice", 4)], series=[("p1/s1", None)])

    store = LabelStore(path)

    assert store.get_labels("nouid:p1/s1", "alice").quality == 4
    assert store.labeled_uids("alice") == {"nouid:p1/s1"}


def test_relabelling_a_migrated_row_updates_it_rather_than_adding_one(tmp_path):
    from quality_labeler.schema import Labels

    path = tmp_path / "labels.db"
    write_old_database(path, rows=[("p1/s1", "alice", 3)], series=[("p1/s1", "1.2.840.1")])

    store = LabelStore(path)
    store.save_labels("1.2.840.1", "alice", Labels(quality=5), series_key="moved/s1",
                      expected_weight=None, seconds_spent=2.0)

    rows = store.conn.execute("SELECT series_key, quality FROM labels").fetchall()
    assert [tuple(r) for r in rows] == [("moved/s1", 5)]


def test_an_old_file_is_still_readable_by_a_path_keyed_build(tmp_path):
    """The migration only adds a column, so the old query still answers."""
    path = tmp_path / "labels.db"
    write_old_database(path, rows=[("p1/s1", "alice", 3)], series=[("p1/s1", "1.2.840.1")])
    LabelStore(path).close()

    conn = sqlite3.connect(path)
    row = conn.execute(
        "SELECT quality FROM labels WHERE series_key = 'p1/s1' AND labeler = 'alice'"
    ).fetchone()
    conn.close()
    assert row[0] == 3


def test_a_series_labeled_at_two_paths_is_reported_not_silently_merged(tmp_path):
    """Under path keys the same series could be labeled twice; that cannot be keyed by UID."""
    path = tmp_path / "labels.db"
    write_old_database(
        path,
        rows=[("p1/copy_a", "alice", 2), ("p1/copy_b", "alice", 5)],
        series=[("p1/copy_a", "1.2.840.1"), ("p1/copy_b", "1.2.840.1")],
    )

    with pytest.raises(AmbiguousHistory) as excinfo:
        LabelStore(path)
    assert "copy_a" in str(excinfo.value) and "copy_b" in str(excinfo.value)
