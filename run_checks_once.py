from db import list_links_to_check, record_check
from doda_check import fetch_status


def main():
    links = list_links_to_check()
    print(f"Checking {len(links)} link(s)...")
    for l in links:
        url = (l["url"] or "").strip()
        link_id = l["id"]
        status = fetch_status(url)
        record_check(link_id=link_id, url=url, status=status)
        print(link_id, status.get("label"), status.get("matchedPhrase"), "CLEARED" if status.get("is_clear") else "")


if __name__ == "__main__":
    main()
