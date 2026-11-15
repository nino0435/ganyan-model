"""Parse Sporx 'at-yarisi-hazir-kuponlar' daily tips HTML (stdlib only)."""
import codecs
import hashlib
from html.parser import HTMLParser
import json
import re

_ALTILI_BY_ID = {
    "tahmin_tilki": "fenomen_tilki",
    "tahmin_editor": "editorun_kuponu",
    "tahmin_hipodrom": "hipodrom_guzeli",
}
_AI_SLUGS = {"sprintmaster": "sprintmaster", "beygirbooster": "beygirbooster"}
_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_SKIP_TAGS = frozenset({"noscript", "script", "style", "template"})
_BLOCK_TAGS = frozenset({"div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})
_META_CHARSET_RE = re.compile(r'<meta\b[^>]*?charset\s*=\s*["\']?\s*([A-Za-z0-9._-]+)', re.IGNORECASE)
_AI_PICK_RE = re.compile(r"^(.+?)\s*\(\s*([^()]+?)\s+(\d{1,2})\s*\.\s*[kK](?:[oO]?[şŞsS][uU]?|[şŞsS])\.?\s*\)$")


def _decode_html(html_bytes_or_str):
    if isinstance(html_bytes_or_str, str):
        return html_bytes_or_str
    raw = bytes(html_bytes_or_str)
    if not raw:
        return ""
    m = _META_CHARSET_RE.search(raw[:8192].decode("ascii", errors="ignore"))
    if m:
        enc = m.group(1).strip()
        try:
            codecs.lookup(enc)
            return raw.decode(enc, errors="replace")
        except LookupError:
            pass
    return raw.decode("iso-8859-9", errors="replace")


class _Node:
    __slots__ = ("tag", "el_id", "cls", "parent", "parts")

    def __init__(self, tag, attrs=None, parent=None):
        a = attrs or {}
        self.tag = tag
        self.el_id = a.get("id", "").strip()
        self.cls = frozenset(a.get("class", "").split())
        self.parent = parent
        self.parts = []

    def children(self):
        return [p for p in self.parts if isinstance(p, _Node)]


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "br":
            self.stack[-1].parts.append("\n")
            return
        node = _Node(t, {k.lower(): (v or "") for k, v in attrs if k}, self.stack[-1])
        self.stack[-1].parts.append(node)
        if t not in _VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        t = tag.lower()
        if t not in _VOID_TAGS:
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i].tag == t:
                    del self.stack[i:]
                    break

    def handle_data(self, data):
        if data and not any(anc.tag in _SKIP_TAGS for anc in self.stack):
            self.stack[-1].parts.append(data)


def _collect_text(node, block_nl=False):
    buf = []

    def walk(n):
        if n.tag in _SKIP_TAGS:
            return
        sep = "\n" if block_nl and n.tag in _BLOCK_TAGS else ""
        if sep:
            buf.append(sep)
        for p in n.parts:
            walk(p) if isinstance(p, _Node) else buf.append(p)
        if sep:
            buf.append(sep)

    walk(node)
    raw = "".join(buf)
    if block_nl:
        return [c for ln in raw.split("\n") if (c := " ".join(ln.split()))]
    return " ".join(raw.split())


def _find(node, pred):
    out = [node] if pred(node) else []
    for ch in node.children():
        out.extend(_find(ch, pred))
    return out


def _parse_altili_card(tt_node, slug):
    texts = _collect_text(tt_node, block_nl=True)
    if len(texts) >= 2:
        banko, altili_name = texts[0], texts[1]
    elif len(texts) == 1 and "ganyan" in texts[0].lower():
        banko, altili_name = "", texts[0]
    else:
        return []
    if tt_node.parent is None:
        return []
    siblings = tt_node.parent.children()
    container = None
    for sib in siblings[siblings.index(tt_node) + 1:]:
        if sib.el_id in _ALTILI_BY_ID:
            break
        if found := _find(sib, lambda n: "kupon-yazar-container" in n.cls):
            container = found[0]
            break
    if container is None:
        return []
    cols = _find(container, lambda n: "kupon-yazar-column" in n.cls)
    if len(cols) != 6:
        return []
    legs = []
    for col in cols:
        nums = [
            str(int(t))
            for item in _find(col, lambda n: "kupon-yazar-item" in n.cls)
            if (t := _collect_text(item)).isdigit() and int(t) > 0
        ]
        if not nums:
            return []
        legs.append(",".join(nums))
    return [
        {
            "tipster": slug,
            "kind": "altili",
            "altili_name": altili_name,
            "leg_no": leg_no,
            "race_ref": None,
            "picks": legs[leg_no - 1],
            "banko": banko,
        }
        for leg_no in range(1, 7)
    ]


def _parse_ai_span(span_node, slug):
    if span_node.parent is None:
        return []
    siblings = span_node.parent.children()
    for sib in siblings[siblings.index(span_node) + 1:]:
        if sib.tag == "span":
            break
        for b_node in _find(sib, lambda n: n.tag in ("b", "strong")):
            if m := _AI_PICK_RE.match(_collect_text(b_node)):
                banko, city, race_no = m.group(1).strip(), m.group(2).strip(), int(m.group(3))
                if banko and city and race_no >= 1:
                    return [{
                        "tipster": slug,
                        "kind": "tek_kosu",
                        "altili_name": None,
                        "leg_no": None,
                        "race_ref": f"{city} {race_no}. koşu",
                        "picks": "",
                        "banko": banko,
                    }]
    return []


def parse_sporx_coupons(html_bytes_or_str):
    """Parse Sporx 'at-yarisi-hazir-kuponlar' HTML (bytes or str) into normalized tip rows."""
    text = _decode_html(html_bytes_or_str)
    if not text or not text.strip():
        return []
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    rows, seen = [], set()

    def walk(node):
        if node.el_id in _ALTILI_BY_ID and _ALTILI_BY_ID[node.el_id] not in seen:
            slug = _ALTILI_BY_ID[node.el_id]
            if parsed := _parse_altili_card(node, slug):
                seen.add(slug)
                rows.extend(parsed)
        elif node.tag == "span":
            key = _collect_text(node).replace("İ", "i").replace("I", "i").replace("ı", "i").lower()
            slug = _AI_SLUGS.get(key)
            if slug and slug not in seen and (parsed := _parse_ai_span(node, slug)):
                seen.add(slug)
                rows.extend(parsed)
        for ch in node.children():
            walk(ch)

    walk(builder.root)
    return rows


def content_hash(rows):
    """Return deterministic first-16-hex SHA-256 digest of parsed tip rows."""
    canonical = sorted(
        (
            {
                "tipster": r.get("tipster") or "",
                "kind": r.get("kind") or "",
                "altili_name": r.get("altili_name") or "",
                "leg_no": int(r["leg_no"]) if r.get("leg_no") is not None else 0,
                "race_ref": r.get("race_ref") or "",
                "picks": r.get("picks") or "",
                "banko": r.get("banko") or "",
            }
            for r in rows
        ),
        key=lambda x: (
            x["tipster"], x["leg_no"], x["kind"],
            x["altili_name"], x["race_ref"], x["picks"], x["banko"],
        ),
    )
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
