"""Veri kaynağı derinlik ölçer (İP-1): TJK HTML/sorgu uçları ve dış siteler.

Yalnız Python standart kütüphanesi ve ganyan/tjk.py::get kullanır.
Veritabanına dokunmaz; ham yanıtları --raw-dir altına, özeti --out Markdown dosyasına yazar.
"""
import argparse
import datetime as dt
import gzip
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.tjk import UA, get as tjk_get

IST = ZoneInfo("Europe/Istanbul")
XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
TJK_DELAY = 1.0
EXT_DELAY = 2.0
TJK_BUDGET = 350
EXT_BUDGET = 60

LIDERFORM_BASES = ["https://www.liderform.com.tr", "https://liderform.com.tr"]
LIDERFORM_PATHS = [
    "/sonuclar",
    "/program",
    "/program/galop",
    "/program/galop-bulten",
    "/program/performans",
    "/program/sprintler",
    "/program/kim-kimi-gecti",
    "/muhtemeller",
    "/kayitlar/galop",
    "/istatistik/at",
    "/istatistik/jokey",
]

YENIBEYGIR_BASES = ["https://yenibeygir.com", "https://www.yenibeygir.com"]
YENIBEYGIR_PATHS = [
    "/",
    "/01-05-2026/istanbul/1/sonuclar",
]

ASSET_EXT_RE = re.compile(
    r"\.(?:css|js|mjs|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|map)(?:\?|$)",
    re.IGNORECASE,
)
RUNNER_CELL_RE = re.compile(
    r'<td\b[^>]*\bclass=["\'][^"\']*\bgunluk-GunlukYarisSonuclari-([A-Za-z0-9_]+)\b[^"\']*["\'][^>]*>(.*?)</td>',
    re.DOTALL | re.IGNORECASE,
)
ALTILI_LINE_RE = re.compile(
    r"6['’‘]\s*[Ll][Iİıi]\s+[Gg][Aa][Nn][Yy][Aa][Nn]\b"
    r"(?:(?!6['’‘]\s*[Ll][Iİıi]\s+[Gg][Aa][Nn][Yy][Aa][Nn]).){0,90}?"
    r"(?:\d+\s*/\s*\d+|DEV[İIıi]R)",
    re.DOTALL,
)
SON800_RE = re.compile(r"Son\s*800\s*:\s*\d", re.IGNORECASE)
DAGITILACAK_RE = re.compile(r"Da[ğg][ıi]t[ıi]lacak\s+Tutarlar", re.IGNORECASE)

TR_ASCII_MAP = str.maketrans({
    "ç": "c", "Ç": "c",
    "ğ": "g", "Ğ": "g",
    "ı": "i", "İ": "i", "I": "i",
    "ö": "o", "Ö": "o",
    "ş": "s", "Ş": "s",
    "ü": "u", "Ü": "u",
})


class MaxRequestsReached(Exception):
    """İstek bütçesi (--max-requests veya bölüm tavanı) dolduğunda fırlatılır."""


def safe_slug(text):
    s = (text or "").translate(TR_ASCII_MAP).lower()
    s = re.sub(r"[^a-z0-9._-]+", "_", s).strip("_")
    return s[:90] or "item"


def clean_html_text(fragment):
    """HTML etiketlerini ve entity'leri temizleyip tek satır metin döndürür."""
    if not fragment:
        return ""
    no_script = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", fragment, flags=re.DOTALL | re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", " ", no_script)
    unescaped = html.unescape(no_tags).replace("\xa0", " ")
    return re.sub(r"\s+", " ", unescaped).strip()


def is_filled(val):
    """Hücre metni boş veya tire ('-') değilse True döndürür."""
    s = (val or "").strip()
    return bool(s) and s not in ("-", "--", "---", "—", "–")


def first_sunday(year, month):
    """Verilen yıl ve ayın ilk Pazar gününü döndürür."""
    d = dt.date(year, month, 1)
    return d + dt.timedelta(days=(6 - d.weekday()) % 7)


def mid_june_sunday(year):
    """Haziran ortası Pazar gününü (12..18 Haziran arası Pazar; ör. 2015 -> 14.06.2015) döndürür."""
    d = dt.date(year, 6, 12)
    return d + dt.timedelta(days=(6 - d.weekday()) % 7)


def fmt_tjk_date(d):
    """TJK sorgu parametresi için URL-kodlu gg%2Faa%2Fyyyy döndürür."""
    return urllib.parse.quote(d.strftime("%d/%m/%Y"), safe="")


# ---------------------------------------------------------------------------
# Saf (ağsız) HTML ayrıştırıcılar
# ---------------------------------------------------------------------------


