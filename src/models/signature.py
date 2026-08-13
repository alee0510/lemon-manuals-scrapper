from __future__ import annotations
from enum import Enum

class PageType(str, Enum):
    INDEX = "index"                                         # nav-list of sibling pages (img.folder-icon + a)
    HIERARCHICAL_SPEC_TABLE = "hierarchical_spec_table"     # thead/tbody, colspan/padding-indented outline
    FLAT_TABLE = "flat_table"                               # thead/tbody, rectangular rows (not yet seen — reserved)
    IMAGE_DESCRIPTION = "image_description"                 # img + caption (not yet seen — reserved)
    UNKNOWN = "unknown"