from __future__ import annotations
import posixpath
from urllib.parse import urlsplit, unquote

from src.models.path import CanonicalRef

def resolve_href(source_path: str, href: str) -> CanonicalRef | None:
    """
    Resolve an href relative to a source path.

    Args:
        source_path: The path of the current page.
        href: The href to resolve.

    Returns:
        A CanonicalRef object with the resolved path and fragment.
    """
    split = urlsplit(href)

    # Ignore absolute URLs
    if split.scheme or split.netloc:
        return None

    # Ignore empty paths and fragments
    if not split.path and not split.fragment:
        return None

    # if the fragment exists, we
    if not split.path:
        target_path = source_path
    else:
        target_dir = posixpath.dirname(source_path)
        target_path = posixpath.normpath(posixpath.join(target_dir, split.path))

    # Remove any ".." components
    while target_path.startswith("../"):
        target_path = target_path[3:]
    target_path = target_path.lstrip("/")

    # Decode the fragment
    fragment = unquote(split.fragment) if split.fragment else None
    return CanonicalRef(path=target_path, fragment=fragment)


def canonicalize_source_path(raw_path: str, site_root: str) -> str:
    """
    Canonicalize a raw path relative to a site root.

    Args:
        raw_path: The raw path to canonicalize.
        site_root: The root of the site.

    Returns:
        A string with the canonicalized path.
    """
    rel = posixpath.relpath(raw_path, site_root)
    return rel.replace("\\", "/")