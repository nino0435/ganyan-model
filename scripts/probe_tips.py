"""Türkiye at yarışı tahmin/bülten kaynakları erişim ve içerik ölçer (1. aşama).

Yalnız Python standart kütüphanesi ve ganyan/tjk.py::UA kullanır.
Aday sayfaları ve liste sayfalarından keşfedilen en çok 3 yeni yazıyı indirir,
ham HTML yanıtlarını (<=400 KB) --out-dir altına kaydeder ve --doc envanter belgesini üretir.
"""
import argparse
import datetime as dt
import gzip
import html as html_lib
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.tjk import UA

IST = ZoneInfo("Europe/Istanbul")
MAX_RAW_BYTES = 400_000
MAX_SNIPPET_CHARS = 200
MAX_ARTICLES_PER_SOURCE = 3
JS_ONLY_MAX_TEXT_LEN = 500
JS_ONLY_MIN_SCRIPTS = 3

CANDIDATES = {
    "sporx": [
        "https://www.sporx.com/at-yarisi-hazir-kuponlar",
        "https://www.sporx.com/at-yarisi",
        "https://www.sporx.com/at-yarisi-muhtemeller",
    ],
    "gazetevatan": [
        "https://www.gazetevatan.com/sampiy10/at-yarisi/",
    ],
    "milliyet": [
        "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/",
    ],
    "fanatik": [
        "https://www.fanatik.com.tr/at-yarisi",
        "https://www.fanatik.com.tr/haberleri/hipodrom",
    ],
    "hipodrom": [
        "https://www.hipodrom.com/",
    ],
    "atyarisi": [
        "https://www.atyarisi.com/",
    ],
    "hurriyet": [
        "https://www.hurriyet.com.tr/haberleri/istanbul-hipodromu",
    ],
    "sabah": [
        "https://www.sabah.com.tr/at-yarisi",
    ],
    "liderform": [
        "https://www.liderform.com.tr/tahminler",
        "https://www.liderform.com.tr/program/tahmin",
    ],
}

TAHMIN_ARTICLE_RE = (
    r"^/(?!(?:haberleri|etiket|kategori|konu|yazarlar)/)(?!.*iddaa)"
    r"(?:"
    r"(?:[a-z0-9-]+/)+(?=[a-z0-9-]*-)[a-z0-9-]*tahmin[a-z0-9-]*"
    r"|(?:[a-z0-9-]+/)*\d{4}/\d{2}/\d{2}/[a-z0-9-]*tahmin[a-z0-9-]*"
    r"|[a-z0-9-]*tahmin[a-z0-9-]*-\d+"
    r")"
    r"(?:\.html?)?/?$"
)

DISCOVERY_PATTERNS = {
    "gazetevatan": [
        r"^/sampiy10/(?!sayfa-\d+/?$)(?:[a-z0-9-]+/)?[a-z0-9-]+-\d+(?:\.html?)?/?$",
    ],
    "milliyet": [
        r"^/skorer/(?:yazarlar/)?afsin-yakuboglu/altili-ganyanda-bugun-\d{1,2}-[a-z][a-z0-9-]*-\d+(?:\.html?)?/?$",
    ],
    "fanatik": [TAHMIN_ARTICLE_RE],
    "sabah": [TAHMIN_ARTICLE_RE],
}

ASSET_EXT_RE = re.compile(
    r"\.(?:css|js|mjs|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|map|pdf|xml|json)(?:\?|$)",
    re.IGNORECASE,
)
PICK_NUM_SEQ_RE = re.compile(
    r"(?<![\d/-])\d{1,2}(?:\s?[-–/,]\s?\d{1,2}){1,}(?![\d/-])"
)
AYAK_RE = re.compile(r"(?:\b\d+\.\s*ayak\b|\bayak(?:ta|lar|ları)?\b)")
BANKO_RE = re.compile(r"\bbanko(?:su|lar|ları|m|muz)?\b")

