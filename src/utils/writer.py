from __future__ import annotations
import hashlib
from pathlib import Path
from bs4 import BeautifulSoup

from src.utils.discover import DiscoveredDataset
from src.models.sites import SiteGraph, SiteNode
from src.models.content import PageContent
from src.models.graph import GraphNode, GraphEdge, DatasetGraph
from src.models.writer import CollapsedLink, ManifestNode, ManifestBrokenLink, ManifestOutOfScopeLink, DatasetManifest , DatasetGraphSection
from src.utils.extractor import extract
from src.utils.crawler import crawler

_LABEL_BY_PAGE_TYPE = {
    "index": "Section",
    "hierarchical_spec_table": "Procedure",
    "flat_table": "DTCTable",
    "image_description": "ComponentDiagram",
    "unknown": "Page",
}

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
# Pass 2 — pass-through detection + transitive resolution.
# A pass-through is an INDEX page with exactly one link total and no notes.
# The crawl root is never eligible, even if it happens to match the shape.
# ---------------------------------------------------------------------------

def _find_passthroughs(content_map: dict[str, PageContent], root_id: str) -> dict[str, str]:
    """Returns {passthrough_id: direct_target_id} for single-hop redirects."""
    passthroughs: dict[str, str] = {}

    for page_id, pc in content_map.items():
        if page_id == root_id:
            continue

        content = pc.content
        if content.kind != "index":
            continue
        if content.notes:
            continue  # real accompanying text means it's not just a redirect

        items = [item for section in content.sections for item in section.items]
        if len(items) != 1:
            continue

        target = items[0].target_id
        if target is None or target == page_id:
            continue

        passthroughs[page_id] = target

    return passthroughs

def _resolve_transitive(passthroughs: dict[str, str]) -> dict[str, str]:
    """
    Follows passthrough -> passthrough -> ... chains to the first
    non-passthrough target. Cycle-guarded: a pathological A->B->A loop
    falls back to leaving the chain unresolved (mapped to itself) rather
    than looping forever.
    """
    resolved: dict[str, str] = {}

    for start in passthroughs:
        visited: set[str] = set()
        current = start
        while current in passthroughs and current not in visited:
            visited.add(current)
            current = passthroughs[current]

        if current in visited:
            # Cycle detected — bail out, don't collapse this chain at all.
            continue

        resolved[start] = current

    return resolved


# ---------------------------------------------------------------------------
# Pass 3 — content-hash alias detection, run AFTER passthrough removal so
# dropped pass-through nodes never get hashed in the first place.
# ---------------------------------------------------------------------------

def _hash_content(pc: PageContent) -> str:
    payload = pc.content.model_dump_json()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def _resolve_aliases(content_map: dict[str, PageContent]) -> dict[str, str]:
    seen_hash_to_id: dict[str, str] = {}
    aliases: dict[str, str] = {}

    for page_id, pc in content_map.items():
        h = _hash_content(pc)
        if h in seen_hash_to_id:
            aliases[page_id] = seen_hash_to_id[h]
        else:
            seen_hash_to_id[h] = page_id

    return aliases


# ---------------------------------------------------------------------------
# Unified canonicalization — redirects (pass-through collapses) and aliases
# (content duplicates) are semantically different (tracked separately in
# the manifest) but both need to be followed when rewriting ids. IDs are
# disjoint by construction (aliases are computed only over content that
# already excludes passthrough ids), so a flat merge is safe. A visited
# guard handles the rare case where a redirect's target itself later turns
# out to be an alias of something else.
# ---------------------------------------------------------------------------

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
# Pass 4 — rewrite the graph: drop collapsed/alias nodes, rewire every
# children/parents edge through the canonical resolver, attach
# collapsed_via provenance to surviving target nodes.
# ---------------------------------------------------------------------------

