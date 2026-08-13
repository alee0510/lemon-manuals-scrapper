"""
Content extraction: given a parsed page + the page_type already decided by
signature.classify(), pull out the actual repair content into the
PageContent envelope (see models/content.py).

Deliberately a SEPARATE pass from crawler.py rather than folded into it —
crawler.py's job is purely graph/reachability (cheap, runs once per page no
matter how large the dataset gets); extraction is the heavier per-page work
and is dispatched by page_type, so it's easy to add a new PageType handler
without touching graph logic at all.
"""

from __future__ import annotations
from bs4 import BeautifulSoup, Tag

from src.models.signature import PageType
from src.models.content import (
    PageContent,
    PageContentBody,
    IndexContent,
    IndexSection,
    IndexItem,
    TableContent,
    TableRow,
    ImageDescriptionContent,
    ImageItem,
    UnknownContent,
)
from src.utils.path import resolve_href
from src.helper.attribute import _attr_str

# Same placeholder targets crawler.py ignores when building graph edges —
# kept in sync here so IndexItem.target_id doesn't resolve to noise like
# 404.html either.
IGNORED_TARGETS = {"404.html", "about.html"}


def extract(
    *,
    page_id: str,
    dataset_name: str,
    source_path: str,
    page_type: PageType,
    title: str,
    breadcrumbs: list,
    soup: BeautifulSoup,
) -> PageContent:
    """
    Build the full PageContent envelope for one page. Caller (the future
    writer/pipeline step) supplies the identity fields already computed by
    discover()/crawler() — this function only owns the `content` body.
    """
    main = soup.find("div", class_="main")
    body = _extract_body(main, page_type, source_path)

    return PageContent(
        id=page_id,
        dataset=dataset_name,
        source_path=source_path,
        page_type=page_type,
        title=title,
        breadcrumbs=breadcrumbs,
        content=body,
    )


def _extract_body(main: Tag | None, page_type: PageType, source_path: str) -> PageContentBody:
    if main is None:
        return UnknownContent(raw_text="")

    if page_type == PageType.INDEX:
        return _extract_index(main, source_path)

    if page_type in (PageType.FLAT_TABLE, PageType.HIERARCHICAL_SPEC_TABLE):
        table = main.find("table")
        if table is None:
            return UnknownContent(raw_text=main.get_text(" ", strip=True))
        return _extract_table(table, source_path)

    if page_type == PageType.IMAGE_DESCRIPTION:
        table = main.find("table")
        tbody = table.find("tbody") if table else None
        if tbody is None:
            return UnknownContent(raw_text=main.get_text(" ", strip=True))
        return _extract_image_description(tbody)

    # PageType.UNKNOWN, or anything else not yet handled
    return UnknownContent(raw_text=main.get_text(" ", strip=True))


# ---------------------------------------------------------------------------
# INDEX — e.g. index.html, pages/2.html, pages/3.html, pages/4.html
# ---------------------------------------------------------------------------

def _extract_index(main: Tag, source_path: str) -> IndexContent:
    sections: list[IndexSection] = []
    notes: list[str] = []

    for child in main.children:
        if not isinstance(child, Tag):
            continue

        if child.name == "ul":
            sections.append(_extract_index_section(child, source_path))
        elif child.name in ("h1",):
            continue  # title already captured separately via _extract_common in crawler
        else:
            text = child.get_text(" ", strip=True)
            if text:
                notes.append(text)

    # main.html often has free text as bare NavigableStrings between tags
    # (e.g. "This is a LEMON manual, retrieved in 2025.") rather than inside
    # a wrapping element — pick those up too.
    for child in main.children:
        if isinstance(child, Tag):
            continue
        text = str(child).strip()
        if text:
            notes.append(text)

    return IndexContent(sections=sections, notes=notes)


