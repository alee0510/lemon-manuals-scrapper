from __future__ import annotations
from enum import StrEnum
from pathlib import Path
from pydantic import BaseModel, Field

class SkipReason(StrEnum):
    """
    Why a URL was skipped during discovery.
    """
    NOT_A_DIRECTORY = "not_a_directory"
    MISSING_INDEX = "missing_index"
    HIDDEN_OR_SYSTEM = "hidden_or_system_entry" # e.g. .git, Trash, Cache, node_modules, .DS_Store, etc.

class DiscoveredDataset(BaseModel):
    """One valid dataset found under data_dir — a folder with an index.html."""
    name: str # folder name, used as the dataset id downstream
    root_dir: Path # absolute path to the dataset folder
    index_path: Path # absolute path to its index.html
    size_bytes: int | None = None # populated lazily/optionally

class SkippedEntry(BaseModel):
       """A top-level entry under data_dir that was NOT treated as a dataset."""
       name: str
       path: Path
       reason: SkipReason

class DiscoveryResult(BaseModel):
    """Full result of scanning data_dir once."""
    data_dir: Path
    datasets: list[DiscoveredDataset] = Field(default_factory=list)
    skipped: list[SkippedEntry] = Field(default_factory=list)

    @property
    def dataset_names(self) -> list[str]:
        """List of dataset names."""
        return [d.name for d in self.datasets]
