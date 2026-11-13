from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from properdocs.structure.files import Files
    from properdocs.structure.pages import Page

# The README is copied as the site's home page, docs/index.md, unchanged. Its links to other pages are written
# from the repository root, as docs/how_it_works.md, so they work on GitHub, and from the home page they're
# siblings, so the docs/ is dropped for the site.
README_PAGE = "index.md"
FROM_ROOT = "](docs/"


def on_page_markdown(markdown: str, page: Page, config: object, files: Files) -> str:
    """Properdocs hook, rewriting the home page's links to other pages for where it sits on the site"""
    if page.file.src_uri != README_PAGE:
        return markdown
    return markdown.replace(FROM_ROOT, "](")
