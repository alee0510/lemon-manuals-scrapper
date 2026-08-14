from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field

class GraphNode(BaseModel):
    id: str
    labels: list[str]
    properties: dict[str, Any] = Field(default_factory=dict)

class GraphEdge(BaseModel):
    from_id: str = Field(serialization_alias="from")
    to_id: str = Field(serialization_alias="to")
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)

class DatasetGraph(BaseModel):
    dataset_name: str
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)