META_DATE_NAME_RE = re.compile(
    r"""\b(?:property|name|itemprop)\s*=\s*["']"""
    r"""(?:(?:og:)?article:published_time|og:published_time|datePublished|dateCreated|pubdate|publish[-_]?date|dc\.date(?:\.issued)?)["']""",
    re.IGNORECASE,
)
META_DATE_CONTENT_RE = re.compile(
    r"""\bcontent\s*=\s*["'][^"']*(?:19|20)\d{2}[^"']*["']""",
    re.IGNORECASE,
)
TIME_TAG_RE = re.compile(
    r"""<time\b[^>]*\bdatetime\s*=\s*["'][^"']*(?:19|20)\d{2}[^"']*["']""",
    re.IGNORECASE,
)
ITEMPROP_DATE_ATTR_RE = re.compile(
    r"""<(?!meta\b)[a-z0-9]+\b(?=[^>]*\bitemprop\s*=\s*["']datePublished["'])(?=[^>]*\b(?:content|datetime)\s*=\s*["'][^"']*(?:19|20)\d{2})[^>]*>""",
    re.IGNORECASE,
)
ITEMPROP_DATE_ELEM_RE = re.compile(
    r"""<(?!meta\b)([a-z0-9]+)\b[^>]*\bitemprop\s*=\s*["']datePublished["'][^>]*>(.*?)</\1>""",
    re.DOTALL | re.IGNORECASE,
)
JSONLD_DATE_RE = re.compile(
    r"""["']datePublished["']\s*:\s*["'][^"']*(?:19|20)\d{2}[^"']*["']""",
    re.IGNORECASE,
)
VISIBLE_DATE_LABEL_RE = re.compile(
    r"\b(?:yayınlanma|yayinlanma|yayımlanma|yayimlanma|yayın\s+tarihi|yayin\s+tarihi"
    r"|eklenme\s+tarihi|güncellenme(?:\s+tarihi)?|guncellenme(?:\s+tarihi)?"
    r"|son\s+güncelleme|haber\s+giriş)\b"
)
VISIBLE_DATETIME_RE = re.compile(
    r"(?<!\d)\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\s*(?:[-–,|]\s*|\s+)\d{1,2}:\d{2}(?!\d)"
)

PAYWALL_JSON_RE = re.compile(
    r"""["']isAccessibleForFree["']\s*:\s*(?:false|["']false["'])""",
    re.IGNORECASE,
)
PAYWALL_ATTR_RE = re.compile(
    r"""<[a-z0-9]+\b[^>]*(?:class|id)\s*=\s*["'][^"']*\bpaywall\b[^"']*["']""",
    re.IGNORECASE,
)
PAYWALL_TEXT_RE = re.compile(
    r"(?:\b(?:üye(?:lik)?|abone(?:lik)?)\s+gerektir"
    r"|\bsadece\s+(?:üye|abone)lere\s+özel"
    r"|\b(?:ücretli|vip|gold|altın|premium)\s+üyelik"
    r"|\b(?:görüntülemek|okumak|erişmek|görmek)\s+için\s+(?:üye\s+ol|giriş\s+yap|abone\s+ol)"
    r"|\bbu\s+(?:içerik|sayfa|tahmin|kupon)\s+(?:sadece\s+)?(?:üye|abone))"
)

TR_ASCII_MAP = str.maketrans({
    "ç": "c", "Ç": "c",
    "ğ": "g", "Ğ": "g",
    "ı": "i", "İ": "i", "I": "i",
    "ö": "o", "Ö": "o",
    "ş": "s", "Ş": "s",
    "ü": "u", "Ü": "u",
})


def _tr_lower(text):
    """Türkçe İ/I harflerini koruyarak küçük harfe çevirir."""
    return (text or "").replace("İ", "i").replace("I", "ı").lower()


def _normalize_host(netloc):
    host = (netloc or "").split(":")[0].lower().strip()
    return host[4:] if host.startswith("www.") else host


def safe_slug(text):
    s = (text or "").translate(TR_ASCII_MAP).lower()
    s = re.sub(r"[^a-z0-9._-]+", "_", s).strip("_")
    return s[:80] or "anasayfa"


