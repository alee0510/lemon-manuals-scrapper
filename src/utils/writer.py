"""
Writer: turns a dataset's SiteGraph + extracted content into the on-disk
output layout —

    <output_dir>/<dataset_name>/vehicle.json
    <output_dir>/<dataset_name>/graph.json
    <output_dir>/<dataset_name>/pages/<id>.json

Three passes before writing, same order as before and for the same
reasons: pass-through collapsing must run before content-hash aliasing
(collapsing changes what even gets hashed), and both must resolve to a
single canonical() function before any id gets written anywhere.
"""

from __future__ import annotations
import hashlib
from pathlib import Path

from bs4 import BeautifulSoup

from src.utils.discover import DiscoveredDataset
from src.models.sites import SiteGraph, SiteNode
from src.models.content import PageContent, SectionNode
from src.models.graph import GraphNode, GraphEdge
from src.models.writer import (
    VehicleDocument, GraphDocument, ManifestNode, ManifestBrokenLink,
    ManifestOutOfScopeLink, DatasetGraphSection, CollapsedLink,
)
from src.utils.extractor import extract
from src.utils.crawler import crawler

_LABEL_BY_PAGE_TYPE = {
    "index": "Section",
    "hierarchical_spec_table": "Procedure",
    "flat_table": "DTCTable",
    "image_description": "ComponentDiagram",
    "unknown": "Page",
}


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
# Single-parse crawl + extract (Task 4's on_node_parsed hook)
# ---------------------------------------------------------------------------

def _crawl_and_extract(dataset: DiscoveredDataset, entry_point: str = "pages/2.html") -> tuple[SiteGraph, dict[str, PageContent]]:
    content_map: dict[str, PageContent] = {}

    def _on_node_parsed(page_path: str, node: SiteNode, soup: BeautifulSoup) -> None:
        page_id = page_path_to_id(page_path)
        content_map[page_id] = extract(
            page_id=page_id, dataset_name=dataset.name, source_path=page_path,
            page_type=node.page_type, title=node.title, breadcrumbs=node.breadcrumbs, soup=soup,
        )

    graph = crawler(dataset, entry_point=entry_point, on_node_parsed=_on_node_parsed)
    return graph, content_map


# ---------------------------------------------------------------------------
# Pass-through detection — a passthrough is an INDEX page with exactly
# one top-level SectionNode, that node is a PAGE (not a TOC grouping),
# and no accompanying notes. Matches the old pages/25280.html shape:
# one <ul><li><a href=...></ul>, nothing else.
# ---------------------------------------------------------------------------

def _find_passthroughs(content_map: dict[str, PageContent], root_id: str) -> dict[str, str]:
    passthroughs: dict[str, str] = {}

    for page_id, pc in content_map.items():
        if page_id == root_id:
            continue
        content = pc.content
        if content.kind != "index":
            continue
        if content.notes:
            continue
        if len(content.sections) != 1:
            continue

        only = content.sections[0]
        if only.type != "PAGE" or only.page_id is None or only.page_id == page_id:
            continue

        passthroughs[page_id] = only.page_id

    return passthroughs

