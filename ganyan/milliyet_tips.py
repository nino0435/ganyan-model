"""Pure HTML parsers and magic-byte detector for Milliyet daily racing tip images."""
from html.parser import HTMLParser
import json
import re
import urllib.parse

BASE_URL = "https://www.milliyet.com.tr/"
AUTHOR_URL = "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/"

_ARTICLE_SLUG = "altili-ganyanda-bugun-"
_TRAILING_ID_RE = re.compile(r"-(\d+)/?$")
_LD_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_LD_HEADLINE_RE = re.compile(r'"headline"\s*:\s*"([^"]+)"')


def _attrs_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for key, val in attrs:
        k = key.lower()
        v = val or ""
        if k == "class" and k in merged:
            merged[k] = f"{merged[k]} {v}".strip()
        elif k not in merged or v:
            merged[k] = v
    return merged


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = _attrs_dict(attrs).get("href", "").strip()
            if href:
                self.hrefs.append(href)


def parse_listing(html: str) -> list[dict]:
    """Extract unique 'altili-ganyanda-bugun-' links sorted by descending article_id."""
    if not html or not isinstance(html, str):
        return []
    parser = _ListingParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass

    seen_ids: set[int] = set()
    seen_urls: set[str] = set()
    items: list[dict] = []

    for href in parser.hrefs:
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        abs_url = urllib.parse.urljoin(BASE_URL, href)
        parts = urllib.parse.urlsplit(abs_url)
        if parts.scheme not in ("http", "https"):
            continue
        if _ARTICLE_SLUG not in parts.path:
            continue
        m = _TRAILING_ID_RE.search(parts.path)
        if not m:
            continue
        article_id = int(m.group(1))
        clean_url = urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, parts.query, "")
        )
        if article_id in seen_ids or clean_url in seen_urls:
            continue
        seen_ids.add(article_id)
        seen_urls.add(clean_url)
        items.append({"url": clean_url, "article_id": article_id})

    items.sort(key=lambda x: x["article_id"], reverse=True)
    return items


def _walk_ld_json(node, out: dict[str, str | None]) -> None:
    if isinstance(node, dict):
        pub = node.get("datePublished")
        if isinstance(pub, str) and pub.strip() and out["published"] is None:
            out["published"] = pub.strip()
        head = node.get("headline")
        if isinstance(head, str) and head.strip() and out["title"] is None:
            out["title"] = head.strip()
        graph = node.get("@graph")
        if isinstance(graph, list):
            for child in graph:
                _walk_ld_json(child, out)
    elif isinstance(node, list):
        for child in node:
            _walk_ld_json(child, out)


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_h1: str | None = None
        self.any_h1: str | None = None
        self.doc_title: str | None = None
        self.og_title: str | None = None
        self.meta_title: str | None = None
        self.meta_published: str | None = None
        self.ld_title: str | None = None
        self.ld_published: str | None = None
        self.image_url: str | None = None

        self._in_h1 = False
        self._h1_is_article = False
        self._h1_buf: list[str] = []

        self._in_title = False
        self._title_buf: list[str] = []

        self._in_ld_json = False
        self._ld_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = _attrs_dict(attrs)
        if tag == "h1":
            self._in_h1 = True
            self._h1_is_article = "article__title" in amap.get("class", "").split()
            self._h1_buf = []
        elif tag == "title":
            self._in_title = True
            self._title_buf = []
        elif tag == "script":
            stype = amap.get("type", "").split(";", 1)[0].strip().lower()
            if stype == "application/ld+json":
                self._in_ld_json = True
                self._ld_buf = []
        elif tag == "meta":
            content = amap.get("content", "").strip()
            if not content:
                return
            prop = amap.get("property", "").strip().lower()
            name = amap.get("name", "").strip().lower()
            if prop == "og:title" and self.og_title is None:
                self.og_title = content
            elif name == "title" and self.meta_title is None:
                self.meta_title = content
            if (name == "datepublished" or prop == "article:published_time") and self.meta_published is None:
                self.meta_published = content
        elif tag == "img" and self.image_url is None:
            if amap.get("data-inline-image", "").strip().lower() == "true":
                candidate = amap.get("data-src", "").strip() or amap.get("src", "").strip()
                if candidate:
                    self.image_url = urllib.parse.urljoin(BASE_URL, candidate)

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self._h1_buf.append(data)
        if self._in_title:
            self._title_buf.append(data)
        if self._in_ld_json:
            self._ld_buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._in_h1:
            text = " ".join("".join(self._h1_buf).split())
            if text:
                if self._h1_is_article and self.article_h1 is None:
                    self.article_h1 = text
                elif self.any_h1 is None:
                    self.any_h1 = text
            self._in_h1 = False
        elif tag == "title" and self._in_title:
            text = " ".join("".join(self._title_buf).split())
            if text and self.doc_title is None:
                self.doc_title = text
            self._in_title = False
        elif tag == "script" and self._in_ld_json:
            raw = "".join(self._ld_buf).strip()
            self._in_ld_json = False
            if raw:
                found: dict[str, str | None] = {"title": None, "published": None}
                try:
                    parsed = json.loads(raw)
                    _walk_ld_json(parsed, found)
                except Exception:
                    m_pub = _LD_DATE_RE.search(raw)
                    if m_pub:
                        found["published"] = m_pub.group(1).strip() or None
                    m_head = _LD_HEADLINE_RE.search(raw)
                    if m_head:
                        found["title"] = m_head.group(1).strip() or None
                if found["title"] and self.ld_title is None:
                    self.ld_title = found["title"]
                if found["published"] and self.ld_published is None:
                    self.ld_published = found["published"]


def parse_article(html: str) -> dict:
    """Extract title, published timestamp, and inline tip image URL from article HTML."""
    empty = {"title": None, "published": None, "image_url": None}
    if not html or not isinstance(html, str):
        return empty
    parser = _ArticleParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    title = (
        parser.article_h1
        or parser.ld_title
        or parser.og_title
        or parser.meta_title
        or parser.any_h1
        or parser.doc_title
    )
    published = parser.ld_published or parser.meta_published
    return {
        "title": title,
        "published": published,
        "image_url": parser.image_url,
    }


def image_ext(data: bytes) -> str | None:
    """Detect image extension from magic bytes: PNG -> 'png', JPEG -> 'jpg', else None."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return None
    head = bytes(data[:4])
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None
