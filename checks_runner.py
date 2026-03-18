from __future__ import annotations

from db import list_links_to_check, record_check
from doda_check import fetch_status


def run_checks_once() -> int:
    """Run a single pass of status checks for all known links.

    Returns: number of links processed.
    """
    links = list_links_to_check()
    for link in links:
        url = (link.get("url") or "").strip()
        link_id = link.get("id")
        if not url or link_id is None:
            continue
        status = fetch_status(url)
        record_check(link_id=link_id, url=url, status=status)
    return len(links)
