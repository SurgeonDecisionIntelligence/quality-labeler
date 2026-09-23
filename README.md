# quality-labeler

Keyboard-driven desktop tool for labeling the quality of MRI DICOM series quickly.

## Usage

```bash
uv sync
uv run quality-labeler label /data/mri_root --weight T2 --db labels.db
uv run quality-labeler export labels.csv --db labels.db
```

Every folder under the root that contains files is treated as one series. Series you
have already labeled are skipped, so you can quit and resume at any time. Each save is
committed immediately.

Options for `label`:

| Option | Meaning |
|---|---|
| `--weight` | Expected weighting (`T1`, `T2`, …), used as the default weight label. `auto` (default) uses the guess from the DICOM header instead. |
| `--labeler` | Name stored with each label (default `$USER`). Each labeler has their own labels for a series. |
| `--db` | SQLite file (default `labels.db`). |
| `--relabel` | Step through series you have already labeled too. |

## Keys

| Key | Action |
|---|---|
| `Enter` / `Space` | Save and go to the next unlabeled series |
| `1` `2` `3` | Quality: accept / partially accept / reject |
| `N` | Cycle noise: none / some / noisy (`Shift+N` backwards) |
| `M` `F` `C` `H` `A` `I` | Toggle motion / field inhomogeneity / clipping / hardware / misc artifact / improper acquisition |
| `R` `P` `W` | Cycle region / plane / weight (`Shift` cycles backwards) |
| `T` or `/` | Type notes (`Enter` saves, `Esc` leaves the field) |
| `D` | Reset labels to the defaults |
| `←` / `Backspace` | Previous series (shows its saved labels for editing) |
| `→` / `S` | Skip without saving |
| `Tab` / `G` | Toggle grid of all slices ↔ single slice |
| `↑` `↓` / wheel | Change slice; click a tile to open it |
| Right-drag / `L` | Adjust window/level / reset it |

## Defaults

Labels start at: quality accept, noise none, all findings no. Region, plane and weight are
pre-filled from the header when possible (`ImageOrientationPatient` for plane;
BodyPartExamined/descriptions for region; description, then TE/TR/TI for weight),
falling back to lumbar / sagittal / other. If `--weight` is given it is the default
weight, and the header guess is highlighted when it disagrees.

## Database

- `series`: one row per series: header values (TE, TR, TI, flip angle, field
  strength, description, UIDs) and the header guesses (`guess_plane`,
  `guess_region`, `guess_weight`, `guess_weight_reason`).
- `labels`: one row per (series, labeler): the labels, notes, `expected_weight`
  (the `--weight` passed at runtime), and `seconds_spent`.

Comparing `labels.weight` with `expected_weight` or `series.guess_weight` gives the
error rate of the upstream weight classification or of the header heuristic.

## Adding label options

Label options live in `src/quality_labeler/schema.py`. A new flag also needs a
column in `db.py` and a bump of `SCHEMA_VERSION`; databases written with an
older version are rejected on open rather than being written to with the wrong
columns.

## Tests

```bash
uv run pytest
```
