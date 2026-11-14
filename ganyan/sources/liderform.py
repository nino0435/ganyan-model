"""Parse Liderform per-race galop HTML pages (__NEXT_DATA__ JSON, 2015+).

Leakage rule: historical pages expose scrape-day career fields (`races[]`, `ranks`,
`handicap`). Those fields must NEVER be returned or persisted, and only workouts
strictly prior to the race date (`meeting_date < race_date`) are emitted.
"""
import datetime
import json
import re
import urllib.parse

from ganyan.parse_results import race_time

BASE_URL = "https://liderform.com.tr"

DOMESTIC_CITY_SLUGS = {
    "İstanbul": "istanbul",
    "İzmir": "izmir",
    "Şanlıurfa": "sanliurfa",
    "Elazığ": "elazig",
    "Diyarbakır": "diyarbakir",
    "Kocaeli": "kocaeli",
    "Antalya": "antalya",
    "Bursa": "bursa",
    "Ankara": "ankara",
    "Adana": "adana",
}

TJK_CODE_TO_CITY = {
    "ISTANBUL": "İstanbul",
    "IZMIR": "İzmir",
    "SANLIURFA": "Şanlıurfa",
    "ELAZIG": "Elazığ",
    "DIYARBAKIR": "Diyarbakır",
    "KOCAELI": "Kocaeli",
    "ANTALYA": "Antalya",
    "BURSA": "Bursa",
    "ANKARA": "Ankara",
    "ADANA": "Adana",
}

_TR_ASCII = str.maketrans({
    "ç": "c", "Ç": "C",
    "ğ": "g", "Ğ": "G",
    "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O",
    "ş": "s", "Ş": "S",
    "ü": "u", "Ü": "U",
})

