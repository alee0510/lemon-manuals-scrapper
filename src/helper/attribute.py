from bs4.element import AttributeValueList

def _attr_str(value: AttributeValueList | str | None, default: str = "") -> str:
    """
    Normalize a bs4 attribute value to a plain str. bs4 types Tag.get() as
    AttributeValueList | str | None because some attributes (e.g. class)
    can be multi-valued; href/src are always single-valued in practice on
    this dataset's markup, but the type checker can't know that statically.
    Mirrors the isinstance(href, list) guard crawler.py already uses in
    _extract_common for breadcrumb hrefs.
    """
    if value is None:
        return default
    if isinstance(value, list):
        return " ".join(value) if value else default
    return value