def _resolve_transitive(passthroughs: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for start in passthroughs:
        visited: set[str] = set()
        current = start
        while current in passthroughs and current not in visited:
            visited.add(current)
            current = passthroughs[current]
        if current in visited:
            continue
        resolved[start] = current
    return resolved


# ---------------------------------------------------------------------------
# Content-hash aliasing, run after collapsing.
# ---------------------------------------------------------------------------

def _hash_content(pc: PageContent) -> str:
    return hashlib.sha256(pc.content.model_dump_json().encode("utf-8")).hexdigest()

def _resolve_aliases(content_map: dict[str, PageContent]) -> dict[str, str]:
    seen: dict[str, str] = {}
    aliases: dict[str, str] = {}
    for page_id, pc in content_map.items():
        h = _hash_content(pc)
        if h in seen:
            aliases[page_id] = seen[h]
        else:
            seen[h] = page_id
    return aliases


def _build_canonical_resolver(redirects: dict[str, str], aliases: dict[str, str]):
    combined = {**redirects, **aliases}
    def canonical(page_id: str) -> str:
        current = page_id
        visited: set[str] = set()
        while current in combined and current not in visited:
            visited.add(current)
            current = combined[current]
        return current
    return canonical


# ---------------------------------------------------------------------------
# Rewrite graph nodes + content through the canonical resolver.
# ---------------------------------------------------------------------------

def _remap_graph(graph: SiteGraph, canonical, collapsed_labels: dict[str, str]) -> dict[str, ManifestNode]:
    remapped: dict[str, ManifestNode] = {}

    for page_path, node in graph.nodes.items():
        page_id = page_path_to_id(page_path)
        canonical_id = canonical(page_id)
        children = sorted({canonical(page_path_to_id(c)) for c in node.children})
        parents = sorted({canonical(page_path_to_id(p)) for p in node.parents})

        if canonical_id in remapped:
            existing = remapped[canonical_id]
            existing.children = sorted(set(existing.children) | set(children))
            existing.parents = sorted(set(existing.parents) | set(parents))
        else:
            remapped[canonical_id] = ManifestNode(
                page_type=node.page_type.value, title=node.title, children=children, parents=parents,
            )

    for passthrough_id, label in collapsed_labels.items():
        target_id = canonical(passthrough_id)
        if target_id in remapped:
            remapped[target_id].collapsed_via.append(CollapsedLink(id=passthrough_id, label=label))

    for node in remapped.values():
        node.collapsed_via.sort(key=lambda c: c.id)

    return remapped

def _remap_section_nodes(nodes: list[SectionNode], canonical) -> list[SectionNode]:
    for node in nodes:
        if node.page_id is not None:
            node.page_id = canonical(node.page_id)
        if node.children:
            node.children = _remap_section_nodes(node.children, canonical)
    return nodes

def _remap_content(content_map: dict[str, PageContent], canonical, dropped_ids: set[str]) -> dict[str, PageContent]:
    remapped: dict[str, PageContent] = {}

    for page_id, pc in content_map.items():
        if page_id in dropped_ids:
            continue

        content = pc.content
        if content.kind == "index":
            content.sections = _remap_section_nodes(content.sections, canonical)
        elif content.kind == "table":
            for row in content.rows:
                row.links = {col: canonical(tid) for col, tid in row.links.items()}
        elif content.kind == "dtc_table":
            # NOTE: this branch was missing before — DTCEntry.target_id
            # was never being canonicalized through collapses/aliases.
            # Fixed here.
            for entry in content.entries:
                if entry.target_id is not None:
                    entry.target_id = canonical(entry.target_id)

        remapped[page_id] = pc

    return remapped


# ---------------------------------------------------------------------------
# graph.json's typed nodes/edges — unchanged in substance from Task 3,
# just attached to GraphDocument instead of DatasetManifest.
# ---------------------------------------------------------------------------

def build_graph_section(dataset: DiscoveredDataset, dataset_meta, root_id: str,
                         manifest_nodes: dict[str, ManifestNode],
                         content_by_id: dict[str, PageContent]) -> DatasetGraphSection:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    dataset_node_id = f"dataset:{dataset.name}"
    nodes.append(GraphNode(
        id=dataset_node_id, labels=["Dataset"],
        properties={"manufacturer": dataset_meta.manufacturer, "year": dataset_meta.year, "model": dataset_meta.model},
    ))
    edges.append(GraphEdge(from_id=dataset_node_id, to_id=root_id, type="HAS_TOC"))

    for page_id, mnode in manifest_nodes.items():
        label = _LABEL_BY_PAGE_TYPE.get(mnode.page_type, "Page")
        nodes.append(GraphNode(id=page_id, labels=[label], properties={"title": mnode.title}))

        edge_type = "CONTAINS" if label == "Section" else "REFERENCES"
        for child_id in mnode.children:
            edges.append(GraphEdge(from_id=page_id, to_id=child_id, type=edge_type))

        for collapsed in mnode.collapsed_via:
            synthetic_id = f"collapsed:{collapsed.id}"
            nodes.append(GraphNode(
                id=synthetic_id, labels=["CollapsedRedirect"],
                properties={"original_id": collapsed.id, "label": collapsed.label},
            ))
            edges.append(GraphEdge(from_id=synthetic_id, to_id=page_id, type="REDIRECTED_FROM"))

    for page_id, pc in content_by_id.items():
        if pc.content.kind != "dtc_table":
            continue
        for entry in pc.content.entries:
            dtc_node_id = f"dtc:{entry.code}"
            nodes.append(GraphNode(
                id=dtc_node_id, labels=["DTCCode"],
                properties={"code": entry.code, "description": entry.description},
            ))
            edges.append(GraphEdge(from_id=page_id, to_id=dtc_node_id, type="CONTAINS"))
            if entry.target_id is not None:
                edges.append(GraphEdge(
                    from_id=dtc_node_id, to_id=entry.target_id, type="DIAGNOSED_BY",
                    properties={"action_text": entry.action_text},
                ))

    return DatasetGraphSection(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def write_dataset(output_dir: Path, dataset: DiscoveredDataset, graph: SiteGraph, content_map: dict[str, PageContent]) -> Path:
    root_id = page_path_to_id(graph.root)

    passthroughs = _find_passthroughs(content_map, root_id)
    redirects = _resolve_transitive(passthroughs)
    collapsed_labels = {pid: content_map[pid].title for pid in redirects}

    content_after_collapse = {pid: pc for pid, pc in content_map.items() if pid not in redirects}
    aliases = _resolve_aliases(content_after_collapse)

    canonical = _build_canonical_resolver(redirects, aliases)
    dropped_ids = set(redirects) | set(aliases)

    manifest_nodes = _remap_graph(graph, canonical, collapsed_labels)
    final_content = _remap_content(content_map, canonical, dropped_ids)
    root_canonical = canonical(root_id)

    # The root page's sections are lifted into vehicle.json and no longer
    # written as their own pages/<id>.json — that content now lives
    # entirely embedded in the vehicle document.
    root_content = final_content.pop(root_canonical, None)
    root_sections = root_content.content.sections if root_content is not None and root_content.content.kind == "index" else []

    graph_section = build_graph_section(dataset, graph.metadata, root_canonical, manifest_nodes, final_content)

    vehicle_doc = VehicleDocument(
        dataset_name=dataset.name,
        year=graph.metadata.year,
        make=graph.metadata.manufacturer,
        model=graph.metadata.model,
        toc_id=root_canonical,
        sections=root_sections,
    )

    graph_doc = GraphDocument(
        dataset_name=dataset.name,
        root=root_canonical,
        aliases=aliases,
        nodes=manifest_nodes,
        broken_links=[
            ManifestBrokenLink(source_page=canonical(page_path_to_id(bl.source_page)), href=bl.href, resolved_path=bl.resolved_path)
            for bl in graph.broken_links
        ],
        out_of_scope_links=[
            ManifestOutOfScopeLink(source_page=canonical(page_path_to_id(ol.source_page)), href=ol.href, resolved_path=ol.resolved_path)
            for ol in graph.out_of_scope_links
        ],
        graph=graph_section,
    )

    dataset_dir = output_dir / dataset.name
    pages_dir = dataset_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    (dataset_dir / "vehicle.json").write_text(vehicle_doc.model_dump_json(indent=2), encoding="utf-8")
    (dataset_dir / "graph.json").write_text(graph_doc.model_dump_json(indent=2, by_alias=True), encoding="utf-8")

    for page_id, pc in final_content.items():
        (pages_dir / f"{page_id}.json").write_text(pc.model_dump_json(indent=2), encoding="utf-8")

    return dataset_dir


def is_dataset_already_written(output_dir: Path, dataset: DiscoveredDataset) -> bool:
    return (output_dir / dataset.name / "vehicle.json").is_file()