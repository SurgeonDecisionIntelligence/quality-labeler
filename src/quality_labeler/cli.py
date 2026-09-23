"""Command line entry point: `quality-labeler label ROOT` and `quality-labeler export OUT.csv`."""

import argparse
import getpass
import sys
from pathlib import Path

from .db import LabelStore, SchemaMismatch
from .schema import WEIGHTS


def _label(args):
    from PySide6.QtWidgets import QApplication

    from .app import LabelerWindow
    from .dicom_io import discover_series

    root = args.root.resolve()
    print(f"Scanning {root} for series folders…", flush=True)
    paths = discover_series(root)
    if not paths:
        sys.exit(f"No series folders found under {root}")
    print(f"Found {len(paths)} series.", flush=True)

    try:
        store = LabelStore(args.db)
    except SchemaMismatch as e:
        sys.exit(str(e))

    app = QApplication(sys.argv[:1])
    window = LabelerWindow(
        root,
        paths,
        store,
        labeler=args.labeler,
        expected_weight=None if args.weight == "auto" else args.weight,
        relabel=args.relabel,
    )
    window.resize(1600, 1000)
    window.show()
    sys.exit(app.exec())


def _export(args):
    try:
        store = LabelStore(args.db)
    except SchemaMismatch as e:
        sys.exit(str(e))
    n = store.export_csv(args.out)
    print(f"Wrote {n} label rows to {args.out}")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(prog="quality-labeler", description=__doc__)
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("label", help="open the labeling window")
    p.add_argument("root", type=Path, help="directory whose sub-folders are DICOM series")
    p.add_argument("--db", type=Path, default=Path("labels.db"), help="SQLite file (default: labels.db)")
    p.add_argument(
        "--weight",
        choices=("auto", *WEIGHTS),
        default="auto",
        help="expected weighting, used as the default label (auto: guess from DICOM header)",
    )
    p.add_argument("--labeler", default=getpass.getuser(), help="labeler name (default: $USER)")
    p.add_argument("--relabel", action="store_true", help="also step through series you already labeled")
    p.set_defaults(func=_label)

    p = sub.add_parser("export", help="write all labels joined with series metadata to CSV")
    p.add_argument("out", type=Path)
    p.add_argument("--db", type=Path, default=Path("labels.db"))
    p.set_defaults(func=_export)

    args = parser.parse_args(argv)
    args.func(args)