def parse_domestic_cities(day_html):
    """TJK gün sayfasından ('... Y.G.' içeren bağlantılar) [(şehir_adı, sehir_id)] döndürür."""
    if not day_html:
        return []
    seen = {}
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", day_html, flags=re.DOTALL | re.IGNORECASE):
        attrs, inner = m.group(1), m.group(2)
        if "Y.G." not in clean_html_text(inner):
            continue
        id_m = re.search(r'(?<![\w-])id=["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        sid_m = re.search(r'\bdata-sehir-id=["\'](\d+)["\']', attrs, flags=re.IGNORECASE)
        if id_m and sid_m:
            city = html.unescape(id_m.group(1)).strip()
            sehir_id = sid_m.group(1).strip()
            if city and city not in seen:
                seen[city] = sehir_id
    return list(seen.items())


def parse_result_html_stats(html_text):
    """TJK HTML günlük sonuç sayfasındaki alan doluluklarını sayar."""
    stats = {
        "runner_rows": 0,
        "agf_pct": 0,
        "gny": 0,
        "fark": 0,
        "gec_cikis": 0,
        "hc": 0,
        "son_800": 0,
        "altili": 0,
        "has_dagitilacak": False,
    }
    if not html_text:
        return stats

    for tr_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", html_text, flags=re.DOTALL | re.IGNORECASE):
        row_html = tr_m.group(1)
        pairs = [(m.group(1), clean_html_text(m.group(2))) for m in RUNNER_CELL_RE.finditer(row_html)]
        if not pairs:
            continue
        stats["runner_rows"] += 1
        agf_vals = [v for k, v in pairs if k.upper().startswith("AGFORAN")]
        if any(v.lstrip().startswith("%") for v in agf_vals):
            stats["agf_pct"] += 1
        cells = {}
        for k, v in pairs:
            if k not in cells or not is_filled(cells[k]):
                cells[k] = v
        if is_filled(cells.get("Gny", "")):
            stats["gny"] += 1
        if is_filled(cells.get("Fark", "")):
            stats["fark"] += 1
        if is_filled(cells.get("GecCikis", "")):
            stats["gec_cikis"] += 1
        if is_filled(cells.get("Hc", "")):
            stats["hc"] += 1

    plain = clean_html_text(html_text)
    stats["son_800"] = len(SON800_RE.findall(plain))
    stats["altili"] = len(ALTILI_LINE_RE.findall(plain))
    stats["has_dagitilacak"] = bool(DAGITILACAK_RE.search(plain))
    return stats


def parse_total_count(html_text):
    """'Toplam N sonuçtan ...' veya 'Toplam N' ifadesinden tam sayı N döndürür; yoksa 0."""
    if not html_text:
        return 0
    plain = clean_html_text(html_text)
    for pat in (
        r"Toplam\s*:?\s*([\d.]+)\s*(?:sonu[çc]|kay[ıi]t|ko[şs]u|adet)",
        r"\bToplam\s*:?\s*([\d.]+)\b",
    ):
        m = re.search(pat, plain, flags=re.IGNORECASE)
        if m:
            digits = m.group(1).replace(".", "").replace(",", "")
            if digits.isdigit():
                return int(digits)
    if re.search(r"(?:kay[ıi]t|sonu[çc]|veri)\s+bulunamad[ıi]", plain, flags=re.IGNORECASE):
        return 0
    # Yedek: 'Toplam' metni olmayan küçük veri tablolarında <tbody> satırlarını say
    tbody_m = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", html_text, flags=re.DOTALL | re.IGNORECASE)
    if tbody_m:
        rows = 0
        for tr_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", tbody_m.group(1), flags=re.DOTALL | re.IGNORECASE):
            tds = re.findall(r"<td\b[^>]*>(.*?)</td>", tr_m.group(1), flags=re.DOTALL | re.IGNORECASE)
            if len(tds) >= 4 and not re.search(r"bulunamad[ıi]", clean_html_text(tr_m.group(1)), re.IGNORECASE):
                rows += 1
        return rows
    return 0


def extract_script_urls(html_text, base_url="https://www.tjk.org"):
    """Sayfa içindeki TJK'ya ait (kütüphane dışı) <script src='...'> adreslerini döndürür."""
    if not html_text:
        return []
    skip_tokens = ("jquery", "bootstrap", "modernizr", "analytics", "gtag", "googletagmanager", "fontawesome")
    urls = []
    for m in re.finditer(r'<script\b[^>]*\bsrc=["\']([^"\']+)["\']', html_text, flags=re.IGNORECASE):
        raw_src = html.unescape(m.group(1)).strip()
        low = raw_src.lower()
        if any(tok in low for tok in skip_tokens):
            continue
        full = urllib.parse.urljoin(base_url, raw_src)
        host = urllib.parse.urlparse(full).netloc.lower()
        if host in ("www.tjk.org", "tjk.org", "medya-cdn.tjk.org"):
            if full not in urls:
                urls.append(full)
    return urls


def extract_galop_pagination_info(*texts):
    """HTML/JS metinlerinde DataRows/IdmanIstatistikleri çağrısını ve sayfa parametresini arar."""
    found_params = []
    snippet = None

    for raw_text in texts:
        if not raw_text:
            continue
        text = html.unescape(raw_text)
        for dm in re.finditer(r"Query/DataRows/IdmanIstatistikleri|DataRows/IdmanIstatistikleri|DataRows", text):
            start = max(0, dm.start() - 250)
            end = min(len(text), dm.end() + 450)
            window = text[start:end]
            if snippet is None or "IdmanIstatistikleri" in dm.group(0):
                snippet = re.sub(r"\s+", " ", window).strip()[:300]

            # 0) Doğrudan DataRows/IdmanIstatistikleri?... sorgu dizesindeki QueryParameter_ dışı parametreler
            url_q = re.search(r"DataRows(?:/IdmanIstatistikleri)?\?([^\"'\s<>]+)", window)
            if url_q:
                for qk in re.findall(r"(?:^|&)([A-Za-z0-9_]+)=", url_q.group(1)):
                    if not qk.startswith("QueryParameter_") and qk.lower() not in ("sort", "era") and qk not in found_params:
                        found_params.append(qk)

            # 1) Query string veya string birleştirme içinde ?PageNumber= / &PageNumber= / "PageNumber="
            for qm in re.finditer(
                r"[?&\"']([A-Za-z0-9_]*(?:[Pp]age|[Ss]ayfa|[Ii]ndex|[Ss]tart|[Ss]kip)[A-Za-z0-9_]*)\s*=",
                window,
            ):
                p = qm.group(1)
                if p not in found_params:
                    found_params.append(p)

            # 2) JS nesnesi içinde { PageNumber: ... }
            for km in re.finditer(
                r"\b([A-Za-z0-9_]*(?:[Pp]age[Nn]umber|[Pp]age[Ii]ndex|[Cc]urrent[Pp]age|[Ss]ayfa[Nn]o|[Pp]age))\s*:",
                window,
            ):
                p = km.group(1)
                if p not in found_params:
                    found_params.append(p)

        # 3) Form içindeki gizli sayfa input'u (<input name="PageNumber" ...>)
        for im in re.finditer(
            r'<input\b[^>]*\bname=["\']([A-Za-z0-9_]*(?:[Pp]age|[Ss]ayfa)[A-Za-z0-9_]*)["\']',
            text,
        ):
            p = im.group(1)
            if p not in found_params:
                found_params.append(p)

    candidates = list(found_params)
    for fallback in ("PageNumber", "page", "Page", "PageIndex"):
        if fallback not in candidates:
            candidates.append(fallback)

    return {
        "param_name": found_params[0] if found_params else None,
        "snippet": snippet,
        "candidate_params": candidates,
    }


def parse_table_rows(html_text, max_rows=3):
    """HTML tablosundan başlıkları (<th>) ve ilk max_rows veri satırını döndürür."""
    if not html_text:
        return [], []
    headers = []
    thead_m = re.search(r"<thead\b[^>]*>(.*?)</thead>", html_text, flags=re.DOTALL | re.IGNORECASE)
    head_src = thead_m.group(1) if thead_m else html_text
    for th_m in re.finditer(r"<th\b[^>]*>(.*?)</th>", head_src, flags=re.DOTALL | re.IGNORECASE):
        t = clean_html_text(th_m.group(1))
        if t:
            headers.append(t)
        if len(headers) >= 20:
            break

    tbody_m = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", html_text, flags=re.DOTALL | re.IGNORECASE)
    body_src = tbody_m.group(1) if tbody_m else html_text
    rows = []
    for tr_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", body_src, flags=re.DOTALL | re.IGNORECASE):
        tds = [clean_html_text(x) for x in re.findall(r"<td\b[^>]*>(.*?)</td>", tr_m.group(1), flags=re.DOTALL | re.IGNORECASE)]
        if len(tds) >= 2 and any(tds):
            if re.search(r"bulunamad[ıi]", " ".join(tds), re.IGNORECASE):
                continue
            rows.append(tds)
            if len(rows) >= max_rows:
                break
    return headers, rows


def parse_komiser_pdfs(html_text, base_url="https://www.tjk.org"):
    """Komiser raporları HTML yanıtından tekilleştirilmiş PDF URL listesi döndürür."""
    if not html_text:
        return []
    pdfs = []
    for m in re.finditer(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html_text, flags=re.IGNORECASE):
        href = html.unescape(m.group(1)).strip()
        full = urllib.parse.urljoin(base_url, href)
        if full not in pdfs:
            pdfs.append(full)
    return pdfs


def detect_block_reason(html_text, status_code):
    """Cloudflare, BTK veya HTTP erişim engeli varsa açıklama döndürür; yoksa None."""
    if status_code is None:
        return "Bağlantı hatası / zaman aşımı (BTK veya ağ engeli olabilir)"
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
    if status_code in (401, 403, 429, 451, 503):
        return f"HTTP {status_code} engeli/hatası"
    return None


def extract_date_link_patterns(html_text):
    """Sayfadaki tarih biçimli bağlantı kalıplarını ve doldurulabilir şablonları çıkarır."""
    if not html_text:
        return {"patterns": [], "templates": [], "samples": [], "form_date_inputs": []}

    patterns = []
    templates = []
    samples = []

    date_rules = [
        (re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)"), "{YYYY-MM-DD}", "{YYYY}-{MM}-{DD}"),
        (re.compile(r"(?<!\d)(\d{2})-(\d{2})-((?:19|20)\d{2})(?!\d)"), "{DD-MM-YYYY}", "{DD}-{MM}-{YYYY}"),
        (re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.((?:19|20)\d{2})(?!\d)"), "{DD.MM.YYYY}", "{DD}.{MM}.{YYYY}"),
        (re.compile(r"(?<!\d)(\d{2})/(\d{2})/((?:19|20)\d{2})(?!\d)"), "{DD/MM/YYYY}", "{DD}/{MM}/{YYYY}"),
        (re.compile(r"(?<!\d)((?:19|20)\d{2})/(\d{2})/(\d{2})(?!\d)"), "{YYYY/MM/DD}", "{YYYY}/{MM}/{DD}"),
    ]

    for m in re.finditer(r'\b(?:href|data-url|action)=["\']([^"\']+)["\']', html_text, flags=re.IGNORECASE):
        raw_href = html.unescape(m.group(1)).strip()
        if not raw_href or raw_href.startswith(("javascript:", "#", "mailto:")):
            continue
        if ASSET_EXT_RE.search(raw_href):
            continue

        matched_rule = False
        for rx, disp_tok, tmpl_tok in date_rules:
            if rx.search(raw_href):
                matched_rule = True
                disp = rx.sub(disp_tok, raw_href, count=1)
                tmpl = rx.sub(tmpl_tok, raw_href, count=1)
                if disp not in patterns:
                    patterns.append(disp)
                if tmpl not in templates:
                    templates.append(tmpl)
                if raw_href not in samples and len(samples) < 10:
                    samples.append(raw_href)
                break

        if not matched_rule and re.search(r"[?&](?:tarih|date|gun|idmantarih)=", raw_href, flags=re.IGNORECASE):
            if raw_href not in patterns:
                patterns.append(raw_href)

    form_inputs = []
    for im in re.finditer(r"<input\b([^>]*)>", html_text, flags=re.IGNORECASE):
        attrs = im.group(1)
        nm = re.search(r'\bname=["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        tp = re.search(r'\btype=["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        if nm:
            name_val = nm.group(1)
            type_val = (tp.group(1) if tp else "").lower()
            if type_val == "date" or any(k in name_val.lower() for k in ("tarih", "date", "gun")):
                if name_val not in form_inputs:
                    form_inputs.append(name_val)

    return {
        "patterns": patterns[:15],
        "templates": templates[:15],
        "samples": samples[:10],
        "form_date_inputs": form_inputs[:10],
    }


def analyze_external_html(html_text, status_code):
    """Dış site yanıtından <title>, ilk 30 <th>, tarih kalıpları ve engel bilgisini döndürür."""
    title = ""
    if html_text:
        tm = re.search(r"<title\b[^>]*>(.*?)</title>", html_text, flags=re.DOTALL | re.IGNORECASE)
        if tm:
            title = clean_html_text(tm.group(1))[:140]

    th_headers = []
    if html_text:
        for th_m in re.finditer(r"<th\b[^>]*>(.*?)</th>", html_text, flags=re.DOTALL | re.IGNORECASE):
            t = clean_html_text(th_m.group(1))
            if t and t not in th_headers:
                th_headers.append(t)
            if len(th_headers) >= 30:
                break

    link_info = extract_date_link_patterns(html_text)
    blocked = detect_block_reason(html_text, status_code)

    return {
        "status": status_code,
        "title": title,
        "th_headers": th_headers,
        "date_patterns": link_info["patterns"],
        "templates": link_info["templates"],
        "samples": link_info["samples"],
        "form_date_inputs": link_info["form_date_inputs"],
        "blocked": blocked,
    }


def format_date_template(template, d):
    """Şablondaki {YYYY}, {MM}, {DD} yer tutucularını verilen tarihle doldurur."""
    return (
        template.replace("{YYYY}", f"{d.year:04d}")
        .replace("{MM}", f"{d.month:02d}")
        .replace("{DD}", f"{d.day:02d}")
    )


# ---------------------------------------------------------------------------
# Ağ katmanı: nazik istek, bütçe sayacı ve ham kayıt
# ---------------------------------------------------------------------------


def _external_get(url, timeout=20, extra_headers=None):
    """Dış siteler için HTTP GET: 403/503 Cloudflare gövdesini ve durum kodunu korur."""
    headers = {"User-Agent": UA}
    if extra_headers:
        headers.update(extra_headers)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, body
    except Exception:
        return None, b""


class ProbeClient:
    """İstek sayacı, bekleme süresi ve --raw-dir ham yanıt kaydını yönetir."""

    def __init__(self, raw_dir="data/raw/probe", max_requests=400, fetch_fn=None, sleep_fn=time.sleep):
        self.raw_dir = raw_dir
        self.max_requests = max_requests
        self.fetch_fn = fetch_fn
        self.sleep_fn = sleep_fn
        self.request_count = 0
        self.stopped_by_limit = False
        self.saved_files = []
        os.makedirs(self.raw_dir, exist_ok=True)

    def fetch(
        self,
        url,
        source,
        key,
        delay=TJK_DELAY,
        extra_headers=None,
        is_external=False,
        save_ext=".html.gz",
        section_limit=None,
        section_start=0,
    ):
        if self.request_count >= self.max_requests:
            self.stopped_by_limit = True
            raise MaxRequestsReached(f"--max-requests ({self.max_requests}) sınırına ulaşıldı")
        if section_limit is not None and (self.request_count - section_start) >= section_limit:
            self.stopped_by_limit = True
            raise MaxRequestsReached(f"Bölüm istek sınırı ({section_limit}) doldu")

        self.request_count += 1
        if self.fetch_fn is not None:
            status, body = self.fetch_fn(url, extra_headers)
        elif is_external:
            status, body = _external_get(url, timeout=20, extra_headers=extra_headers)
        else:
            status, body = tjk_get(url, tries=2, timeout=25, extra_headers=extra_headers)

        raw_path = None
        if body:
            fname = f"{safe_slug(source)}_{safe_slug(key)}{save_ext}"
            raw_path = os.path.join(self.raw_dir, fname)
            if save_ext.endswith(".gz"):
                with gzip.open(raw_path, "wb") as gz:
                    gz.write(body)
            else:
                with open(raw_path, "wb") as fp:
                    fp.write(body)
            self.saved_files.append({
                "path": raw_path,
                "raw_bytes": len(body),
                "disk_bytes": os.path.getsize(raw_path),
                "source": source,
                "url": url,
                "status": status,
            })

        if delay > 0:
            self.sleep_fn(delay)
        return status, body, raw_path


# ---------------------------------------------------------------------------
# Madde 2: --tjk ölçümleri
# ---------------------------------------------------------------------------


def probe_tjk(client, today=None):
    """TJK kaynaklarının tarihsel derinliğini ölçer (Madde 2a-2e, toplam <= 350 istek)."""
    today = today or dt.datetime.now(IST).date()
    sec_start = client.request_count
    result = {
        "html_results_by_year": [],
        "galop": {
            "first_date": None,
            "binary_steps": [],
            "monthly": [],
            "pagination": {},
            "sample_date": None,
            "sample_headers": [],
            "sample_rows": [],
        },
        "kosu_counts": [],
        "komiser": [],
        "pist_counts": [],
        "pist_headers": [],
    }

    def _tjk_fetch(url, source, key, xhr=True, save_ext=".html.gz"):
        hdrs = XHR_HEADERS if xhr else None
        return client.fetch(
            url,
            source=source,
            key=key,
            delay=TJK_DELAY,
            extra_headers=hdrs,
            is_external=False,
            save_ext=save_ext,
            section_limit=TJK_BUDGET,
            section_start=sec_start,
        )

    try:
        # 2a. HTML günlük sonuç: 2005..2026 her yıl Mart ve Ekim ilk pazarı (<=3 deneme), ilk yerli şehir
        print("[TJK 2a] HTML günlük sonuçlar yoklanıyor (2005..2026)...", flush=True)
        for year in range(2005, 2027):
            year_agg = {
                "year": year,
                "sampled": [],
                "days_found": 0,
                "runner_rows": 0,
                "agf_pct": 0,
                "gny": 0,
                "fark": 0,
                "gec_cikis": 0,
                "hc": 0,
                "son_800": 0,
                "altili": 0,
                "dagitilacak_days": 0,
            }
            result["html_results_by_year"].append(year_agg)

            for month in (3, 10):
                base_sunday = first_sunday(year, month)
                if base_sunday > today:
                    continue
                chosen = None
                for attempt in range(3):
                    cand = base_sunday + dt.timedelta(days=attempt)
                    if cand > today:
                        break
                    day_url = (
                        "https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisSonuclari"
                        f"?QueryParameter_Tarih={fmt_tjk_date(cand)}"
                    )
                    st, body, _ = _tjk_fetch(day_url, "tjk_gun", cand.isoformat(), xhr=False)
                    if st == 200 and body:
                        cities = parse_domestic_cities(body.decode("utf-8", "replace"))
                        if cities:
                            chosen = (cand, cities[0][0], cities[0][1])
                            break

                if not chosen:
                    continue

                cand_date, city_name, sehir_id = chosen
                city_url = (
                    "https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukYarisSonuclari"
                    f"?SehirId={urllib.parse.quote(str(sehir_id), safe='')}"
                    f"&QueryParameter_Tarih={fmt_tjk_date(cand_date)}"
                    f"&SehirAdi={urllib.parse.quote(city_name, safe='')}"
                    "&Era=past"
                )
                st_c, body_c, _ = _tjk_fetch(
                    city_url,
                    "tjk_sonuc",
                    f"{cand_date.isoformat()}_{city_name}",
                    xhr=True,
                )
                if st_c == 200 and body_c:
                    st_map = parse_result_html_stats(body_c.decode("utf-8", "replace"))
                    year_agg["days_found"] += 1
                    year_agg["sampled"].append(f"{cand_date.isoformat()} {city_name}")
                    year_agg["runner_rows"] += st_map["runner_rows"]
                    year_agg["agf_pct"] += st_map["agf_pct"]
                    year_agg["gny"] += st_map["gny"]
                    year_agg["fark"] += st_map["fark"]
                    year_agg["gec_cikis"] += st_map["gec_cikis"]
                    year_agg["hc"] += st_map["hc"]
                    year_agg["son_800"] += st_map["son_800"]
                    year_agg["altili"] += st_map["altili"]
                    if st_map["has_dagitilacak"]:
                        year_agg["dagitilacak_days"] += 1

        # 2b. Galop: ikili arama (2021-01-01..2022-06-15), aylık 15'i (2022-06..2026-11), sayfalama
        print("[TJK 2b] Galop (IdmanIstatistikleri) ikili arama ve aylık seri yoklanıyor...", flush=True)
        galop_cache = {}
        latest_sample = {"date": None, "html": ""}

        def _galop_count(d):
            if d in galop_cache:
                return galop_cache[d]
            g_url = (
                "https://www.tjk.org/TR/YarisSever/Query/Data/IdmanIstatistikleri"
                f"?QueryParameter_IDMANTARIH={fmt_tjk_date(d)}"
            )
            st_g, body_g, _ = _tjk_fetch(g_url, "tjk_galop", d.isoformat(), xhr=True)
            txt = body_g.decode("utf-8", "replace") if (st_g == 200 and body_g) else ""
            cnt = parse_total_count(txt)
            galop_cache[d] = cnt
            if cnt > 50 or (cnt > 0 and latest_sample["date"] is None):
                latest_sample["date"] = d
                latest_sample["html"] = txt
            return cnt

        lo = dt.date(2021, 1, 1)
        hi = dt.date(2022, 6, 15)
        c_lo = _galop_count(lo)
        result["galop"]["binary_steps"].append((lo.isoformat(), c_lo))
        if c_lo > 0:
            result["galop"]["first_date"] = lo.isoformat()
        else:
            c_hi = _galop_count(hi)
            result["galop"]["binary_steps"].append((hi.isoformat(), c_hi))
            if c_hi > 0:
                while (hi - lo).days > 1:
                    mid = lo + dt.timedelta(days=(hi - lo).days // 2)
                    c_mid = _galop_count(mid)
                    result["galop"]["binary_steps"].append((mid.isoformat(), c_mid))
                    if c_mid > 0:
                        hi = mid
                    else:
                        # Tek günlük tatil/boşluk yanılmasını önlemek için ertesi günü de kontrol et
                        nxt = mid + dt.timedelta(days=1)
                        if nxt < hi:
                            c_nxt = _galop_count(nxt)
                            result["galop"]["binary_steps"].append((nxt.isoformat(), c_nxt))
                            if c_nxt > 0:
                                hi = nxt
                                continue
                        lo = mid
                result["galop"]["first_date"] = hi.isoformat()

        for y in range(2022, 2027):
            m_start = 6 if y == 2022 else 1
            m_end = 11 if y == 2026 else 12
            for m in range(m_start, m_end + 1):
                d15 = dt.date(y, m, 15)
                cnt = _galop_count(d15)
                result["galop"]["monthly"].append({"date": d15.isoformat(), "count": cnt})

        # Örnek satırlar ve sayfalama keşfi
        sample_candidate_date = latest_sample["date"]
        sample_html = latest_sample["html"]
        if sample_candidate_date is not None and sample_html:
            headers, rows = parse_table_rows(sample_html, max_rows=3)
            result["galop"]["sample_date"] = sample_candidate_date.isoformat()
            result["galop"]["sample_headers"] = headers
            result["galop"]["sample_rows"] = rows

        page_url = "https://www.tjk.org/TR/YarisSever/Query/Page/IdmanIstatistikleri"
        st_p, body_p, _ = _tjk_fetch(page_url, "tjk_galop", "page_js", xhr=False)
        page_txt = body_p.decode("utf-8", "replace") if (st_p == 200 and body_p) else ""
        js_texts = [page_txt, sample_html]
        pg_info = extract_galop_pagination_info(*js_texts)

        # Inline script'te bulunamadıysa sayfadaki yerel TJK JS dosyalarını (en çok 2) kontrol et
        if pg_info["param_name"] is None and page_txt:
            for idx, s_url in enumerate(extract_script_urls(page_txt)[:2]):
                st_js, body_js, _ = _tjk_fetch(s_url, "tjk_galop_js", f"script_{idx + 1}", xhr=False)
                if st_js == 200 and body_js:
                    js_texts.append(body_js.decode("utf-8", "replace"))
                    pg_info = extract_galop_pagination_info(*js_texts)
                    if pg_info["param_name"] is not None:
                        break

        verified_param = None
        verified_rows_count = 0
        differs_from_p1 = False
        probe_date = sample_candidate_date or dt.date(2022, 6, 15)
        p1_first_row = result["galop"]["sample_rows"][0] if result["galop"]["sample_rows"] else None

        for cand_param in pg_info["candidate_params"][:3]:
            dr_url = (
                "https://www.tjk.org/TR/YarisSever/Query/DataRows/IdmanIstatistikleri"
                f"?QueryParameter_IDMANTARIH={fmt_tjk_date(probe_date)}"
                f"&{urllib.parse.quote(cand_param, safe='')}=2"
            )
            st_dr, body_dr, _ = _tjk_fetch(dr_url, "tjk_galop_datarows", f"{cand_param}_p2", xhr=True)
            if st_dr == 200 and body_dr:
                dr_txt = body_dr.decode("utf-8", "replace")
                _, dr_rows = parse_table_rows(f"<table><tbody>{dr_txt}</tbody></table>", max_rows=3)
                if dr_rows:
                    verified_param = cand_param
                    verified_rows_count = len(re.findall(r"<tr\b", dr_txt, flags=re.IGNORECASE))
                    differs_from_p1 = (p1_first_row is None) or (dr_rows[0] != p1_first_row)
                    if differs_from_p1:
                        break

        result["galop"]["pagination"] = {
            "js_param": pg_info["param_name"],
            "verified_param": verified_param,
            "verified_rows": verified_rows_count,
            "differs_from_page1": differs_from_p1,
            "snippet": pg_info["snippet"],
            "tested_date": probe_date.isoformat(),
        }

        # 2c. Koşu sorgulama: 1990..2026 yıl başına koşu sayısı
        print("[TJK 2c] Yıllık koşu sayıları yoklanıyor (1990..2026)...", flush=True)
        for year in range(1990, 2027):
            k_url = (
                "https://www.tjk.org/TR/YarisSever/Query/Data/KosuSorgulama"
                f"?QueryParameter_Tarih_Start=01%2F01%2F{year}"
                f"&QueryParameter_Tarih_End=31%2F12%2F{year}"
            )
            st_k, body_k, _ = _tjk_fetch(k_url, "tjk_kosu", str(year), xhr=True)
            cnt = parse_total_count(body_k.decode("utf-8", "replace")) if (st_k == 200 and body_k) else 0
            result["kosu_counts"].append({"year": year, "status": st_k, "count": cnt})

        # 2d. Komiser raporları: 2015, 2018, 2021, 2024 haziran ortası pazar + ilk 2 PDF
        print("[TJK 2d] Komiser raporları ve örnek PDF'ler yoklanıyor...", flush=True)
        for year in (2015, 2018, 2021, 2024):
            target_d = mid_june_sunday(year)
            pdfs = []
            used_date = target_d
            st_km = None
            for attempt in range(2):
                cand_d = target_d + dt.timedelta(days=attempt)
                km_url = (
                    "https://www.tjk.org/TR/YarisSever/Query/Data/KomiserRaporlari"
                    f"?QueryParameter_Tarih={fmt_tjk_date(cand_d)}"
                )
                st_km, body_km, _ = _tjk_fetch(km_url, "tjk_komiser", cand_d.isoformat(), xhr=True)
                if st_km == 200 and body_km:
                    pdfs = parse_komiser_pdfs(body_km.decode("utf-8", "replace"))
                    used_date = cand_d
                    if pdfs:
                        break

            downloaded = []
            for idx, pdf_url in enumerate(pdfs[:2], start=1):
                base_name = os.path.basename(urllib.parse.urlparse(pdf_url).path) or f"rapor_{idx}.pdf"
                if base_name.lower().endswith(".pdf"):
                    base_name = base_name[:-4]
                st_pdf, body_pdf, pdf_path = _tjk_fetch(
                    pdf_url,
                    "tjk_komiser_pdf",
                    f"{used_date.isoformat()}_{idx}_{base_name}",
                    xhr=False,
                    save_ext=".pdf",
                )
                downloaded.append({
                    "url": pdf_url,
                    "status": st_pdf,
                    "size": len(body_pdf) if body_pdf else 0,
                    "is_pdf": bool(body_pdf and body_pdf.startswith(b"%PDF")),
                    "path": pdf_path,
                })

            result["komiser"].append({
                "year": year,
                "date": used_date.isoformat(),
                "status": st_km,
                "pdf_count": len(pdfs),
                "downloaded": downloaded,
            })

        # 2e. Pist bilgileri: 2010..2026 yıl başına kayıt sayısı
        print("[TJK 2e] Pist/hava bilgileri yoklanıyor (2010..2026)...", flush=True)
        for year in range(2010, 2027):
            p_url = (
                "https://www.tjk.org/TR/YarisSever/Query/Data/PistBilgileri"
                f"?QueryParameter_Tarih_Start=01%2F01%2F{year}"
                f"&QueryParameter_Tarih_End=31%2F12%2F{year}"
            )
            st_pb, body_pb, _ = _tjk_fetch(p_url, "tjk_pist", str(year), xhr=True)
            txt_pb = body_pb.decode("utf-8", "replace") if (st_pb == 200 and body_pb) else ""
            cnt_pb = parse_total_count(txt_pb)
            if cnt_pb > 0 and not result["pist_headers"]:
                hdrs_pb, _ = parse_table_rows(txt_pb, max_rows=1)
                result["pist_headers"] = hdrs_pb
            result["pist_counts"].append({"year": year, "status": st_pb, "count": cnt_pb})

    except MaxRequestsReached as exc:
        print(f"[TJK] {exc} — mevcut bulgular yazılacak.", flush=True)

    return result


# ---------------------------------------------------------------------------
# Madde 3: --external ölçümleri
# ---------------------------------------------------------------------------


def _pick_working_base(client, bases, first_path, source_name, sec_start):
    """İlk istekte SSL/DNS bağlantı hatası olursa alternatif alan adını dener."""
    last_res = (None, b"", None, bases[0])
    for i, base in enumerate(bases):
        url = base + first_path
        st, body, rpath = client.fetch(
            url,
            source=source_name,
            key=first_path.strip("/") or "home",
            delay=EXT_DELAY,
            is_external=True,
            section_limit=EXT_BUDGET,
            section_start=sec_start,
        )
        last_res = (st, body, rpath, base)
        if st is not None or i == len(bases) - 1:
            return last_res
    return last_res


def _resolve_historical_template(site, kind, page_entries, base_url):
    """Bulunan sayfa analizlerinden sonuç veya galop için en uygun tarih şablonunu seçer."""
    for entry in page_entries:
        if entry["templates"]:
            for tmpl in entry["templates"]:
                low = tmpl.lower()
                if kind == "sonuc" and ("sonuc" in low or entry["path"].endswith("sonuclar")):
                    return urllib.parse.urljoin(base_url, tmpl), "sayfa bağlantısından bulundu"
                if kind == "galop" and "galop" in low:
                    return urllib.parse.urljoin(base_url, tmpl), "sayfa bağlantısından bulundu"

    # İlgili sayfanın kendi içinde genel tarih şablonu veya form input'u varsa kullan
    for entry in page_entries:
        p_low = entry["path"].lower()
        is_target = (kind == "sonuc" and "sonuc" in p_low) or (kind == "galop" and "galop" in p_low)
        if not is_target:
            continue
        if entry["templates"]:
            return urllib.parse.urljoin(base_url, entry["templates"][0]), "ilgili sayfa bağlantısından bulundu"
        if entry["form_date_inputs"]:
            inp = entry["form_date_inputs"][0]
            base_path = entry["path"]
            return f"{base_url}{base_path}?{inp}={{YYYY}}-{{MM}}-{{DD}}", f"form input ({inp}) kalıbı"

    # Yedek bilinen kalıplar
    if site == "yenibeygir" and kind == "sonuc":
        return f"{base_url}/{{DD}}-{{MM}}-{{YYYY}}/istanbul/1/sonuclar", "şartname varsayılan kalıbı"
    if site == "liderform" and kind == "sonuc":
        return f"{base_url}/sonuclar?tarih={{YYYY}}-{{MM}}-{{DD}}", "varsayılan sorgu kalıbı (?tarih=)"
    if site == "liderform" and kind == "galop":
        return f"{base_url}/program/galop?tarih={{YYYY}}-{{MM}}-{{DD}}", "varsayılan sorgu kalıbı (?tarih=)"
    return None, "tarih kalıbı bulunamadı"


def probe_external(client):
    """liderform.com.tr ve yenibeygir.com yollarını ve tarihsel derinliğini ölçer (<= 60 istek)."""
    sec_start = client.request_count
    result = {
        "pages": [],
        "historical": [],
        "notes": [],
    }

    def _record_page(site, path, url, st, body):
        txt = body.decode("utf-8", "replace") if body else ""
        info = analyze_external_html(txt, st)
        entry = {
            "site": site,
            "path": path,
            "url": url,
            "status": st,
            "size": len(body) if body else 0,
            "title": info["title"],
            "th_headers": info["th_headers"],
            "date_patterns": info["date_patterns"],
            "templates": info["templates"],
            "form_date_inputs": info["form_date_inputs"],
            "blocked": info["blocked"],
        }
        result["pages"].append(entry)
        return entry

    try:
        # 1) liderform.com.tr yolları
        print("[DIS] liderform.com.tr yolları yoklanıyor...", flush=True)
        lf_entries = []
        st0, body0, _, lf_base = _pick_working_base(
            client, LIDERFORM_BASES, LIDERFORM_PATHS[0], "liderform", sec_start
        )
        lf_entries.append(_record_page("liderform", LIDERFORM_PATHS[0], lf_base + LIDERFORM_PATHS[0], st0, body0))

        for path in LIDERFORM_PATHS[1:]:
            url = lf_base + path
            st, body, _ = client.fetch(
                url,
                source="liderform",
                key=path.strip("/"),
                delay=EXT_DELAY,
                is_external=True,
                section_limit=EXT_BUDGET,
                section_start=sec_start,
            )
            lf_entries.append(_record_page("liderform", path, url, st, body))

        # 2) yenibeygir.com yolları
        print("[DIS] yenibeygir.com yolları yoklanıyor...", flush=True)
        yb_entries = []
        st_y0, body_y0, _, yb_base = _pick_working_base(
            client, YENIBEYGIR_BASES, YENIBEYGIR_PATHS[0], "yenibeygir", sec_start
        )
        yb_entries.append(_record_page("yenibeygir", YENIBEYGIR_PATHS[0], yb_base + YENIBEYGIR_PATHS[0], st_y0, body_y0))

        for path in YENIBEYGIR_PATHS[1:]:
            url = yb_base + path
            st, body, _ = client.fetch(
                url,
                source="yenibeygir",
                key=path.strip("/"),
                delay=EXT_DELAY,
                is_external=True,
                section_limit=EXT_BUDGET,
                section_start=sec_start,
            )
            yb_entries.append(_record_page("yenibeygir", path, url, st, body))

        # Yenibeygir ana sayfasında galop ile ilgili bir bağlantı varsa 1 kez keşfet
        yb_home_txt = body_y0.decode("utf-8", "replace") if body_y0 else ""
        galop_href_m = re.search(
            r'href=["\']([^"\']*galop[^"\']*)["\']', yb_home_txt, flags=re.IGNORECASE
        )
        if galop_href_m:
            g_href = html.unescape(galop_href_m.group(1)).strip()
            g_url = urllib.parse.urljoin(yb_base, g_href)
            if urllib.parse.urlparse(g_url).netloc.endswith("yenibeygir.com"):
                g_path = urllib.parse.urlparse(g_url).path
                st_yg, body_yg, _ = client.fetch(
                    g_url,
                    source="yenibeygir",
                    key=f"kesif_{g_path}",
                    delay=EXT_DELAY,
                    is_external=True,
                    section_limit=EXT_BUDGET,
                    section_start=sec_start,
                )
                yb_entries.append(_record_page("yenibeygir", g_path, g_url, st_yg, body_yg))

        # 3) Eski tarih denemeleri: 2024, 2020, 2015, 2010 (Ekim ilk pazarı — İstanbul sezonu açık, 2020 pandemi dışı)
        hist_years = [2024, 2020, 2015, 2010]
        hist_targets = [
            ("liderform", "sonuc", lf_entries, lf_base),
            ("liderform", "galop", lf_entries, lf_base),
            ("yenibeygir", "sonuc", yb_entries, yb_base),
            ("yenibeygir", "galop", yb_entries, yb_base),
        ]

        print("[DIS] 2024, 2020, 2015, 2010 eski sayfa denemeleri yapılıyor...", flush=True)
        for site, kind, entries, base_url in hist_targets:
            tmpl, source_note = _resolve_historical_template(site, kind, entries, base_url)
            if not tmpl:
                result["notes"].append(f"{site} ({kind}): {source_note}")
                continue
            result["notes"].append(f"{site} ({kind}) şablonu: `{tmpl}` ({source_note})")
            for yr in hist_years:
                d = first_sunday(yr, 10)
                h_url = format_date_template(tmpl, d)
                st_h, body_h, _ = client.fetch(
                    h_url,
                    source=f"{site}_{kind}_hist",
                    key=d.isoformat(),
                    delay=EXT_DELAY,
                    is_external=True,
                    section_limit=EXT_BUDGET,
                    section_start=sec_start,
                )
                txt_h = body_h.decode("utf-8", "replace") if body_h else ""
                info_h = analyze_external_html(txt_h, st_h)
                _, sample_rows = parse_table_rows(txt_h, max_rows=5)
                result["historical"].append({
                    "site": site,
                    "kind": kind,
                    "year": yr,
                    "date": d.isoformat(),
                    "url": h_url,
                    "status": st_h,
                    "size": len(body_h) if body_h else 0,
                    "title": info_h["title"],
                    "th_count": len(info_h["th_headers"]),
                    "row_sample_count": len(sample_rows),
                    "blocked": info_h["blocked"],
                })

    except MaxRequestsReached as exc:
        print(f"[DIS] {exc} — mevcut bulgular yazılacak.", flush=True)

    return result


# ---------------------------------------------------------------------------
# Madde 4: Markdown rapor üretimi
# ---------------------------------------------------------------------------


def _md_escape(text):
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _render_raw_files_section(saved_files):
    lines = ["## Ham Örnekler", ""]
    if not saved_files:
        lines.append("_Kaydedilen ham yanıt yok._")
        return lines
    lines.append(f"Toplam **{len(saved_files)}** dosya kaydedildi:")
    lines.append("")
    lines.append("| # | Kaynak | Dosya | HTTP | Ham Boyut (B) | Disk Boyutu (B) |")
    lines.append("|---:|---|---|---:|---:|---:|")
    for idx, item in enumerate(saved_files, start=1):
        lines.append(
            f"| {idx} | `{_md_escape(item['source'])}` | `{_md_escape(item['path'])}` | "
            f"{item['status'] if item['status'] is not None else 'ERR'} | "
            f"{item['raw_bytes']} | {item['disk_bytes']} |"
        )
    return lines


def render_tjk_markdown(data, client, measured_at):
    lines = [
        "# TJK Veri Kaynağı Derinlik Envanteri",
        "",
        f"- **Ölçüm tarihi:** {measured_at}",
        f"- **Toplam istek sayısı:** {client.request_count}",
        f"- **Ham yanıt dizini:** `{client.raw_dir}`",
    ]
    if client.stopped_by_limit:
        lines.append(f"- **Not:** ⚠️ İstek sınırı (`{client.max_requests}`) dolduğu için ölçüm erken durduruldu.")
    lines.append("")

    # 2a tablosu
    lines.extend([
        "## 1. HTML Günlük Sonuç Alan Doluluğu (2005–2026)",
        "",
        "| Yıl | Örneklenen Tarihler (Şehir) | Gün | At Satırı | AGF `%` | Gny | Fark | GecCikis | Hc | Son 800 | 6'lı Satırı | Dağıtılacak Tutarlar |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in data["html_results_by_year"]:
        sampled_s = ", ".join(row["sampled"]) if row["sampled"] else "-"
        dag_s = f"{row['dagitilacak_days']}/{row['days_found']}" if row["days_found"] else "0/0"
        lines.append(
            f"| {row['year']} | {_md_escape(sampled_s)} | {row['days_found']} | "
            f"{row['runner_rows']} | {row['agf_pct']} | {row['gny']} | {row['fark']} | "
            f"{row['gec_cikis']} | {row['hc']} | {row['son_800']} | {row['altili']} | {dag_s} |"
        )
    lines.append("")

    # 2b Galop
    gal = data["galop"]
    pg = gal.get("pagination", {})
    lines.extend([
        "## 2. Galop (`IdmanIstatistikleri`)",
        "",
        f"- **İkili arama ilk verili gün (2021-01-01…2022-06-15):** `{gal['first_date'] or 'bulunamadı'}`",
        f"- **JS içinde bulunan sayfalama parametresi:** `{pg.get('js_param') or 'bulunamadı'}`",
        f"- **`DataRows` ile doğrulanan sayfalama parametresi:** `{pg.get('verified_param') or 'doğrulanamadı'}` "
        f"(test tarihi: `{pg.get('tested_date', '-')}`, dönen satır: `{pg.get('verified_rows', 0)}`, "
        f"1. sayfadan farklı: `{pg.get('differs_from_page1', False)}`)",
    ])
    if pg.get("snippet"):
        lines.append(f"- **JS `DataRows` kesiti:** `{_md_escape(pg['snippet'])}`")
    lines.append("")

    if gal["binary_steps"]:
        lines.extend([
            "### İkili Arama Adımları",
            "",
            "| Adım | Tarih | Toplam Satır |",
            "|---:|---|---:|",
        ])
        for idx, (ds, cnt) in enumerate(gal["binary_steps"], start=1):
            lines.append(f"| {idx} | {ds} | {cnt} |")
        lines.append("")

    if gal["sample_rows"]:
        lines.extend([
            f"### İlk Sayfa Örnek Satırlar (`{gal['sample_date']}`)",
            "",
        ])
        ncols = max(len(gal["sample_headers"]), max(len(r) for r in gal["sample_rows"]))
        hdrs = gal["sample_headers"][:ncols] if gal["sample_headers"] else [f"Sütun {i + 1}" for i in range(ncols)]
        if len(hdrs) < ncols:
            hdrs = hdrs + [f"Sütun {i + 1}" for i in range(len(hdrs), ncols)]
        lines.append("| " + " | ".join(_md_escape(h) for h in hdrs) + " |")
        lines.append("|" + "|".join(["---"] * ncols) + "|")
        for r in gal["sample_rows"]:
            padded = (r + [""] * ncols)[:ncols]
            lines.append("| " + " | ".join(_md_escape(c) for c in padded) + " |")
        lines.append("")

    lines.extend([
        "### Aylık Galop Satır Sayısı (Her Ayın 15'i, 2022-06…2026-11)",
        "",
        "| Tarih | Toplam Satır |",
        "|---|---:|",
    ])
    for mrow in gal["monthly"]:
        lines.append(f"| {mrow['date']} | {mrow['count']} |")
    lines.append("")

    # 2c Koşu sorgulama
    lines.extend([
        "## 3. Koşu Sorgulama Yıllık Koşu Sayıları (1990–2026)",
        "",
        "| Yıl | HTTP | Toplam Koşu |",
        "|---:|---:|---:|",
    ])
    for krow in data["kosu_counts"]:
        lines.append(f"| {krow['year']} | {krow['status'] or 'ERR'} | {krow['count']} |")
    lines.append("")

    # 2d Komiser raporları
    lines.extend([
        "## 4. Komiser Raporları ve Örnek PDF İndirmeleri",
        "",
        "| Yıl | Tarih | HTTP | PDF Sayısı | İndirilen İlk 2 PDF (Boyut / Geçerli PDF) |",
        "|---:|---|---:|---:|---|",
    ])
    for km in data["komiser"]:
        dl_parts = []
        for d_item in km["downloaded"]:
            name = os.path.basename(d_item["path"]) if d_item["path"] else os.path.basename(d_item["url"])
            dl_parts.append(f"`{name}` ({d_item['size']} B, PDF={d_item['is_pdf']})")
        dl_str = "; ".join(dl_parts) if dl_parts else "-"
        lines.append(f"| {km['year']} | {km['date']} | {km['status'] or 'ERR'} | {km['pdf_count']} | {dl_str} |")
    lines.append("")

    # 2e Pist bilgileri
    lines.extend([
        "## 5. Pist ve Hava Bilgileri Yıllık Kayıt Sayıları (2010–2026)",
        "",
    ])
    if data["pist_headers"]:
        lines.append("- **Tablo başlıkları:** " + ", ".join(f"`{_md_escape(h)}`" for h in data["pist_headers"]))
        lines.append("")
    lines.extend([
        "| Yıl | HTTP | Toplam Kayıt |",
        "|---:|---:|---:|",
    ])
    for prow in data["pist_counts"]:
        lines.append(f"| {prow['year']} | {prow['status'] or 'ERR'} | {prow['count']} |")
    lines.append("")

    lines.extend(_render_raw_files_section(client.saved_files))
    lines.append("")
    return "\n".join(lines)


def render_external_markdown(data, client, measured_at):
    lines = [
        "# Dış Veri Kaynakları Derinlik Envanteri (`liderform.com.tr`, `yenibeygir.com`)",
        "",
        f"- **Ölçüm tarihi:** {measured_at}",
        f"- **Toplam istek sayısı:** {client.request_count}",
        f"- **Ham yanıt dizini:** `{client.raw_dir}`",
    ]
    if client.stopped_by_limit:
        lines.append(f"- **Not:** ⚠️ İstek sınırı (`{client.max_requests}`) dolduğu için ölçüm erken durduruldu.")
    lines.append("")

    lines.extend([
        "## 1. Güncel Yol Yoklaması",
        "",
        "| Site | Yol | HTTP | Boyut (B) | `<title>` | İlk 30 `<th>` | Tarih Bağlantı Kalıpları | Engel / Durum |",
        "|---|---|---:|---:|---|---|---|---|",
    ])
    for p in data["pages"]:
        ths = ", ".join(p["th_headers"][:30]) if p["th_headers"] else "-"
        pats = ", ".join(p["date_patterns"][:6]) if p["date_patterns"] else "-"
        if p["form_date_inputs"] and pats == "-":
            pats = "form input: " + ", ".join(p["form_date_inputs"])
        blk = p["blocked"] or "Açık"
        lines.append(
            f"| `{p['site']}` | `{_md_escape(p['path'])}` | {p['status'] if p['status'] is not None else 'ERR'} | "
            f"{p['size']} | {_md_escape(p['title']) or '-'} | {_md_escape(ths)} | "
            f"`{_md_escape(pats)}` | {_md_escape(blk)} |"
        )
    lines.append("")

    if data["notes"]:
        lines.append("### Kullanılan Tarih Kalıpları")
        lines.append("")
        for note in data["notes"]:
            lines.append(f"- {note}")
        lines.append("")

    lines.extend([
        "## 2. Tarihsel Derinlik Denemeleri (2024, 2020, 2015, 2010)",
        "",
        "| Site | Tür | Yıl | Tarih | URL | HTTP | Boyut (B) | `<title>` | `<th>` Sayısı | Örnek Satır | Engel / Durum |",
        "|---|---|---:|---|---|---:|---:|---|---:|---:|---|",
    ])
    for h in data["historical"]:
        blk = h["blocked"] or "Açık"
        lines.append(
            f"| `{h['site']}` | `{h['kind']}` | {h['year']} | {h['date']} | `{_md_escape(h['url'])}` | "
            f"{h['status'] if h['status'] is not None else 'ERR'} | {h['size']} | "
            f"{_md_escape(h['title']) or '-'} | {h['th_count']} | {h['row_sample_count']} | {_md_escape(blk)} |"
        )
    lines.append("")

    lines.extend(_render_raw_files_section(client.saved_files))
    lines.append("")
    return "\n".join(lines)


def _write_markdown(out_path, content):
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(content)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ganyan veri kaynağı derinlik ölçer")
    ap.add_argument("--tjk", action="store_true", help="TJK HTML ve sorgu uçlarını ölç")
    ap.add_argument("--external", action="store_true", help="Dış siteleri (liderform, yenibeygir) ölç")
    ap.add_argument("--out", default=None, help="Markdown çıktı yolu")
    ap.add_argument("--raw-dir", default="data/raw/probe", help="Ham .html.gz / .pdf kayıt dizini")
    ap.add_argument("--max-requests", type=int, default=400, help="En çok HTTP istek sayısı (varsayılan: 400)")
    args = ap.parse_args(argv)

    if not args.tjk and not args.external:
        ap.error("En az bir mod seçilmeli: --tjk ve/veya --external")

    measured_at = dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M %Z")
    client = ProbeClient(raw_dir=args.raw_dir, max_requests=args.max_requests)

    if args.tjk and args.external and args.out:
        tjk_data = probe_tjk(client)
        ext_data = probe_external(client)
        combined = render_tjk_markdown(tjk_data, client, measured_at) + "\n---\n\n" + render_external_markdown(ext_data, client, measured_at)
        _write_markdown(args.out, combined)
        print(f"Birleşik rapor yazıldı: {args.out} (toplam {client.request_count} istek)", flush=True)
        return 0

    if args.tjk:
        out_tjk = args.out or "docs/KAYNAK_ENVANTERI.md"
        tjk_data = probe_tjk(client)
        _write_markdown(out_tjk, render_tjk_markdown(tjk_data, client, measured_at))
        print(f"TJK raporu yazıldı: {out_tjk} (toplam {client.request_count} istek)", flush=True)

    if args.external:
        out_ext = args.out or "docs/KAYNAK_ENVANTERI_DIS.md"
        ext_data = probe_external(client)
        _write_markdown(out_ext, render_external_markdown(ext_data, client, measured_at))
        print(f"Dış kaynak raporu yazıldı: {out_ext} (toplam {client.request_count} istek)", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
