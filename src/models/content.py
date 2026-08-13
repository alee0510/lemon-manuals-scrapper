from __future__ import annotations
from typing import Union, Literal
from pydantic import BaseModel, Field

from src.models.signature import PageType
from src.models.sites import Breadcrumb


# ---------------------------------------------------------------------------
# INDEX pages (index.html, pages/2.html, pages/3.html, pages/4.html, ...)
# One IndexSection per top-level <ul>, or per named-anchor grouping when a
# page mixes several <ul> blocks under different headings (as seen via the
# breadcrumb fragments like "#Quick Lookups/Common Specs & Procedures/").
# ---------------------------------------------------------------------------

class IndexItem(BaseModel):
    label: str
    target_id: str | None = None   # resolved page id (e.g. "31917"), None if broken/external
    href: str                      # original href, kept for traceability/debugging
    icon: str | None = None        # e.g. "wrench.svg", from the folder-icon <img src>

class IndexSection(BaseModel):
    name: str | None = None        # heading text / anchor name, None if page has no sub-sections
    items: list[IndexItem] = Field(default_factory=list)

class IndexContent(BaseModel):
    kind: Literal["index"] = "index"
    sections: list[IndexSection] = Field(default_factory=list)
    # Free text that sits in main but outside any <ul> (e.g. the
    # "This is a LEMON manual, retrieved in 2025." line, or the
    # "identical to the following model variants" note on index.html).
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# TABLE pages — covers both FLAT_TABLE (pages/31879.html) and
# HIERARCHICAL_SPEC_TABLE (pages/110.html, pages/31917.html). Same shape;
# `depth` / `is_group_header` are just 0 / False for every row on a flat
# table, so one model serves both page_types.
# ---------------------------------------------------------------------------

class TableRow(BaseModel):
    depth: int = 0                     # 0 = top-level row, >0 = indented under a group header
    is_group_header: bool = False      # True for colspan rows like "Combination Procedure: ..."
    cells: list[str] = Field(default_factory=list)
    # Populated only for cells that contained an <a href>, keyed by column
    # index, so link targets survive without polluting `cells` text.
    links: dict[int, str] = Field(default_factory=dict)

class TableContent(BaseModel):
    kind: Literal["table"] = "table"
    columns: list[str] = Field(default_factory=list)   # from <thead>; [] for thead-less tables
    rows: list[TableRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# IMAGE_DESCRIPTION pages (pages/700.html, 826.html, 909.html) — now
# correctly classified after the signature.py fix from the previous step.
# ---------------------------------------------------------------------------

class ImageItem(BaseModel):
    src: str
    alt: str | None = None
    caption: str | None = None   # from the imageCourtesyNote span

class ImageDescriptionContent(BaseModel):
    kind: Literal["image_description"] = "image_description"
    images: list[ImageItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# UNKNOWN — safety net so nothing silently disappears during extraction.
# ---------------------------------------------------------------------------

class UnknownContent(BaseModel):
    kind: Literal["unknown"] = "unknown"
    raw_text: str = ""


PageContentBody = Union[IndexContent, TableContent, ImageDescriptionContent, UnknownContent]


# ---------------------------------------------------------------------------
# Envelope — the shape every pages/<id>.json file has in common, regardless
# of page_type. Mirrors SiteNode's identity/breadcrumb fields so the two
# stay easy to cross-reference, but deliberately carries no children/parents
# (that stays in main.json / the graph manifest, not per-page docs).
# ---------------------------------------------------------------------------

class PageContent(BaseModel):
    id: str                        # stable id from filename, e.g. "31917"; "index" for the root
    dataset: str                   # dataset.name, for when docs are flattened into one Mongo collection
    source_path: str               # e.g. "pages/31917.html", for traceability back to the source HTML
    page_type: PageType
    title: str
    breadcrumbs: list[Breadcrumb] = Field(default_factory=list)
    content: PageContentBody