"""TJK network helpers: polite fetching, CDN URLs, domestic city discovery."""
import datetime
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36"
DELAY = 0.5
DOMESTIC_CITIES = [
    "İstanbul",
    "İzmir",
    "Adana",
    "Bursa",
    "Ankara",
    "Antalya",
    "Şanlıurfa",
    "Elazığ",
    "Kocaeli",
    "Diyarbakır",
]


def get(url, tries=3, timeout=30, extra_headers=None):
    """Polite HTTP GET with retry and 404 fast-exit."""
    headers = {"User-Agent": UA}
    if extra_headers:
        headers.update(extra_headers)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, b""
            time.sleep(2 * (i + 1))
        except Exception:
            if tries == 1:
                break
            time.sleep(2 * (i + 1))
    return None, b""


def results_csv_url(date, city, cache_bust=None):
    """Build TJK CDN URL for daily results CSV."""
    d = datetime.date.fromisoformat(str(date)) if isinstance(date, str) else date
    path = (
        f"/raporftp/TJKPDF/{d.year}/{d.isoformat()}/CSV/GunlukYarisSonuclari/"
        f"{d.strftime('%d.%m.%Y')}-{city}-GunlukYarisSonuclari-TR.csv"
    )
    url = "https://medya-cdn.tjk.org" + urllib.parse.quote(path)
    if cache_bust is not None:
        url += f"?t={cache_bust}"
    return url


def program_csv_url(date, city, cache_bust=None):
    """Build TJK CDN URL for daily program CSV."""
    d = datetime.date.fromisoformat(str(date)) if isinstance(date, str) else date
    path = (
        f"/raporftp/TJKPDF/{d.year}/{d.isoformat()}/CSV/GunlukYarisProgrami/"
        f"{d.strftime('%d.%m.%Y')}-{city}-GunlukYarisProgrami-TR.csv"
    )
    url = "https://medya-cdn.tjk.org" + urllib.parse.quote(path)
    if cache_bust is not None:
        url += f"?t={cache_bust}"
    return url


def domestic_cities(date, page_type="GunlukYarisSonuclari", timeout=5):
    """Return list of domestic cities for a date from TJK day page, or fallback to DOMESTIC_CITIES."""
    d = datetime.date.fromisoformat(str(date)) if isinstance(date, str) else date
    ds = d.strftime("%d/%m/%Y")
    day_url = (
        f"https://www.tjk.org/TR/YarisSever/Info/Page/{page_type}?QueryParameter_Tarih="
        + urllib.parse.quote(ds, safe="")
    )
    st, body = get(day_url, tries=1, timeout=timeout)
    time.sleep(DELAY)
    if st == 200 and body:
        page = body.decode("utf-8", "replace")
        cities = [
            html.unescape(c)
            for c in re.findall(r'<a id="([^"]+)" data-sehir-id="\d+"[^>]*>[^<]*Y\.G\.', page)
        ]
        if cities:
            return list(dict.fromkeys(cities))
    return list(DOMESTIC_CITIES)
