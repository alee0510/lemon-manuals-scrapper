from __future__ import annotations
from pydantic import BaseModel, Field

class Breadcrumb(BaseModel):
    label: str
    href: str | None = None

class SiteNode(BaseModel):
    """
    One node in the SITE graph (not tree). page_path is the canonical id.
    children are stored as REFERENCES (page_path strings), not nested
    SiteNode objects — this is what prevents infinite duplication.
    """
    page_path: str # canonical id, e.g. "pages/19554.html"
    page_type: str
    title: str
    breadcrumbs: list[Breadcrumb] = Field(default_factory=list)
    childrens: list[str] = Field(default_factory=list)
    parents: list[str] = Field(default_factory=list)

class SiteGraph(BaseModel):
     """The full dataset: a flat map of every page, plus the entry point."""
     dataset_name: str
     root: str = "index.html"
     nodes: dict[str, SiteNode] = Field(default_factory=dict)