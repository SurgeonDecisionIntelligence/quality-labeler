"""Label definitions. Add or reorder options here; the UI and database follow."""

from dataclasses import dataclass, fields

# Bump when the label set or the stored series metadata changes, so an older
# database is rejected instead of being written to with mismatched columns.
SCHEMA_VERSION = 4

REGIONS = ("lumbar", "cervical", "thoracic", "other")
PLANES = ("sagittal", "coronal", "axial")
WEIGHTS = ("T1", "T1+C", "T2", "PD", "STIR", "FLAIR", "T2*", "DWI", "other")


@dataclass(frozen=True)
class Scale:
    """An ordinal label. 1 is always the clean end: best quality, no artifact."""

    name: str  # database column / Labels attribute
    label: str  # UI text
    key: str  # keyboard shortcut, cycles upwards (Shift cycles back)
    values: tuple[int, ...]


@dataclass(frozen=True)
class Flag:
    """A yes/no label."""

    name: str
    label: str
    key: str


QUALITY_VALUES = (1, 2, 3, 4, 5)
GRADE_VALUES = (1, 2, 3)

QUALITY = Scale("quality", "Quality", "Q", QUALITY_VALUES)

# Graded findings, shown as one compact 1-2-3 row each.
GRADES = (
    Scale("noise", "Noise", "N", GRADE_VALUES),
    Scale("motion", "Motion artifact", "M", GRADE_VALUES),
    Scale("field_inhomogeneity", "Field inhomogeneity", "F", GRADE_VALUES),
    Scale("clipping", "Clipping", "C", GRADE_VALUES),
    Scale("hardware", "Hardware", "H", GRADE_VALUES),
    Scale("misc_artifact", "Misc artifact", "A", GRADE_VALUES),
)

SCALES = (QUALITY, *GRADES)

FLAGS = (
    Flag("improper_acquisition", "Improper acquisition", "I"),
    Flag("fat_suppression", "Fat suppression", "S"),
)


@dataclass
class Labels:
    quality: int = 1
    noise: int = 1
    motion: int = 1
    field_inhomogeneity: int = 1
    clipping: int = 1
    hardware: int = 1
    misc_artifact: int = 1
    improper_acquisition: bool = False
    fat_suppression: bool = False
    region: str = "lumbar"
    plane: str = "sagittal"
    weight: str = "T2"
    notes: str = ""

    @classmethod
    def field_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]
