from __future__ import annotations
from collections import deque
from typing import Callable
from bs4 import BeautifulSoup

from src.utils.discover import DiscoveredDataset
from src.models.sites import (
    BrokenLink,
    OutOfScopeLink,
    DatasetMetadata,
    SiteGraph,
    SiteNode,
)
from src.utils.path import resolve_href
from src.utils.signature import classify

ENTRY_POINT = "pages/2.html"
NOISE_TARGETS = {"404.html", "about.html"}
OUT_OF_SCOPE_TARGETS = {"index.html", "pages/1.html", "pages/3.html", "pages/4.html"}

# Called once per newly-parsed node, right after it's added to `nodes`,
# with the SAME soup object the crawler already built — lets a caller
# (writer.py) run content extraction inline instead of re-parsing the
# file a second time later. Optional: passing None preserves the
# original crawl-only behavior exactly.
OnNodeParsed = Callable[[str, SiteNode, BeautifulSoup], None]

def crawler(
    dataset: DiscoveredDataset,
    entry_point: str = ENTRY_POINT,
    on_node_parsed: OnNodeParsed | None = None,
) -> SiteGraph:
    nodes: dict[str, SiteNode] = {}
    broken_links: list[BrokenLink] = []
    out_of_scope_links: list[OutOfScopeLink] = []
    seen_out_of_scope: set[tuple[str, str]] = set()

    metadata = _extract_metadata(dataset)

    queue: deque[tuple[str, str | None]] = deque([(entry_point, None)])

    while queue:
        page_path, discovered_from = queue.popleft()

        if page_path in nodes:
            if discovered_from and discovered_from not in nodes[page_path].parents:
                nodes[page_path].parents.append(discovered_from)
            continue

        file_path = dataset.root_dir / page_path
        if not file_path.is_file():
            broken_links.append(BrokenLink(
                source_page=discovered_from or entry_point,
                href=page_path,
                resolved_path=page_path,
            ))
            continue

        soup = BeautifulSoup(file_path.read_text(encoding="utf-8", errors="replace"), "lxml")
        page_type = classify(soup)
        title = _extract_common(soup)

        node = SiteNode(
            page_path=page_path,
            page_type=page_type,
            title=title,
            parents=[discovered_from] if discovered_from else [],
        )
        nodes[page_path] = node

        if on_node_parsed is not None:
            on_node_parsed(page_path, node, soup)

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not isinstance(href, str):
                continue
            ref = resolve_href(page_path, href)
            if ref is None:
                continue
            if ref.page_path in NOISE_TARGETS:
                continue
            if ref.page_path in OUT_OF_SCOPE_TARGETS:
                key = (page_path, ref.page_path)
                if key not in seen_out_of_scope:
                    seen_out_of_scope.add(key)
                    out_of_scope_links.append(OutOfScopeLink(
                        source_page=page_path, href=href, resolved_path=ref.page_path,
                    ))
                continue
            if ref.page_path == page_path:
                continue
            if ref.page_path not in node.children:
                node.children.append(ref.page_path)
            queue.append((ref.page_path, page_path))

    return SiteGraph(
        dataset_name=dataset.name,
        root=entry_point,
        metadata=metadata,
        nodes=nodes,
        broken_links=broken_links,
        out_of_scope_links=out_of_scope_links,
    )

def _extract_metadata(dataset: DiscoveredDataset) -> DatasetMetadata:
    index_path = dataset.root_dir / "index.html"
    if not index_path.is_file():
        return DatasetMetadata()
    soup = BeautifulSoup(index_path.read_text(encoding="utf-8", errors="replace"), "lxml")
    header = soup.find("div", class_="header")
    if header is None:
        return DatasetMetadata()
    crumbs = header.find_all("a", class_="breadcrumb-part")
    labels = [c.get_text(strip=True) for c in crumbs]
    return DatasetMetadata(
        manufacturer=labels[1] if len(labels) > 1 else None,
        year=labels[2] if len(labels) > 2 else None,
        model=labels[3] if len(labels) > 3 else None,
    )

def _extract_common(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""