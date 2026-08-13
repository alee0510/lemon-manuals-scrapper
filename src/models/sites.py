from __future__ import annotations
from pydantic import BaseModel, Field

from src.models.signature import PageType

class Breadcrumb(BaseModel):
    label: str
    href: str | None = None

class BrokenLink(BaseModel):
    """An href that resolved to a canonical page_path, but that path
    doesn't exist on disk. Recorded, not raised — a broken link in a
    50k-page scraped mirror shouldn't crash the whole dataset run."""
    source_page: str
    href: str
    resolved_path: str
    reason: str = "file_not_found"

class SiteNode(BaseModel):
    """One page in the dataset's link graph. children/parents are stored
    as page_path string references, NOT nested SiteNode objects — this is
    what keeps the structure a flat, cycle-safe graph rather than a tree
    that would infinitely re-expand on the first diamond/cycle."""
    page_path: str
    page_type: PageType
    title: str
    breadcrumbs: list[Breadcrumb] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    parents: list[str] = Field(default_factory=list)

class SiteGraph(BaseModel):
    dataset_name: str
    root: str = "index.html"
    nodes: dict[str, SiteNode] = Field(default_factory=dict)
    broken_links: list[BrokenLink] = Field(default_factory=list)