"""Label definitions. Add or reorder options here; the UI and database follow."""

from dataclasses import dataclass, fields

QUALITY = ("accept", "uncertain", "reject")
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
    Flag("noise", "Noise", "N"),
    Flag("field_inhomogeneity", "Field inhomogeneity", "F"),
    Flag("clipping", "Clipping", "C"),
    Flag("musculoskeletal", "Musculoskeletal", "K"),
    Flag("improper_acquisition", "Improper acquisition", "I"),
)


@dataclass
class Labels:
    quality: str = "accept"
    motion: bool = False
    noise: bool = False
    field_inhomogeneity: bool = False
    clipping: bool = False
    musculoskeletal: bool = False
    improper_acquisition: bool = False
    region: str = "lumbar"
    plane: str = "sagittal"
    weight: str = "T2"
    notes: str = ""

    @classmethod
    def field_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]
