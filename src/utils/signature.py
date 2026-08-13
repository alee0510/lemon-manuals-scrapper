"""
Page classification: given a parsed page, decide which extractor should
handle it. Deliberately pure — takes a BeautifulSoup object, returns an
enum value, does zero file I/O and zero href resolution. This is what
makes it cheap to unit-test in isolation against golden HTML fixtures.
"""

from __future__ import annotations
from bs4 import BeautifulSoup

from src.models.signature import PageType

def classify(soup: BeautifulSoup) -> PageType:
    main = soup.find("div", class_="main")
    if main is None:
        return PageType.UNKNOWN

    table = main.find("table")
    if table is not None:
        return _classify_table(table)

    if _looks_like_index(main):
        return PageType.INDEX

    return PageType.UNKNOWN

def _classify_table(table) -> PageType:
    thead = table.find("thead")
    tbody = table.find("tbody")
    if thead is None or tbody is None:
        return PageType.UNKNOWN

    rows = tbody.find_all("tr", recursive=False)
    if not rows:
        return PageType.UNKNOWN

    indented = sum(1 for tr in rows if _row_has_depth_signal(tr))
    # Majority of rows carrying a colspan or padding-left depth signal is
    # the fingerprint of the indented-outline pattern from pages/31917.html.
    # A genuine rectangular table would have ~0% of rows matching this.
    if indented / len(rows) > 0.5:
        return PageType.HIERARCHICAL_SPEC_TABLE

    return PageType.FLAT_TABLE

def _row_has_depth_signal(tr) -> bool:
    for td in tr.find_all("td", recursive=False):
        if td.has_attr("colspan"):
            return True
        style = td.get("style", "")
        if "padding-left" in style:
            return True
    return False

def _looks_like_index(main) -> bool:
    """
    Matches the pattern from index.html / pages/1.html: a <ul> whose <li>
    children pair a folder-icon <img> with a link, e.g.:
        <li><img class='folder-icon' src='...'><a href='...'>Label</a></li>
    """
    for ul in main.find_all("ul", recursive=False):
        for li in ul.find_all("li", recursive=False):
            if li.find("img", class_="folder-icon") and li.find("a"):
                return True
    return False