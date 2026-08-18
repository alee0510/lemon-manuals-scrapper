from __future__ import annotations
from pydantic import BaseModel, Field

from src.models.signature import PageType

class BrokenLink(BaseModel):
    """An href that resolved to a canonical page_path, but that path
    doesn't exist on disk. Recorded, not raised — a broken link in a
    50k-page scraped mirror shouldn't crash the whole dataset run."""
    source_page: str
    href: str
    resolved_path: str
    reason: str = "file_not_found"

class OutOfScopeLink(BaseModel):
    """A link that resolves to a real, existing page — but one outside
    the Repair & Diagnosis subtree we crawl from pages/2.html (e.g. a
    mid-procedure link to Labor Times). Tracked separately from
    BrokenLink because the target isn't missing/broken, it's just
    deliberately not traversed for this project's scope."""
    source_page: str
    href: str
    resolved_path: str

class DatasetMetadata(BaseModel):
    """Brand/year/model, parsed once off the breadcrumb — same on every
    page in the dataset, so this is a flat lookup, not a graph concern."""
    manufacturer: str | None = None
    year: str | None = None
    model: str | None = None

class SiteNode(BaseModel):
    """A node in the page graph, representing a single HTML page.
    """
    page_path: str
    page_type: PageType
    title: str
    children: list[str] = Field(default_factory=list)
    parents: list[str] = Field(default_factory=list)

class SiteGraph(BaseModel):
    """The full page-level graph for a single dataset: node
    -> children (directed edges).
    """
    dataset_name: str
    root: str = "pages/2.html"
    metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)
    nodes: dict[str, SiteNode] = Field(default_factory=dict)
    broken_links: list[BrokenLink] = Field(default_factory=list)
    out_of_scope_links: list[OutOfScopeLink] = Field(default_factory=list)