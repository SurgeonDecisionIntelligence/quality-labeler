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
| `--view` | Which view each series opens in: `grid` (default) or `single`. |
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
| `Z` | Zoom: auto / 1× / 2× / 4× (`Shift+Z` backwards); drag to pan |
| `↑` `↓` / wheel | Change slice; click a tile to open it |
| Right-drag / `L` | Adjust window/level / reset it |

## Resolution

Pixel data is kept as float32 at full precision; only the final draw is 8-bit
grayscale, mapped through the current window, so window/level always re-renders
from the original values.

The single-slice view never draws below 1:1 — if a slice is larger than the
viewport it is shown at full resolution and panned by dragging, and when it is
magnified it uses nearest neighbour so noise and edges are not smoothed into
something prettier than the data. The grid is an overview and does scale tiles
down; it area-averages (rather than point-sampling) and the status line states
the scale, e.g. `tiles at 47% — Tab for full resolution`. Judge noise and fine
artifacts in the single-slice view; `--view single` makes that the default.

The panel also shows the geometry a quality judgement depends on, e.g.
`0.53 × 0.98 mm effective (0.43 mm grid) · 4 mm thick, 0.4 gap · acquired
416×224 → 512×512 (interpolated)`. "Interpolated" means the stored matrix is
larger than the acquired one (zero filling on the scanner), so the extra pixels
carry no extra information. The effective figure divides the field of view by
the *acquired* samples, which is what actually limits detail; the grid figure is
`PixelSpacing`, which only describes the reconstruction. They differ most in the
phase-encoding direction, so an apparently isotropic 0.43 mm series can really
be 0.53 × 0.98 mm.

`AcquisitionMatrix` is vendor-dependent and does not capture partial Fourier or
reconstruction filtering, so treat the effective figure as an upper bound on
detail, not an exact measure. The same fields are stored per series,
so label agreement can later be analysed against voxel size.

Note that a lossy remote-desktop codec can discard exactly the high-frequency
detail that noise labels depend on; use a lossless or near-lossless session.

## Defaults

Labels start at: quality accept, noise none, all findings no. Region, plane and weight are
pre-filled from the header when possible (`ImageOrientationPatient` for plane;
BodyPartExamined/descriptions for region; description, then TE/TR/TI for weight),
falling back to lumbar / sagittal / other. If `--weight` is given it is the default
weight, and the header guess is highlighted when it disagrees.

## Database

- `series`: one row per series: header values (TE, TR, TI, flip angle, field
  strength, description, UIDs), geometry (`pixel_spacing_row/column`,
  `slice_thickness`, `slice_spacing`, `rows`, `columns`, `acquired_rows`,
  `acquired_columns`, `interpolated`) and the header guesses (`guess_plane`,
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