_NEXT_DATA_RE = re.compile(
    r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

_GRAPH_COLS = ("d1600", "d1400", "d1200", "d1000", "d800", "d600", "d400")


def _iso_date(val):
    if isinstance(val, datetime.datetime):
        return val.date().isoformat()
    if isinstance(val, datetime.date):
        return val.isoformat()
    s = str(val or "").strip()
    return datetime.date.fromisoformat(s[:10]).isoformat()


def _opt_iso_date(val):
    if not val:
        return None
    try:
        return _iso_date(val)
    except ValueError:
        return None


def _opt_str(val):
    if val is None:
        return None
    s = " ".join(str(val).split())
    return s or None


def _opt_positive_float(val):
    if val is None or val == "":
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if f > 0 else None


def _workout_time(val):
    """Convert Liderform split time ('25.0', '1.15.8', '1.00.5') to float seconds."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        f = float(val)
        return round(f, 4) if f > 0 else None
    s = str(val).strip().replace(",", ".")
    if not s or s in ("-", "--"):
        return None
    if s.isdigit():
        f = float(s)
        return f if f > 0 else None
    s = re.sub(r"^(\d+)\.(\d+\.\d+)$", r"\1:\2", s)
    t = race_time(s)
    return t if (t is not None and t > 0) else None


def _workout_city(track):
    """Map workout track.tjk_code to Turkish domestic city name, or None if foreign."""
    if not isinstance(track, dict):
        return None
    country = track.get("country_code")
    if country is not None and str(country).strip() and str(country).strip().upper() != "TUR":
        return None
    raw_code = track.get("tjk_code")
    if not raw_code:
        return None
    norm_code = str(raw_code).strip().translate(_TR_ASCII).upper()
    return TJK_CODE_TO_CITY.get(norm_code)


def city_slug(city):
    """Convert Turkish city name (e.g. 'İstanbul', 'Şanlıurfa') to Liderform URL slug."""
    raw = (city or "").strip()
    if raw in DOMESTIC_CITY_SLUGS:
        return DOMESTIC_CITY_SLUGS[raw]
    s = raw.translate(_TR_ASCII).lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    if not s:
        raise ValueError(f"Geçersiz şehir adı: {city!r}")
    return s


def galop_url(date, city, race_no):
    """Build Liderform per-race galop URL: /program/galop/<yyyy-mm-dd>/<slug>/<race_no>."""
    d_iso = _iso_date(date)
    slug = city_slug(city)
    r_no = int(race_no)
    if r_no < 1:
        raise ValueError(f"Geçersiz koşu numarası: {race_no!r}")
    return f"{BASE_URL}/program/galop/{d_iso}/{slug}/{r_no}"


def parse_next_data(html_text):
    """Extract and parse <script id='__NEXT_DATA__'> JSON dict from Liderform HTML."""
    if isinstance(html_text, (bytes, bytearray)):
        html_text = html_text.decode("utf-8", errors="replace")
    if not html_text or not isinstance(html_text, str):
        return {}
    m = _NEXT_DATA_RE.search(html_text)
    if not m:
        return {}
    raw_json = m.group(1).strip()
    if not raw_json:
        return {}
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_race_data(html_or_data):
    data = html_or_data if isinstance(html_or_data, dict) else parse_next_data(html_or_data)
    race_data = data.get("props", {}).get("pageProps", {}).get("raceData")
    return race_data if isinstance(race_data, list) else []


def _parse_entry_identity(entry):
    raw_no = entry.get("horse_number")
    try:
        horse_number = int(str(raw_no).strip()) if raw_no is not None and str(raw_no).strip() != "" else None
    except ValueError:
        horse_number = None

    horse_obj = entry.get("horse") if isinstance(entry.get("horse"), dict) else {}
    raw_id = horse_obj.get("id")
    ext_horse_id = str(raw_id).strip() if raw_id is not None and str(raw_id).strip() != "" else None
    horse_name = _opt_str(horse_obj.get("name"))
    return horse_number, ext_horse_id, horse_name


def parse_galop_horses(html_or_data):
    """Return horse identity dicts (horse_number, ext_horse_id, horse_name) from raceData.

    Never touches or emits scrape-time fields (`races`, `ranks`, `handicap`).
    """
    horses = []
    for entry in _extract_race_data(html_or_data):
        if not isinstance(entry, dict):
            continue
        horse_number, ext_horse_id, horse_name = _parse_entry_identity(entry)
        if horse_number is None and not ext_horse_id and not horse_name:
            continue
        horses.append({
            "horse_number": horse_number,
            "ext_horse_id": ext_horse_id,
            "horse_name": horse_name,
        })
    return horses


def parse_galop_page(html_text, race_date):
    """Parse pre-race workouts (`meeting_date < race_date`) from a Liderform galop page."""
    cutoff = _iso_date(race_date)
    workouts = []

    for entry in _extract_race_data(html_text):
        if not isinstance(entry, dict):
            continue
        horse_number, ext_horse_id, horse_name = _parse_entry_identity(entry)
        raw_workouts = entry.get("workouts")
        if not isinstance(raw_workouts, list):
            continue

        for w in raw_workouts:
            if not isinstance(w, dict):
                continue
            w_date = _opt_iso_date(w.get("meeting_date"))
            if w_date is None or not (w_date < cutoff):
                continue

            w_horse = w.get("horse") if isinstance(w.get("horse"), dict) else {}
            h_name = horse_name or _opt_str(w_horse.get("name"))
            if not h_name:
                continue
            raw_wid = w_horse.get("id")
            h_ext_id = ext_horse_id or (
                str(raw_wid).strip() if raw_wid is not None and str(raw_wid).strip() != "" else None
            )

            jockey_obj = w.get("jockey") if isinstance(w.get("jockey"), dict) else {}
            splits = {col: None for col in _GRAPH_COLS}
            graph = w.get("graph")
            if isinstance(graph, list):
                for pt in graph:
                    if not isinstance(pt, dict):
                        continue
                    try:
                        col = f"d{int(pt.get('label'))}"
                    except (TypeError, ValueError):
                        continue
                    if col in splits:
                        splits[col] = _workout_time(pt.get("value"))

            workouts.append({
                "horse_number": horse_number,
                "ext_horse_id": h_ext_id,
                "horse_name": h_name,
                "date": w_date,
                "city": _workout_city(w.get("track")),
                "kind": _opt_str(w.get("track_type")),
                "jockey": _opt_str(jockey_obj.get("name")),
                "kg": _opt_positive_float(jockey_obj.get("weight_kg")),
                "d1600": splits["d1600"],
                "d1400": splits["d1400"],
                "d1200": splits["d1200"],
                "d1000": splits["d1000"],
                "d800": splits["d800"],
                "d600": splits["d600"],
                "d400": splits["d400"],
                "d200": None,
                "effort": _opt_str(w.get("effort")),
                "going": _opt_str(w.get("going")),
                "inner_outer": _opt_str(w.get("inner_outer")),
            })

    return workouts


def detect_liderform_block(html_text, http_status=None, final_url=None):
    """Return human-readable block reason if Cloudflare/403 or BTK block/redirect is seen."""
    if final_url:
        host = urllib.parse.urlparse(str(final_url)).netloc.lower().split(":")[0]
        if host and host != "liderform.com.tr" and not host.endswith(".liderform.com.tr"):
            return f"BTK/dış yönlendirme ({host})"

    low = (html_text or "").lower()
    btk_markers = (
        "5651 sayılı",
        "erişim engellenmiştir",
        "btk.gov.tr",
        "ihbarweb.org.tr",
        "guvenlinet.org.tr",
    )
    if any(m in low for m in btk_markers):
        return f"BTK erişim engeli (HTTP {http_status})"

    cf_markers = (
        "just a moment...",
        "attention required! | cloudflare",
        "cf-browser-verification",
        "__cf_chl_",
        "cf-error-details",
    )
    if any(m in low for m in cf_markers) or ("cloudflare" in low and http_status in (403, 429, 503)):
        return f"Cloudflare engeli (HTTP {http_status})"

    if http_status in (401, 403, 429, 451, 503):
        return f"HTTP {http_status} erişim engeli"

    return None