def _remap_graph(
    graph: SiteGraph,
    canonical,
    collapsed_labels: dict[str, str],   # passthrough_id -> its own title/label
) -> dict[str, ManifestNode]:
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
                page_type=node.page_type.value,
                title=node.title,
                children=children,
                parents=parents,
            )

    # Attach collapsed_via provenance: every passthrough id that resolved
    # to this node gets recorded here, using the passthrough's own title.
    for passthrough_id, label in collapsed_labels.items():
        target_id = canonical(passthrough_id)
        if target_id in remapped:
            remapped[target_id].collapsed_via.append(
                CollapsedLink(id=passthrough_id, label=label)
            )

    for node in remapped.values():
        node.collapsed_via.sort(key=lambda c: c.id)

    return remapped

def _remap_content(
    content_map: dict[str, PageContent],
    canonical,
    dropped_ids: set[str],   # passthrough ids + alias ids — excluded from output
) -> dict[str, PageContent]:
    remapped: dict[str, PageContent] = {}

    for page_id, pc in content_map.items():
        if page_id in dropped_ids:
            continue

        content = pc.content
        if content.kind == "index":
            for section in content.sections:
                for item in section.items:
                    if item.target_id is not None:
                        item.target_id = canonical(item.target_id)
        elif content.kind == "table":
            for row in content.rows:
                row.links = {col: canonical(tid) for col, tid in row.links.items()}

        remapped[page_id] = pc

    return remapped

# ---------------------------------------------------------------------------
# Pass 4 — build the graph structure using the manifest + content.
# ---------------------------------------------------------------------------

def build_graph(
    dataset: DiscoveredDataset,
    manifest: DatasetManifest,
    content_by_id: dict[str, PageContent],
) -> DatasetGraph:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    dataset_node_id = f"dataset:{dataset.name}"
    nodes.append(GraphNode(
        id=dataset_node_id,
        labels=["Dataset"],
        properties={
            "manufacturer": manifest.manufacturer,
            "year": manifest.year,
            "model": manifest.model,
        },
    ))
    edges.append(GraphEdge(from_id=dataset_node_id, to_id=manifest.root, type="HAS_TOC"))

    for page_id, mnode in manifest.nodes.items():
        label = _LABEL_BY_PAGE_TYPE.get(mnode.page_type, "Page")

        # A DTCTable node's actual codes get promoted below; the table
        # node itself still exists as a container, just without raw
        # table rows duplicated onto it as properties.
        nodes.append(GraphNode(
            id=page_id,
            labels=[label],
            properties={"title": mnode.title},
        ))

        # Structural containment: only Section (INDEX) pages get CONTAINS
        # edges to their children — that's genuine navigational hierarchy.
        # Non-Section pages' "children" (cross-links inside table cells,
        # etc.) become REFERENCES instead, since linking to a pinpoint
        # test from a DTC action isn't containment.
        edge_type = "CONTAINS" if label == "Section" else "REFERENCES"
        for child_id in mnode.children:
            edges.append(GraphEdge(from_id=page_id, to_id=child_id, type=edge_type))

        for collapsed in mnode.collapsed_via:
            edges.append(GraphEdge(
                from_id=page_id,
                to_id=page_id,
                type="REDIRECTED_FROM",
                properties={"via_id": collapsed.id, "via_label": collapsed.label},
            ))

    for alias_id, canonical_id in manifest.aliases.items():
        edges.append(GraphEdge(from_id=alias_id, to_id=canonical_id, type="SAME_AS"))

    # DTC code promotion — walk surviving page content, not the manifest,
    # since DTCTableContent lives on PageContent, not ManifestNode.
    for page_id, pc in content_by_id.items():
        if pc.content.kind != "dtc_table":
            continue
        for entry in pc.content.entries:
            dtc_node_id = f"dtc:{entry.code}"
            nodes.append(GraphNode(
                id=dtc_node_id,
                labels=["DTCCode"],
                properties={"code": entry.code, "description": entry.description},
            ))
            edges.append(GraphEdge(from_id=page_id, to_id=dtc_node_id, type="CONTAINS"))
            if entry.target_id is not None:
                edges.append(GraphEdge(
                    from_id=dtc_node_id,
                    to_id=entry.target_id,
                    type="DIAGNOSED_BY",
                    properties={"action_text": entry.action_text},
                ))

    return DatasetGraph(dataset_name=dataset.name, nodes=nodes, edges=edges)