def url_to_slug(url):
    parsed = urllib.parse.urlparse(url or "")
    raw = (parsed.path or "").strip("/")
    if parsed.query:
        raw = f"{raw}_{parsed.query}" if raw else parsed.query
    return safe_slug(raw or "anasayfa")


def _strip_non_text_tags(fragment, drop_nav=False):
    if not fragment:
        return ""
    cleaned = re.sub(r"<!--.*?-->", " ", fragment, flags=re.DOTALL)
    cleaned = re.sub(
        r"<(script|style|svg)\b[^>]*>.*?(?:</\1>|\Z)",
        " ",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if drop_nav:
        cleaned = re.sub(
            r"<nav\b[^>]*>.*?(?:</nav>|\Z)",
            " ",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )
    no_tags = re.sub(r"<[^>]+>", " ", cleaned)
    unescaped = html_lib.unescape(no_tags).replace("\xa0", " ")
    return re.sub(r"\s+", " ", unescaped).strip()


def extract_body_fragment(html):
    if not html:
        return ""
    m = re.search(r"<body\b[^>]*>(.*?)(?:</body>|\Z)", html, flags=re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else html


def extract_title(html):
    if not html:
        return ""
    m = re.search(r"<title\b[^>]*>(.*?)</title>", html, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    return _strip_non_text_tags(m.group(1))[:140]


def discover_links(html, base_url, patterns):
    """Liste sayfası HTML'sinden verilen kalıplara uyan aynı alan adlı yazı URL'lerini döndürür."""
    if not html or not patterns:
        return []
    if isinstance(patterns, (str, re.Pattern)):
        patterns = [patterns]
    compiled = [
        p if isinstance(p, re.Pattern) else re.compile(p, flags=re.IGNORECASE)
        for p in patterns
    ]
    base_parsed = urllib.parse.urlparse(base_url or "")
    base_domain = _normalize_host(base_parsed.netloc)
    base_norm = urllib.parse.urldefrag(base_url or "")[0].rstrip("/")

    found = []
    seen = set()
    for m in re.finditer(
        r"""<a\b[^>]*?\bhref\s*=\s*(?:["']([^"']+)["']|([^\s>"']+))""",
        html,
        flags=re.IGNORECASE,
    ):
        raw_href = html_lib.unescape((m.group(1) or m.group(2) or "").strip())
        if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:", "whatsapp:")):
            continue
        full_url = urllib.parse.urljoin(base_url, raw_href)
        full_url = urllib.parse.urldefrag(full_url)[0]
        parsed = urllib.parse.urlparse(full_url)
        if parsed.scheme not in ("http", "https"):
            continue
        if base_domain and _normalize_host(parsed.netloc) != base_domain:
            continue
        path = parsed.path or "/"
        if ASSET_EXT_RE.search(path):
            continue
        if full_url.rstrip("/") == base_norm:
            continue
        dedup_key = (parsed.scheme, _normalize_host(parsed.netloc), path.rstrip("/"), parsed.query)
        if dedup_key in seen:
            continue
        if any(rx.search(path) or rx.search(full_url) for rx in compiled):
            seen.add(dedup_key)
            found.append(full_url)
    return found


def pick_newest_links(urls, limit=MAX_ARTICLES_PER_SOURCE):
    """Bulunan yazı bağlantılarından en yeni en çok `limit` adedini seçer."""
    if not urls or limit <= 0:
        return []

    def _recency_key(item):
        idx, u = item
        path = urllib.parse.urlparse(u).path or ""
        dm = re.search(r"(?<!\d)(20\d{2})[/-](\d{2})[/-](\d{2})(?!\d)", path)
        date_num = int(dm.group(1) + dm.group(2) + dm.group(3)) if dm else 0
        idm = re.search(r"-(\d{4,})(?:\.html?)?/?$", path)
        art_id = int(idm.group(1)) if idm else 0
        return (date_num, art_id, -idx)

    ranked = sorted(enumerate(urls), key=_recency_key, reverse=True)
    return [u for _, u in ranked[:limit]]


def _has_meta_date_stamp(no_script_html, raw_html):
    if JSONLD_DATE_RE.search(raw_html):
        return True
    if TIME_TAG_RE.search(no_script_html) or ITEMPROP_DATE_ATTR_RE.search(no_script_html):
        return True
    for em in ITEMPROP_DATE_ELEM_RE.finditer(no_script_html):
        if re.search(r"\d", _strip_non_text_tags(em.group(2))):
            return True
    for m in re.finditer(r"<meta\b[^>]*>", no_script_html, flags=re.IGNORECASE):
        tag = m.group(0)
        if META_DATE_NAME_RE.search(tag) and META_DATE_CONTENT_RE.search(tag):
            return True
    return False


def detect_signals(html):
    """HTML metninden tahmin, tarih damgası, düz metin uzunluğu, JS-only ve paywall sinyallerini çıkarır."""
    if not html:
        return {
            "has_picks_text": False,
            "has_date_stamp": False,
            "body_text_len": 0,
            "uses_js_only": False,
            "paywall_hint": False,
        }

    body_frag = extract_body_fragment(html)
    body_text = _strip_non_text_tags(body_frag, drop_nav=False)
    body_text_len = len(body_text)

    picks_text_low = _tr_lower(_strip_non_text_tags(body_frag, drop_nav=True))
    has_ayak = bool(AYAK_RE.search(picks_text_low))
    has_num_seq = bool(PICK_NUM_SEQ_RE.search(picks_text_low))
    has_banko = bool(BANKO_RE.search(picks_text_low))
    has_picks_text = (has_ayak and has_num_seq) or has_banko

    no_script_html = re.sub(
        r"<(script|style)\b[^>]*>.*?(?:</\1>|\Z)",
        " ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    body_low = _tr_lower(body_text)
    has_date_stamp = (
        _has_meta_date_stamp(no_script_html, html)
        or bool(VISIBLE_DATE_LABEL_RE.search(body_low))
        or bool(VISIBLE_DATETIME_RE.search(body_low))
    )

    script_count = len(re.findall(r"<script\b", html, flags=re.IGNORECASE))
    uses_js_only = (body_text_len < JS_ONLY_MAX_TEXT_LEN) and (script_count >= JS_ONLY_MIN_SCRIPTS)

    paywall_hint = (
        bool(PAYWALL_JSON_RE.search(html))
        or bool(PAYWALL_ATTR_RE.search(no_script_html))
        or bool(PAYWALL_TEXT_RE.search(body_low))
    )

    return {
        "has_picks_text": has_picks_text,
        "has_date_stamp": has_date_stamp,
        "body_text_len": body_text_len,
        "uses_js_only": uses_js_only,
        "paywall_hint": paywall_hint,
    }


def extract_sample_snippet(html, max_chars=MAX_SNIPPET_CHARS):
    """Tahmin içeriğinden (yoksa makale gövdesinden) en çok `max_chars` karakterlik kısa alıntı döndürür."""
    if not html or max_chars <= 0:
        return ""
    body_frag = extract_body_fragment(html)
    art_m = re.search(r"<(article|main)\b[^>]*>(.*?)</\1>", body_frag, flags=re.DOTALL | re.IGNORECASE)
    candidate_text = ""
    if art_m:
        candidate_text = _strip_non_text_tags(art_m.group(2), drop_nav=True)
    if len(candidate_text) < 40:
        candidate_text = _strip_non_text_tags(body_frag, drop_nav=True)
    if not candidate_text:
        return ""

    low = _tr_lower(candidate_text)
    anchor = (
        re.search(r"\b1\.\s*ayak\b", low)
        or re.search(r"\b\d+\.\s*ayak\b", low)
        or (PICK_NUM_SEQ_RE.search(low) if AYAK_RE.search(low) else None)
        or BANKO_RE.search(low)
    )
    if anchor:
        start = max(0, anchor.start() - 25)
        if start > 0:
            sp = candidate_text.find(" ", start)
            if 0 <= sp < anchor.start():
                start = sp + 1
        snippet = candidate_text[start : start + max_chars].strip()
    else:
        snippet = candidate_text[:max_chars].strip()
    return snippet[:max_chars]


def decode_html_bytes(body, content_type=""):
    if not body:
        return ""
    enc = None
    ct_m = re.search(r"charset\s*=\s*([A-Za-z0-9._-]+)", content_type or "", flags=re.IGNORECASE)
    if ct_m:
        enc = ct_m.group(1).strip("\"'")
    if not enc:
        head_ascii = body[:2048].decode("ascii", errors="ignore")
        meta_m = re.search(r"""charset\s*=\s*["']?\s*([A-Za-z0-9._-]+)""", head_ascii, flags=re.IGNORECASE)
        if meta_m:
            enc = meta_m.group(1)
    if enc:
        try:
            return body.decode(enc, errors="replace")
        except LookupError:
            pass
    return body.decode("utf-8", errors="replace")


def detect_block_reason(html_text, status_code, error_msg=None):
    if status_code is None:
        return f"Hata/zaman aşımı ({error_msg or 'ağ hatası'})"
    low = (html_text or "").lower()
    cf_markers = (
        "just a moment...",
        "attention required! | cloudflare",
        "cf-browser-verification",
        "__cf_chl_",
        "cf-error-details",
    )
    if any(tok in low for tok in cf_markers) or ("cloudflare" in low and status_code in (403, 429, 503)):
        return f"Cloudflare engeli (HTTP {status_code})"
    if "5651 sayılı" in low or "erişim engellenmiştir" in low:
        return f"BTK erişim engeli (HTTP {status_code})"
    if status_code >= 400:
        return f"HTTP {status_code}"
    return None


def fetch_url(url, tries=2, timeout=20):
    """Nazik HTTP GET: (status, body_bytes, final_url, content_type, error_msg) döndürür."""
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    last_err = None
    for i in range(max(1, tries)):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                ce = (resp.headers.get("Content-Encoding") or "").lower()
                if ce == "gzip" or raw[:2] == b"\x1f\x8b":
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass
                ctype = resp.headers.get("Content-Type", "")
                final_u = resp.geturl() or url
                return resp.status, raw, final_u, ctype, None
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read()
                if err_body[:2] == b"\x1f\x8b":
                    try:
                        err_body = gzip.decompress(err_body)
                    except Exception:
                        pass
            except Exception:
                err_body = b""
            ctype = e.headers.get("Content-Type", "") if e.headers else ""
            final_u = e.geturl() or url
            if e.code in (400, 401, 403, 404, 410, 451) or i == tries - 1:
                return e.code, err_body, final_u, ctype, f"HTTP {e.code}"
            time.sleep(2 * (i + 1))
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    return None, b"", url, "", last_err or "bağlantı hatası"


def _unique_raw_filename(source, url, used_names):
    base_slug = url_to_slug(url)
    src_slug = safe_slug(source)
    candidate = f"{src_slug}__{base_slug}.html"
    idx = 2
    while candidate in used_names:
        candidate = f"{src_slug}__{base_slug}_{idx}.html"
        idx += 1
    used_names.add(candidate)
    return candidate


def run_probe(out_dir="data/raw/probe_tips", delay=1.5, fetch_fn=None, sleep_fn=time.sleep):
    """Tüm aday URL'leri ve keşfedilen yazı bağlantılarını yoklar."""
    os.makedirs(out_dir, exist_ok=True)
    do_fetch = fetch_fn or fetch_url
    used_names = set()
    records = []
    discovered_by_source = {}
    req_count = 0

    def _probe_one(source, url, kind):
        nonlocal req_count
        if req_count > 0 and delay > 0:
            sleep_fn(delay)
        req_count += 1
        try:
            status, body, final_url, content_type, err_msg = do_fetch(url)
        except Exception as exc:
            status, body, final_url, content_type, err_msg = (
                None,
                b"",
                url,
                "",
                f"{type(exc).__name__}: {exc}",
            )

        body = body or b""
        raw_path = None
        truncated = False
        if body:
            fname = _unique_raw_filename(source, url, used_names)
            raw_path = os.path.join(out_dir, fname)
            cut = body[:MAX_RAW_BYTES]
            truncated = len(body) > MAX_RAW_BYTES
            with open(raw_path, "wb") as fp:
                fp.write(cut)

        html_text = decode_html_bytes(body, content_type) if body else ""
        title = extract_title(html_text)
        signals = detect_signals(html_text)
        blocked = detect_block_reason(html_text, status, err_msg)
        snippet = (
            extract_sample_snippet(html_text, MAX_SNIPPET_CHARS)
            if (status == 200 and (signals["has_picks_text"] or kind == "yazı"))
            else ""
        )

        rec = {
            "source": source,
            "kind": kind,
            "url": url,
            "final_url": final_url or url,
            "status": status,
            "bytes": len(body),
            "truncated": truncated,
            "content_type": (content_type or "").split(";")[0].strip(),
            "full_content_type": content_type or "",
            "title": title,
            "signals": signals,
            "blocked": blocked,
            "snippet": snippet,
            "raw_path": raw_path,
        }
        records.append(rec)
        return rec, html_text

    for source, urls in CANDIDATES.items():
        seed_norm = {urllib.parse.urldefrag(u)[0].rstrip("/") for u in urls}
        found_links = []
        seen_links = set()

        for url in urls:
            rec, html_text = _probe_one(source, url, kind="liste")
            if source in DISCOVERY_PATTERNS and html_text and rec["status"] == 200:
                links = discover_links(html_text, rec["final_url"] or url, DISCOVERY_PATTERNS[source])
                for lk in links:
                    norm_lk = lk.rstrip("/")
                    if norm_lk not in seed_norm and norm_lk not in seen_links:
                        seen_links.add(norm_lk)
                        found_links.append(lk)

        if source in DISCOVERY_PATTERNS:
            chosen = pick_newest_links(found_links, limit=MAX_ARTICLES_PER_SOURCE)
            discovered_by_source[source] = {
                "all": found_links,
                "fetched": chosen,
            }
            for art_url in chosen:
                _probe_one(source, art_url, kind="yazı")
        else:
            discovered_by_source[source] = {
                "all": [],
                "fetched": [],
            }

    return {
        "records": records,
        "discovered": discovered_by_source,
        "request_count": req_count,
        "out_dir": out_dir,
    }


def _md_escape(text):
    return (text or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _yn(flag):
    return "Evet" if flag else "Hayır"


def _build_note(rec):
    parts = []
    if rec["blocked"]:
        parts.append(rec["blocked"])
    if rec["signals"]["paywall_hint"]:
        parts.append("paywall izi")
    if rec["final_url"] and rec["final_url"] != rec["url"]:
        parts.append(f"yönlendirme → {rec['final_url']}")
    if rec["full_content_type"]:
        parts.append(rec["full_content_type"])
    parts.append(f"metin={rec['signals']['body_text_len']} krk")
    if rec["truncated"]:
        parts.append("ham<=400KB kesildi")
    if rec["title"]:
        parts.append(f"başlık: {rec['title'][:70]}")
    return "; ".join(parts)


def render_inventory_markdown(probe_data, measured_at=None):
    """Ölçüm çıktısından docs/TAHMIN_KAYNAK_ENVANTERI.md içeriğini üretir."""
    measured_at = measured_at or dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M %Z")
    records = probe_data["records"]
    discovered = probe_data["discovered"]

    lines = [
        "# Tahmin ve Bülten Kaynakları Erişim Envanteri",
        "",
        f"- **Ölçüm zamanı:** {measured_at}",
        f"- **Toplam HTTP isteği:** {probe_data['request_count']}",
        f"- **Ham HTML dizini:** `{probe_data['out_dir']}`",
        "",
        "## 1. URL Ölçüm Tablosu",
        "",
        "| Kaynak | Tür | URL | HTTP | Bayt | Tahmin Metni | Tarih Damgası | JS-Only | Not |",
        "|---|---|---|---:|---:|---|---|---|---|",
    ]

    for rec in records:
        sig = rec["signals"]
        http_s = str(rec["status"]) if rec["status"] is not None else "ERR"
        note_s = _md_escape(_build_note(rec))
        lines.append(
            f"| `{_md_escape(rec['source'])}` | {rec['kind']} | `{_md_escape(rec['url'])}` | "
            f"{http_s} | {rec['bytes']} | {_yn(sig['has_picks_text'])} | "
            f"{_yn(sig['has_date_stamp'])} | {_yn(sig['uses_js_only'])} | {note_s} |"
        )
    lines.append("")

    lines.extend([
        "## 2. Kaynak Bazında Bulunan Yazı Bağlantıları",
        "",
    ])
    for source in CANDIDATES:
        info = discovered.get(source, {"all": [], "fetched": []})
        all_links = info["all"]
        fetched_set = set(info["fetched"])
        if source not in DISCOVERY_PATTERNS:
            lines.append(f"### `{source}`")
            lines.append("- Liste derinleştirme tanımlı değil (doğrudan aday adres ölçüldü).")
            lines.append("")
            continue
        lines.append(
            f"### `{source}` (bulunan: {len(all_links)}, indirilen: {len(info['fetched'])})"
        )
        if not all_links:
            lines.append("- Eşleşen yazı bağlantısı bulunamadı.")
        else:
            for lk in all_links[:10]:
                tag = " **(indirildi)**" if lk in fetched_set else ""
                lines.append(f"- `{lk}`{tag}")
            if len(all_links) > 10:
                lines.append(f"- _... ve {len(all_links) - 10} bağlantı daha._")
        lines.append("")

    lines.extend([
        "## 3. Tahmin İçeriğinden Örnekler (İlk <=200 Karakter)",
        "",
    ])
    snippet_rows = [r for r in records if r["snippet"]]
    if not snippet_rows:
        lines.append("_Tahmin metni veya indirilen yazı gövdesi örneği bulunamadı._")
    else:
        for rec in snippet_rows:
            sig = rec["signals"]
            label = "tahmin sinyali var" if sig["has_picks_text"] else "tahmin sinyali yok — gövde başı"
            short = _md_escape(rec["snippet"][:MAX_SNIPPET_CHARS])
            lines.append(f"- **`{rec['source']}`** (`{rec['url']}`, {label}):")
            lines.append(f"  > {short}")
    lines.append("")
    return "\n".join(lines)


def _write_markdown(doc_path, content):
    parent = os.path.dirname(os.path.abspath(doc_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(doc_path, "w", encoding="utf-8") as fp:
        fp.write(content)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Türkiye at yarışı tahmin kaynaklarını yoklar.")
    ap.add_argument(
        "--out-dir",
        default="data/raw/probe_tips",
        help="Ham HTML kayıt dizini (varsayılan: data/raw/probe_tips)",
    )
    ap.add_argument(
        "--doc",
        default="docs/TAHMIN_KAYNAK_ENVANTERI.md",
        help="Envanter belgesi çıktı yolu (varsayılan: docs/TAHMIN_KAYNAK_ENVANTERI.md)",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="İstekler arası bekleme süresi saniye (varsayılan: 1.5)",
    )
    args = ap.parse_args(argv)

    try:
        measured_at = dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M %Z")
        data = run_probe(out_dir=args.out_dir, delay=args.delay)
        md = render_inventory_markdown(data, measured_at=measured_at)
        _write_markdown(args.doc, md)
        print(
            f"Tahmin kaynak envanteri yazıldı: {args.doc} "
            f"(toplam {data['request_count']} istek, ham dizin: {args.out_dir})",
            flush=True,
        )
    except Exception as exc:
        print(f"[probe_tips] Uyarı: beklenmeyen hata yakalandı: {exc}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
