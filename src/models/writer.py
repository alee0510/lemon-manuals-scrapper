from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

from src.models.graph import GraphNode, GraphEdge
from src.models.content import SectionNode

class CollapsedLink(BaseModel):
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

class DatasetGraphSection(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# vehicle.json — 1:1 with a dataset, sections embedded (small, always
# fetched together with the vehicle record — see writer.py discussion).
# ---------------------------------------------------------------------------

class VehicleDocument(BaseModel):
    dataset_name: str
    type: Literal["vehicle"] = "vehicle"
    year: str | None = None
    make: str | None = None
    model: str | None = None
    source_path: str = "index.html"
    toc_id: str
    sections: list[SectionNode] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# graph.json — everything that scales with total crawled page count,
# kept out of vehicle.json so a basic vehicle lookup stays small.
# ---------------------------------------------------------------------------

class GraphDocument(BaseModel):
    dataset_name: str
    root: str
    aliases: dict[str, str] = Field(default_factory=dict)
    nodes: dict[str, ManifestNode] = Field(default_factory=dict)
    broken_links: list[ManifestBrokenLink] = Field(default_factory=list)
    out_of_scope_links: list[ManifestOutOfScopeLink] = Field(default_factory=list)
    graph: DatasetGraphSection = Field(default_factory=DatasetGraphSection)