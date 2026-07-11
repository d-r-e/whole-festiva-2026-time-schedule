#!/usr/bin/env python3
"""Scrape SoundCloud links published on the official WHOLE lineup profiles.

The script deliberately does not guess usernames or search SoundCloud. It only
visits SoundCloud URLs present in the artist data embedded in WHOLE's lineup
page, then extracts public profile metadata from the linked SoundCloud page.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_LINEUP_URL = "https://www.wholefestival.com/lineup"
USER_AGENT = "WholeFestivalSoundCloudResearch/1.0 (+https://www.wholefestival.com/lineup)"
ARTIST_MARKER = '\\"_type\\":\\"artist\\"'
TITLE_RE = re.compile(r'\\"title\\":\\"(.*?)\\"')
TEXT_RE = re.compile(r'\\"text\\":\\"(.*?)\\"')
HREF_RE = re.compile(r'\\"href\\":\\"(https?://[^\"]*soundcloud[^\"]*)\\"', re.I)
ALL_HREF_RE = re.compile(r'\\"href\\":\\"(https?://[^\"]+)\\"', re.I)
CANONICAL_RE = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', re.I)
FOLLOWERS_RE = re.compile(r'"followers_count"\s*:\s*(\d+)')
GENRE_RE = re.compile(r'"genre"\s*:\s*"([^"]+)"')
DESCRIPTION_RE = re.compile(r'"description"\s*:\s*"((?:\\.|[^"\\])*)"')
AVATAR_RE = re.compile(r'"avatar_url"\s*:\s*"((?:\\.|[^"\\])*)"')
GENRE_WORDS = (
    "techno", "house", "trance", "electro", "ambient", "breakbeat", "breaks",
    "jungle", "drum and bass", "footwork", "gqom", "noise", "disco", "acid",
    "industrial", "ebm", "experimental", "bass", "garage", "grime", "dubstep",
    "hardstyle", "gabber", "funk", "soul", "pop", "r&b", "reggaeton", "dancehall",
    "baile funk", "afrobeat", "amapiano", "latin", "vogue", "ballroom", "ukg",
)


def fetch(url: str, timeout: int = 40) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def decode_rsc(value: str) -> str:
    """Decode the JSON-string escaping used by Next.js RSC payloads."""
    try:
        return json.loads('"' + value + '"')
    except json.JSONDecodeError:
        return value.replace('\\u0026', '&').replace('\\u003d', '=').replace('\\/', '/')


def clean_url(url: str) -> str:
    url = decode_rsc(html.unescape(url)).replace('\\t', '').strip()
    return url


def parse_lineup(page: str, lineup_url: str) -> list[dict[str, Any]]:
    """Parse artist cards from the embedded lineup data, including no-link cards."""
    page = html.unescape(page)
    parts = page.split(ARTIST_MARKER)[1:]
    artists: list[dict[str, Any]] = []
    for part in parts:
        titles = [decode_rsc(x) for x in TITLE_RE.findall(part)]
        if not titles:
            continue
        name = titles[-1].strip()
        descriptions = [decode_rsc(x).strip() for x in TEXT_RE.findall(part)]
        descriptions = [x for x in descriptions if x]
        links = []
        for raw in HREF_RE.findall(part):
            url = clean_url(raw)
            if url not in links:
                links.append(url)
        related_links = []
        for raw in ALL_HREF_RE.findall(part):
            url = clean_url(raw)
            if url not in related_links:
                related_links.append(url)
        artists.append({
            "artist": name,
            "wholefestival_url": lineup_url,
            "wholefestival_description": " ".join(descriptions),
            "soundcloud_url": links[0] if links else "",
            "soundcloud_urls": ";".join(links),
            "wholefestival_links": ";".join(related_links),
        })
    return artists


def first_match(pattern: re.Pattern[str], page: str) -> str:
    match = pattern.search(page)
    return decode_rsc(match.group(1)) if match else ""


def scrape_soundcloud(row: dict[str, Any]) -> dict[str, Any]:
    url = row["soundcloud_url"]
    result = dict(row)
    result.update({
        "soundcloud_canonical_url": "",
        "soundcloud_followers": "",
        "soundcloud_description": "",
        "soundcloud_avatar_url": "",
        "genres": "",
        "scrape_status": "no_soundcloud_link" if not url else "pending",
    })
    if not url:
        return result
    try:
        page = fetch(url)
        canonical = CANONICAL_RE.search(page)
        genres = []
        for genre in GENRE_RE.findall(page):
            genre = decode_rsc(genre).strip()
            if genre and genre not in genres:
                genres.append(genre)
        result.update({
            "soundcloud_canonical_url": html.unescape(canonical.group(1)) if canonical else url,
            "soundcloud_followers": first_match(FOLLOWERS_RE, page),
            "soundcloud_description": first_match(DESCRIPTION_RE, page),
            "soundcloud_avatar_url": first_match(AVATAR_RE, page),
            "genres": "; ".join(genres[:8]),
            "scrape_status": "ok",
        })
    except Exception as exc:  # keep one unavailable profile from stopping the run
        result["scrape_status"] = f"error: {type(exc).__name__}"
    return result


def infer_genres(row: dict[str, Any]) -> str:
    """Use genre words in the official Whole biography when SoundCloud has none."""
    if row.get("genres"):
        return row["genres"]
    text = row.get("wholefestival_description", "").lower()
    return "; ".join(word for word in GENRE_WORDS if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineup-url", default=DEFAULT_LINEUP_URL)
    parser.add_argument("--output", type=Path, default=Path("whole_soundcloud_artists.csv"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="Only scrape the first N cards (for testing).")
    args = parser.parse_args()

    lineup_page = fetch(args.lineup_url)
    rows = parse_lineup(lineup_page, args.lineup_url)
    if args.limit:
        rows = rows[: args.limit]

    scraped: list[dict[str, Any]] = [None] * len(rows)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(scrape_soundcloud, row): index for index, row in enumerate(rows)}
        for future in as_completed(futures):
            scraped[futures[future]] = future.result()
            time.sleep(0.05)

    fieldnames = [
        "artist", "wholefestival_url", "wholefestival_description", "soundcloud_url",
        "soundcloud_urls", "wholefestival_links",
        "soundcloud_canonical_url", "soundcloud_followers",
        "soundcloud_description", "soundcloud_avatar_url", "genres", "scrape_status", "scraped_at",
    ]
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in scraped:
            row["genres"] = infer_genres(row)
            row["scraped_at"] = scraped_at
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    linked = sum(bool(row["soundcloud_url"]) for row in rows)
    print(f"wrote {len(scraped)} lineup artists ({linked} with a WHOLE-published SoundCloud link) to {args.output}")


if __name__ == "__main__":
    main()
