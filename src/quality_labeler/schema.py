"""Label definitions. Add or reorder options here; the UI and database follow."""

from dataclasses import dataclass, fields

# Bump when the label set or the stored series metadata changes, so an older
# database is rejected instead of being written to with mismatched columns.
SCHEMA_VERSION = 3

QUALITY = ("accept", "partially accept", "reject")
NOISE = ("none", "some", "noisy")
REGIONS = ("lumbar", "cervical", "thoracic")
PLANES = ("sagittal", "coronal", "axial")
WEIGHTS = ("T1", "T1+C", "T2", "PD", "STIR", "FLAIR", "T2*", "DWI", "other")


@dataclass(frozen=True)
class Flag:
    name: str  # database column / Labels attribute
    label: str  # UI text
    key: str  # keyboard shortcut


FLAGS = (
    Flag("motion", "Motion artifact", "M"),
    Flag("field_inhomogeneity", "Field inhomogeneity", "F"),
    Flag("clipping", "Clipping", "C"),
    Flag("hardware", "Hardware", "H"),
    Flag("misc_artifact", "Misc artifact", "A"),
    Flag("improper_acquisition", "Improper acquisition", "I"),
)

# Ordinal scales, shown as a row of radio buttons and cycled with one key.
SCALES = {"quality": QUALITY, "noise": NOISE}


@dataclass
class Labels:
    quality: str = "accept"
    noise: str = "none"
    motion: bool = False
    field_inhomogeneity: bool = False
    clipping: bool = False
    hardware: bool = False
    misc_artifact: bool = False
    improper_acquisition: bool = False
    region: str = "lumbar"
    plane: str = "sagittal"
    weight: str = "T2"
    notes: str = ""

    @classmethod
    def field_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]
