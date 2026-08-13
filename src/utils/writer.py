"""
Writer: turns a dataset's SiteGraph into the on-disk output layout —

    <output_dir>/<dataset_name>/main.json
    <output_dir>/<dataset_name>/pages/<id>.json

Two responsibilities live here that don't belong in crawler.py or
extractor.py:

1. Re-parsing each node's HTML to run extract() — crawler.py discards the
   BeautifulSoup object once a node is built (by design, see its docstring:
   it's the cheap structural pass), so getting content requires a second
   read. For 50k-page datasets this is a real cost; see the note at the
   bottom of this file for how to avoid it later without changing
   crawler.py's contract.

2. Alias resolution — index.html and pages/1.html are confirmed identical
   content in this dataset (index.html's own breadcrumb links to
   pages/1.html, so crawler.py's BFS visits both as separate nodes). We
   don't want two JSON files with duplicate content; pages/1.html becomes
   an alias entry in main.json instead of its own pages/*.json file, and
   every reference to "1" elsewhere is rewritten to "index".
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src.utils.discover import DiscoveredDataset
from src.models.sites import SiteGraph, SiteNode
from src.models.content import PageContent
from src.utils.extractor import extract


# ---------------------------------------------------------------------------
# Manifest models — main.json shape. Deliberately graph-only, no content,
# so this file stays small even at 50k nodes (see crawler.py's own
# docstring on why a flat dict was chosen over a nested tree).
# ---------------------------------------------------------------------------

class ManifestNode(BaseModel):
    page_type: str
    title: str
    children: list[str] = Field(default_factory=list)
    parents: list[str] = Field(default_factory=list)

class ManifestBrokenLink(BaseModel):
    source_page: str
    href: str
    resolved_path: str

class DatasetManifest(BaseModel):
    dataset_name: str
    root: str = "index"
    aliases: dict[str, str] = Field(default_factory=dict)   # alias_id -> canonical_id
    nodes: dict[str, ManifestNode] = Field(default_factory=dict)
    broken_links: list[ManifestBrokenLink] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# id derivation — must match extractor.py's _resolve_target_id exactly, or
# graph ids and content ids drift apart.
# ---------------------------------------------------------------------------

def page_path_to_id(page_path: str) -> str:
    if page_path == "index.html":
        return "index"
    p = page_path
    if p.startswith("pages/"):
        p = p[len("pages/"):]
    if p.endswith(".html"):
        p = p[: -len(".html")]
    return p


# ---------------------------------------------------------------------------
# Pass 1 — parse every node's HTML, run extract(), key by id
# ---------------------------------------------------------------------------

def _build_content_map(dataset: DiscoveredDataset, graph: SiteGraph) -> dict[str, PageContent]:
    content_map: dict[str, PageContent] = {}

    for page_path, node in graph.nodes.items():
        file_path = dataset.root_dir / page_path
        soup = BeautifulSoup(file_path.read_text(encoding="utf-8", errors="replace"), "lxml")

        page_id = page_path_to_id(page_path)
        content_map[page_id] = extract(
            page_id=page_id,
            dataset_name=dataset.name,
            source_path=page_path,
            page_type=node.page_type,
            title=node.title,
            breadcrumbs=node.breadcrumbs,
            soup=soup,
        )

    return content_map


# ---------------------------------------------------------------------------
# Pass 2 — hash content bodies, collapse duplicates into aliases.
# Iterates in dict insertion order, which is BFS discovery order (crawler.py
# visits index.html before pages/1.html), so the first-seen id always wins
# as canonical — "index" beats "1", not the other way round.
# ---------------------------------------------------------------------------

def _hash_content(pc: PageContent) -> str:
    # Hash the content body only, not id/source_path/breadcrumbs — those
    # legitimately differ between index.html and pages/1.html even when
    # the substantive content is identical.
    payload = pc.content.model_dump_json()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def _resolve_aliases(content_map: dict[str, PageContent]) -> dict[str, str]:
    seen_hash_to_id: dict[str, str] = {}
    aliases: dict[str, str] = {}   # alias_id -> canonical_id

    for page_id, pc in content_map.items():
        h = _hash_content(pc)
        if h in seen_hash_to_id:
            aliases[page_id] = seen_hash_to_id[h]
        else:
            seen_hash_to_id[h] = page_id

    return aliases


# ---------------------------------------------------------------------------
# Pass 3 — rewrite every id reference (children/parents in the graph,
# target_id inside extracted content) through the alias map, so nothing
# downstream ever points at a dropped duplicate like "1".
# ---------------------------------------------------------------------------

def _canonical(page_id: str, aliases: dict[str, str]) -> str:
    return aliases.get(page_id, page_id)

def _remap_graph(graph: SiteGraph, aliases: dict[str, str]) -> dict[str, ManifestNode]:
    remapped: dict[str, ManifestNode] = {}

    for page_path, node in graph.nodes.items():
        page_id = page_path_to_id(page_path)
        canonical_id = _canonical(page_id, aliases)

        children = sorted({_canonical(page_path_to_id(c), aliases) for c in node.children})
        parents = sorted({_canonical(page_path_to_id(p), aliases) for p in node.parents})

        if canonical_id in remapped:
            # e.g. "1" (alias) and "index" (canonical) both had their own
            # SiteNode; merge children/parents rather than overwrite.
            existing = remapped[canonical_id]
            existing.children = sorted(set(existing.children) | set(children))
            existing.parents = sorted(set(existing.parents) | set(parents))
        else:
            remapped[canonical_id] = ManifestNode(
                page_type=node.page_type.value,
                title=node.title,
                children=children,
                parents=parents,
            )

    return remapped

def _remap_content(content_map: dict[str, PageContent], aliases: dict[str, str]) -> dict[str, PageContent]:
    """Drop alias entries (they don't get their own pages/<id>.json) and
    rewrite any target_id inside surviving content that pointed at one."""
    remapped: dict[str, PageContent] = {}

    for page_id, pc in content_map.items():
        if page_id in aliases:
            continue  # this page's content is written under its canonical id instead

        content = pc.content
        if content.kind == "index":
            for section in content.sections:
                for item in section.items:
                    if item.target_id is not None:
                        item.target_id = _canonical(item.target_id, aliases)
        elif content.kind == "table":
            for row in content.rows:
                row.links = {col: _canonical(tid, aliases) for col, tid in row.links.items()}

        remapped[page_id] = pc

    return remapped


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def write_dataset(output_dir: Path, dataset: DiscoveredDataset, graph: SiteGraph) -> Path:
    """
    Runs extraction + alias resolution for one dataset and writes:
        output_dir/<dataset.name>/main.json
        output_dir/<dataset.name>/pages/<id>.json

    Returns the dataset's output directory.
    """
    content_map = _build_content_map(dataset, graph)
    aliases = _resolve_aliases(content_map)

    manifest_nodes = _remap_graph(graph, aliases)
    final_content = _remap_content(content_map, aliases)

    manifest = DatasetManifest(
        dataset_name=dataset.name,
        root=_canonical("index", aliases),
        aliases=aliases,
        nodes=manifest_nodes,
        broken_links=[
            ManifestBrokenLink(
                source_page=_canonical(page_path_to_id(bl.source_page), aliases),
                href=bl.href,
                resolved_path=bl.resolved_path,
            )
            for bl in graph.broken_links
        ],
    )

    dataset_dir = output_dir / dataset.name
    pages_dir = dataset_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    (dataset_dir / "main.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    for page_id, pc in final_content.items():
        (pages_dir / f"{page_id}.json").write_text(
            pc.model_dump_json(indent=2), encoding="utf-8"
        )

    return dataset_dir