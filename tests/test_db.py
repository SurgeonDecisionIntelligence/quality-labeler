import csv
import sqlite3

import pytest

from quality_labeler.db import LabelStore, SchemaMismatch
from quality_labeler.inference import HeaderInfo
from quality_labeler.schema import Labels


def _store_with_series(tmp_path):
    store = LabelStore(tmp_path / "labels.db")
    store.upsert_series(
        "p1/s1",
        tmp_path,
        HeaderInfo(series_uid="1.2.3", echo_time=100.0),
        num_slices=12,
        num_files=12,
        load_error=None,
        guesses={"guess_plane": "sagittal", "guess_region": None, "guess_weight": "T2",
                 "guess_weight_reason": "description"},
    )
    return store


def test_roundtrip_and_multiple_labelers(tmp_path):
    store = _store_with_series(tmp_path)
    a = Labels(quality=5, motion=3, noise=3, fat_suppression=True, weight="T1", notes="ghosting")
    store.save_labels("p1/s1", "alice", a, expected_weight="T2", seconds_spent=3.0)
    store.save_labels("p1/s1", "bob", Labels(), expected_weight="T2", seconds_spent=1.0)

    assert store.get_labels("p1/s1", "alice") == a
    assert store.get_labels("p1/s1", "bob") == Labels()
    assert store.get_labels("p1/s1", "carol") is None
    assert store.labeled_keys("alice") == {"p1/s1"}


def test_relabel_overwrites_and_accumulates_time(tmp_path):
    store = _store_with_series(tmp_path)
    store.save_labels("p1/s1", "alice", Labels(), expected_weight=None, seconds_spent=2.0)
    store.save_labels("p1/s1", "alice", Labels(noise=2), expected_weight=None, seconds_spent=1.5)
    assert store.get_labels("p1/s1", "alice").noise == 2
    row = store.conn.execute("SELECT seconds_spent FROM labels").fetchone()
    assert row[0] == 3.5


def test_scales_round_trip_as_integers(tmp_path):
    store = _store_with_series(tmp_path)
    store.save_labels(
        "p1/s1", "alice", Labels(quality=4, hardware=3, misc_artifact=2),
        expected_weight=None, seconds_spent=1.0,
    )
    got = store.get_labels("p1/s1", "alice")
    assert (got.quality, got.hardware, got.misc_artifact) == (4, 3, 2)
    assert got.improper_acquisition is False and got.fat_suppression is False


def test_old_database_is_rejected(tmp_path):
    path = tmp_path / "labels.db"
    LabelStore(path).close()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 1")  # pretend it holds the previous label set
    conn.commit()
    conn.close()
    with pytest.raises(SchemaMismatch):
        LabelStore(path)


def test_export(tmp_path):
    store = _store_with_series(tmp_path)
    store.save_labels(
        "p1/s1", "alice", Labels(clipping=2, improper_acquisition=True),
        expected_weight="T2", seconds_spent=1,
    )
    out = tmp_path / "out.csv"
    assert store.export_csv(out) == 1
    (row,) = csv.DictReader(out.open())
    assert row["series_key"] == "p1/s1"
    assert row["clipping"] == "2"
    assert row["improper_acquisition"] == "1"
    assert row["quality"] == "1"  # the clean default
    assert row["guess_weight"] == "T2"
    assert row["series_uid"] == "1.2.3"
