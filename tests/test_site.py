"""The docs site (site/, published to GitHub Pages): every page links only to pages, anchors and files that exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "site"
PAGES = sorted(SITE.glob("*.html"))


def _ids(page: Path) -> set[str]:
    return set(re.findall(r'id="([^"]+)"', page.read_text(encoding="utf-8")))


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_links_and_files_exist(page):
    html = page.read_text(encoding="utf-8")
    broken = []
    for ref in re.findall(r'(?:href|src)="([^"]+)"', html):
        if ref.startswith(("http://", "https://", "mailto:")) or ref == "/cogito-mem/":  # 404.html's <base>
            continue
        path, _, anchor = ref.partition("#")
        target = SITE / path if path else page
        if not target.exists() or (anchor and anchor not in _ids(target)):
            broken.append(ref)
    assert not broken, f"{page.name} links to missing targets: {broken}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_page_has_the_shared_frame(page):
    html = page.read_text(encoding="utf-8")
    assert '<meta name="viewport"' in html and "assets/style.css" in html and 'class="nav"' in html
    assert re.search(r"<title>[^<]+</title>", html)


def test_the_plugin_homepage_is_the_site():
    import json

    plugin = json.loads((SITE.parent / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin["homepage"] == "https://meridian21lab.github.io/cogito-mem/"
