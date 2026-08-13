from __future__ import annotations
from pydantic import BaseModel

class CanonicalRef(BaseModel):
    path: str
    fragment: str | None = None

    @property
    def id(self) -> str:
        """Return the canonical ID of the page."""
        return self.path if not self.fragment else f"{self.path}#{self.fragment}"

    @property
    def page_path(self) -> str:
        """Return the canonical path of the page."""
        return self.path