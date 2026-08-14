"""
BFS crawl of one dataset, starting at pages/2.html (Repair and Diagnosis —
the section this project scopes to; see project context). index.html /
pages/1.html (model root, duplicate content) and pages/3.html (same tree
flattened to one page) and pages/4.html (Labor Times, a sibling section)
are all out of scope by design, not by accident — see OUT_OF_SCOPE_TARGETS.

Design decisions worth calling out (see conversation history for the
reasoning behind each):

1. `nodes` is a flat dict keyed by canonical page_path — not a nested
   tree — because the same page can be (and demonstrably is, in this
   dataset — pages/19554.html) reachable from more than one parent. A
   flat dict + a `visited` check is what makes a diamond or a true cycle
   terminate instead of infinitely re-expanding.

2. A page is only ever read/parsed/classified ONCE (the `if page_path in
   nodes` guard at the top of the loop). Every subsequent discovery of an
   already-visited page just appends a parent backlink and moves on.

3. Missing target files are NOT fatal. A 50k-page scraped mirror will
   have dead links; we record them in `broken_links` and keep going,
   rather than letting one bad href kill the whole dataset run.

4. NOISE_TARGETS special-cases the site's own placeholder links (404.html,
   about.html) — these never resolve to real content, so they're dropped
   silently, same as before.

5. OUT_OF_SCOPE_TARGETS are real, existing pages that are deliberately
   NOT part of this project's scope (the model-root duplicate and the
   sibling Labor Times section). Unlike NOISE_TARGETS, these are worth
   knowing about — recorded in `out_of_scope_links`, not traversed.
"""

from __future__ import annotations
from collections import deque
from pathlib import Path
from bs4 import BeautifulSoup

from src.utils.discover import DiscoveredDataset
from src.models.sites import (
    Breadcrumb,
    BrokenLink,
    OutOfScopeLink,
    DatasetMetadata,
    SiteGraph,
    SiteNode,
)
from src.utils.path import resolve_href
from src.utils.signature import classify

ENTRY_POINT = "pages/2.html"

# Placeholder links that never resolve to real content — dropped silently,
# not tracked anywhere.
NOISE_TARGETS = {"404.html", "about.html"}

# Real pages that exist on disk but are outside this project's scope
# (model-root duplicate + sibling Labor Times section). Not traversed;
# recorded in out_of_scope_links so the signal isn't silently lost.
OUT_OF_SCOPE_TARGETS = {"index.html", "pages/1.html", "pages/3.html", "pages/4.html"}

def crawler(dataset: DiscoveredDataset, entry_point: str = ENTRY_POINT) -> SiteGraph:
    nodes: dict[str, SiteNode] = {}
    broken_links: list[BrokenLink] = []
    out_of_scope_links: list[OutOfScopeLink] = []
    seen_out_of_scope: set[tuple[str, str]] = set()  # (source_page, resolved_path) dedupe

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
        title, breadcrumbs = _extract_common(soup)

        node = SiteNode(
            page_path=page_path,
            page_type=page_type,
            title=title,
            breadcrumbs=breadcrumbs,
            parents=[discovered_from] if discovered_from else [],
        )
        nodes[page_path] = node

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
                        source_page=page_path,
                        href=href,
                        resolved_path=ref.page_path,
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
    """
    One cheap read of index.html's breadcrumb to pull manufacturer/year/
    model. Crumb shape is consistently:
        Home(→404) >> Brand(→404) >> Year(→404) >> Model(→pages/1.html) >> ...
    so positions 1/2/3 (0-indexed) are manufacturer/year/model, regardless
    of how many crumbs follow on deeper pages.
    """
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

def _extract_common(soup: BeautifulSoup) -> tuple[str, list[Breadcrumb]]:
    """Title + breadcrumbs are structurally identical across every page
    type we've seen so far (same header markup on index pages and table
    pages alike), so this is extracted once here rather than duplicated
    inside every type-specific extractor."""
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    breadcrumbs: list[Breadcrumb] = []
    header = soup.find("div", class_="header")
    if header:
        for a in header.find_all("a", class_="breadcrumb-part"):
            href = a.get("href")
            if isinstance(href, list):
                href = " ".join(href)
            breadcrumbs.append(Breadcrumb(label=a.get_text(strip=True), href=href))

    return title, breadcrumbs