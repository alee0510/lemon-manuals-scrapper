# ---------------------------------------------------------------------------
# Manifest models — main.json shape. Deliberately graph-only, no content,
# so this file stays small even at 50k nodes.
# ---------------------------------------------------------------------------
from __future__ import annotations
from pydantic import BaseModel, Field

from src.models.graph import GraphNode, GraphEdge

class CollapsedLink(BaseModel):
    """Provenance for a pass-through page that was dropped and rewired
    straight to this node — e.g. {"id": "25280", "label": "Common Specs &
    Procedures"} recorded on node "31917"."""
    id: str
    label: str

class ManifestNode(BaseModel):
    page_type: str
    title: str
    children: list[str] = Field(default_factory=list)
    parents: list[str] = Field(default_factory=list)
    collapsed_via: list[CollapsedLink] = Field(default_factory=list)

class ManifestBrokenLink(BaseModel):
    source_page: str
    href: str
    resolved_path: str

class ManifestOutOfScopeLink(BaseModel):
    source_page: str
    href: str
    resolved_path: str

class DatasetManifest(BaseModel):
    dataset_name: str
    root: str
    manufacturer: str | None = None
    year: str | None = None
    model: str | None = None
    aliases: dict[str, str] = Field(default_factory=dict)
    nodes: dict[str, ManifestNode] = Field(default_factory=dict)
    broken_links: list[ManifestBrokenLink] = Field(default_factory=list)
    out_of_scope_links: list[ManifestOutOfScopeLink] = Field(default_factory=list)
    graph: "DatasetGraphSection" = Field(default_factory=lambda: DatasetGraphSection())

class DatasetGraphSection(BaseModel):
    """Same nodes/edges shape as the former standalone graph.json, just
    nested under main.json's `graph` key instead of written separately."""
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
