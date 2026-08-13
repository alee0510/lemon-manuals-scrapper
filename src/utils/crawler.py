"""
BFS crawl of one dataset, starting at index.html.

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

4. `IGNORED_TARGETS` special-cases the site's own placeholder link
   (404.html) so it doesn't pollute broken_links with noise you already
   know about and don't care to chase.
"""

from __future__ import annotations
from collections import deque
from bs4 import BeautifulSoup

from src.utils.discover import DiscoveredDataset
from src.models.sites import Breadcrumb, BrokenLink, SiteGraph, SiteNode
from src.utils.path import resolve_href
from src.utils.signature import classify

IGNORED_TARGETS = {"404.html", "about.html", "contact.html"}

def crawler(dataset: DiscoveredDataset) -> SiteGraph:
    nodes: dict[str, SiteNode] = {}
    broken_links: list[BrokenLink] = []

    # Each queue entry is (page_path_to_visit, discovered_from_page_path).
    queue: deque[tuple[str, str | None]] = deque([("index.html", None)])

    while queue:
        page_path, discovered_from = queue.popleft()
        # print(f"Page path: {page_path} - Discovered from: {discovered_from}")

        if page_path in nodes:
            # Already visited via a different parent — this is exactly
            # the pages/19554.html scenario. Record the extra edge and
            # move on; do NOT re-read/re-parse/re-classify the file.
            if discovered_from and discovered_from not in nodes[page_path].parents:
                nodes[page_path].parents.append(discovered_from)
            continue

        file_path = dataset.root_dir / page_path
        if not file_path.is_file():
            broken_links.append(BrokenLink(
                source_page=discovered_from or "index.html",
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
        # print(f"Page node: {node}")
        nodes[page_path] = node

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not isinstance(href, str):
                continue
            ref = resolve_href(page_path, href)
            if ref is None:
                continue
            if ref.page_path in IGNORED_TARGETS:
                continue
            if ref.page_path == page_path:
                # Self-link — e.g. the current page's own breadcrumb crumb
                # pointing at itself. Not a real traversal edge.
                continue
            if ref.page_path not in node.children:
                # A page can legitimately contain several <a> tags that
                # all resolve to the same target once fragments are
                # stripped (e.g. breadcrumb crumbs "Repair and Diagnosis"
                # and "Quick Lookups" both point at pages/2.html, just
                # with different #fragments). One edge per distinct
                # target is what the graph should record.
                node.children.append(ref.page_path)
            queue.append((ref.page_path, page_path))

    return SiteGraph(
        dataset_name=dataset.name,
        nodes=nodes,
        broken_links=broken_links,
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