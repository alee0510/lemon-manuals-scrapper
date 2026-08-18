from __future__ import annotations
from typing import Union, Literal
from pydantic import BaseModel, Field

from src.models.signature import PageType

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

# class IndexContent(BaseModel):
#     kind: Literal["index"] = "index"
#     sections: list[IndexSection] = Field(default_factory=list)
#     # Free text that sits in main but outside any <ul> (e.g. the
#     # "This is a LEMON manual, retrieved in 2025." line, or the
#     # "identical to the following model variants" note on index.html).
#     notes: list[str] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# DTC - Diagnostic Trouble Code
# ---------------------------------------------------------------------------

class DTCEntry(BaseModel):
    code: str                       # e.g. "P060D:00"
    description: str
    action_text: str | None = None  # e.g. "GO to Pinpoint Test DK"
    target_id: str | None = None    # resolved page id the Action column links to

class DTCTableContent(BaseModel):
    kind: Literal["dtc_table"] = "dtc_table"
    entries: list[DTCEntry] = Field(default_factory=list)



# ---------------------------------------------------------------------------
# Envelope — the shape every pages/<id>.json file has in common, regardless
# of page_type. Mirrors SiteNode's identity/breadcrumb fields so the two
# stay easy to cross-reference, but deliberately carries no children/parents
# (that stays in main.json / the graph manifest, not per-page docs).
# ---------------------------------------------------------------------------

class SectionNode(BaseModel):
    """
    One node in a page's navigation tree. TOC nodes are pure editorial
    groupings with no page of their own (source: <a name="..."> + a
    nested <ul>, e.g. "Quick Lookups", "DTC Index") — page_id is always
    None, children holds the nested nodes. PAGE nodes are real links
    (source: <a href="...">) — a leaf, children is always empty.

    Recursive by design: page2.html nests 4+ levels deep (Quick Lookups >
    DTC Index > 4 leaf links), while a page like the old pages/25280.html
    is just a depth-1 tree with one PAGE node — same model serves both.
    """
    label: str
    type: Literal["TOC", "PAGE"]
    page_id: str | None = None   # canonical page id, PAGE nodes only
    href: str | None = None      # original href, kept for traceability, PAGE nodes only
    icon: str | None = None
    children: list["SectionNode"] = Field(default_factory=list)

SectionNode.model_rebuild()

class IndexContent(BaseModel):
    kind: Literal["index"] = "index"
    sections: list[SectionNode] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

PageContentBody = Union[IndexContent, TableContent, DTCTableContent, ImageDescriptionContent, UnknownContent]

class PageContent(BaseModel):
    id: str                        # stable id from filename, e.g. "31917"; "index" for the root
    dataset: str                   # dataset.name, for when docs are flattened into one Mongo collection
    source_path: str               # e.g. "pages/31917.html", for traceability back to the source HTML
    page_type: PageType
    title: str
    content: PageContentBody