def _extract_index_section(ul: Tag, source_path: str) -> IndexSection:
    items: list[IndexItem] = []
    for li in ul.find_all("li", recursive=False):
        a = li.find("a")
        if a is None:
            continue

        href = _attr_str(a.get("href"))
        target_id = _resolve_target_id(source_path, href)

        icon_img = li.find("img", class_="folder-icon")
        icon = None
        if icon_img is not None:
            src = _attr_str(icon_img.get("src"))
            icon = src.rsplit("/", 1)[-1] if src else None

        items.append(IndexItem(
            label=a.get_text(strip=True),
            target_id=target_id,
            href=href,
            icon=icon,
        ))

    # Section name isn't in the <ul> itself on these sample pages (it lives
    # in a preceding heading/anchor, e.g. the "#Quick Lookups/..." breadcrumb
    # fragments on pages/25280.html) — left as None here. The writer step can
    # backfill `name` from breadcrumb fragments once target pages are known,
    # rather than guessing at extraction time.
    return IndexSection(name=None, items=items)


# ---------------------------------------------------------------------------
# TABLE — covers both FLAT_TABLE (pages/31879.html) and
# HIERARCHICAL_SPEC_TABLE (pages/110.html, pages/31917.html)
# ---------------------------------------------------------------------------

def _extract_table(table: Tag, source_path: str) -> TableContent:
    columns: list[str] = []
    thead = table.find("thead")
    if thead is not None:
        columns = [th.get_text(strip=True) for th in thead.find_all("th")]

    rows: list[TableRow] = []
    tbody = table.find("tbody")
    if tbody is not None:
        for tr in tbody.find_all("tr", recursive=False):
            rows.append(_extract_table_row(tr, source_path))

    return TableContent(columns=columns, rows=rows)


def _extract_table_row(tr: Tag, source_path: str) -> TableRow:
    tds = tr.find_all("td", recursive=False)

    # Same fingerprint signature.py uses to detect depth — reused here so
    # extraction and classification never disagree on what counts as an
    # indented / group-header row.
    is_group_header = len(tds) == 1 and tds[0].has_attr("colspan")
    depth = 1 if (is_group_header or _row_has_depth_signal(tds)) else 0

    cells: list[str] = []
    links: dict[int, str] = {}
    for i, td in enumerate(tds):
        cells.append(td.get_text(" ", strip=True))
        a = td.find("a", href=True)
        if a is not None:
            target_id = _resolve_target_id(source_path, _attr_str(a.get("href")))
            if target_id is not None:
                links[i] = target_id

    return TableRow(depth=depth, is_group_header=is_group_header, cells=cells, links=links)


def _row_has_depth_signal(tds: list[Tag]) -> bool:
    for td in tds:
        if td.has_attr("colspan"):
            return True
        if "padding-left" in _attr_str(td.get("style")):
            return True
    return False


# ---------------------------------------------------------------------------
# IMAGE_DESCRIPTION — pages/700.html, 826.html, 909.html
# ---------------------------------------------------------------------------

def _extract_image_description(tbody: Tag) -> ImageDescriptionContent:
    images: list[ImageItem] = []
    for holder in tbody.find_all("div", class_="imageHolder"):
        img = holder.find("img")
        if img is None:
            continue
        caption_el = holder.find("span", class_="imageCourtesyNote")
        images.append(ImageItem(
            src=_attr_str(img.get("src")),
            alt=_attr_str(img.get("alt")),
            caption=caption_el.get_text(strip=True) if caption_el else None,
        ))

    return ImageDescriptionContent(images=images)


# ---------------------------------------------------------------------------
# shared helper
# ---------------------------------------------------------------------------

def _resolve_target_id(source_path: str, href: str) -> str | None:
    """
    Resolve an href to the target page's id, using the SAME resolve_href
    logic crawler.py uses for graph edges, then strip the .html suffix and
    'pages/' prefix so extraction ids match the crawler's page_path-derived
    ids one-to-one.
    """
    href = _attr_str(href)
    if not href:
        return None

    ref = resolve_href(source_path, href)
    if ref is None:
        return None
    if ref.page_path in IGNORED_TARGETS:
        return None

    page_path = ref.page_path
    if page_path.startswith("pages/"):
        page_path = page_path[len("pages/"):]
    if page_path.endswith(".html"):
        page_path = page_path[: -len(".html")]

    return page_path or None