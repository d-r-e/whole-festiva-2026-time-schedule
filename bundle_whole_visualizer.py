#!/usr/bin/env python3
"""Embed a WHOLE SoundCloud CSV into the visualizer as one standalone HTML file."""

import argparse
import re
from pathlib import Path


MARKER = re.compile(r'<script id="embedded-csv" type="text/plain">.*?</script>', re.S)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, default=Path("whole_soundcloud_visualizer.html"))
    parser.add_argument("--csv", type=Path, default=Path("whole_soundcloud_artists.csv"))
    parser.add_argument("--output", type=Path, default=Path("whole_soundcloud_standalone.html"))
    args = parser.parse_args()

    html = args.html.read_text(encoding="utf-8")
    csv = args.csv.read_text(encoding="utf-8")
    # Prevent a CSV value from prematurely closing the data script element.
    csv = csv.replace("</script", "<\\/script")
    embedded = f'<script id="embedded-csv" type="text/plain">{csv}</script>'
    html = MARKER.sub(embedded, html) if MARKER.search(html) else html.replace("</head>", embedded + "</head>", 1)
    args.output.write_text(html, encoding="utf-8")
    print(f"wrote standalone visualizer: {args.output} ({len(csv):,} embedded CSV characters)")


if __name__ == "__main__":
    main()