def build_graph_section(
    dataset: DiscoveredDataset,
    manifest: DatasetManifest,
    content_by_id: dict[str, PageContent],
) -> DatasetGraphSection:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    dataset_node_id = f"dataset:{dataset.name}"
    nodes.append(GraphNode(
        id=dataset_node_id,
        labels=["Dataset"],
        properties={
            "manufacturer": manifest.manufacturer,
            "year": manifest.year,
            "model": manifest.model,
        },
    ))
    edges.append(GraphEdge(from_id=dataset_node_id, to_id=manifest.root, type="HAS_TOC"))

    for page_id, mnode in manifest.nodes.items():
        label = _LABEL_BY_PAGE_TYPE.get(mnode.page_type, "Page")
        nodes.append(GraphNode(id=page_id, labels=[label], properties={"title": mnode.title}))

        edge_type = "CONTAINS" if label == "Section" else "REFERENCES"
        for child_id in mnode.children:
            edges.append(GraphEdge(from_id=page_id, to_id=child_id, type=edge_type))

        # Synthetic, non-traversable node per collapsed pass-through —
        # e.g. "collapsed:25280" for the "Common Specs & Procedures" hop
        # that got dropped and rewired straight to this node. Kept as its
        # own node (not a self-loop) so the redirect's own id/label are
        # first-class graph properties, queryable/traversable like any
        # other node, rather than metadata buried on an edge with no
        # distinct "from".
        for collapsed in mnode.collapsed_via:
            synthetic_id = f"collapsed:{collapsed.id}"
            nodes.append(GraphNode(
                id=synthetic_id,
                labels=["CollapsedRedirect"],
                properties={"original_id": collapsed.id, "label": collapsed.label},
            ))
            edges.append(GraphEdge(
                from_id=synthetic_id,
                to_id=page_id,
                type="REDIRECTED_FROM",
            ))

    for alias_id, canonical_id in manifest.aliases.items():
        edges.append(GraphEdge(from_id=alias_id, to_id=canonical_id, type="SAME_AS"))

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

def _crawl_and_extract(dataset: DiscoveredDataset, entry_point: str = "pages/2.html") -> tuple[SiteGraph, dict[str, PageContent]]:
    """
    Single-parse pipeline: runs crawler() with an on_node_parsed callback
    that extracts content inline, using the same soup the crawl already
    built, instead of writer.py re-reading and re-parsing every file
    afterward. Replaces the old two-pass (crawl, then separately
    _build_content_map) approach.
    """
    content_map: dict[str, PageContent] = {}

    def _on_node_parsed(page_path: str, node: SiteNode, soup: BeautifulSoup) -> None:
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

    graph = crawler(dataset, entry_point=entry_point, on_node_parsed=_on_node_parsed)
    return graph, content_map

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def write_dataset(output_dir: Path, dataset: DiscoveredDataset, graph: SiteGraph, content_map: dict[str, PageContent]) -> Path:
    """
    Runs pass-through collapsing + alias resolution for one dataset and
    writes main.json + pages/<id>.json. content_map is now supplied by
    the caller (via _crawl_and_extract) instead of built here, so this
    function no longer re-parses HTML at all.
    """
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

    manifest = DatasetManifest(
        dataset_name=dataset.name,
        root=root_canonical,
        manufacturer=graph.metadata.manufacturer,
        year=graph.metadata.year,
        model=graph.metadata.model,
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
    )
    manifest.graph = build_graph_section(dataset, manifest, final_content)

    dataset_dir = output_dir / dataset.name
    pages_dir = dataset_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    (dataset_dir / "main.json").write_text(manifest.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    for page_id, pc in final_content.items():
        (pages_dir / f"{page_id}.json").write_text(pc.model_dump_json(indent=2), encoding="utf-8")

    return dataset_dir

def is_dataset_already_written(output_dir: Path, dataset: DiscoveredDataset) -> bool:
    """Resumability check: a dataset is considered done if its main.json
    already exists. Doesn't validate contents — a partially-written
    main.json (e.g. process killed mid-write) would be wrongly treated as
    complete; the write above isn't atomic yet, worth flagging if that's
    a real risk in your environment."""
    return (output_dir / dataset.name / "main.json").is_file()