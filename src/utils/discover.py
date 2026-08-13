from __future__ import annotations
from pathlib import Path

from src.models.discover import DiscoveryResult, SkipReason, SkippedEntry, DiscoveredDataset

_IGNORED_PREFIXES = (".", "_") # .DS_Store, .git, .gitkeep, __pycache__, etc.SkippedEntry

def discover(data_dir: Path) -> DiscoveryResult:
    """
    Scan `data_dir` for dataset folders. A valid dataset is any direct
    subdirectory of `data_dir` containing an `index.html` file.

    Does NOT read or parse any HTML — this step is purely filesystem
    inspection, kept intentionally cheap and side-effect-free so it can be
    re-run often (e.g. to print a summary) without cost.
    """
    if not data_dir.is_dir():
        raise NotADirectoryError(f"data_dir does not exist or is not a directory: {data_dir}")

    result = DiscoveryResult(data_dir=data_dir)

    for entry in sorted(data_dir.iterdir()):
        if entry.name.startswith(_IGNORED_PREFIXES):
            result.skipped.append(SkippedEntry(name=entry.name, path=entry, reason=SkipReason.HIDDEN_OR_SYSTEM))
            continue
        if not entry.is_dir():
            result.skipped.append(SkippedEntry(name=entry.name, path=entry, reason=SkipReason.NOT_A_DIRECTORY))
            continue

        index_path = entry / "index.html"
        if not index_path.is_file():
            result.skipped.append(SkippedEntry(name=entry.name, path=entry, reason=SkipReason.MISSING_INDEX))
            continue

        # At this point `entry` is a dataset folder with index.html
        result.datasets.append(DiscoveredDataset(
            name=entry.name,
            root_dir=entry,
            index_path=index_path,
            html_file_count=len(list(entry.rglob("*.html"))),
        ))

    return result
