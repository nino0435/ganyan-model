"""Download TJK daily result CSVs (domestic tracks only) for a date range.

Usage: python3 -I download_hist.py OUT_DIR START(YYYY-MM-DD) END(YYYY-MM-DD)
Skips files that already exist; sleeps between requests to stay polite.
"""
import sys, os, re, time, html, datetime, urllib.request, urllib.parse

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36"
DELAY = 0.5
DOMESTIC_CITIES = ["İstanbul", "İzmir", "Adana", "Bursa", "Ankara", "Antalya", "Şanlıurfa", "Elazığ", "Kocaeli", "Diyarbakır"]


def get(url, tries=3, timeout=30):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
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


def main():
    out, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out, exist_ok=True)
    d = datetime.date.fromisoformat(start)
    stop = datetime.date.fromisoformat(end)
    log = open(os.path.join(out, "_log.txt"), "a")
    use_cdn_fallback = False
    while d <= stop:
        if not use_cdn_fallback:
            ds = d.strftime("%d/%m/%Y")
            day_url = ("https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisSonuclari?QueryParameter_Tarih="
                       + urllib.parse.quote(ds, safe=""))
            st, body = get(day_url, tries=1, timeout=5)
            time.sleep(DELAY)
            if st is None:
                use_cdn_fallback = True
        if use_cdn_fallback:
            st = "CDN"
            cities = DOMESTIC_CITIES
        else:
            page = body.decode("utf-8", "replace")
            # Domestic tracks show "(NN. Y.G.)" next to the city name.
            cities = [html.unescape(c) for c in re.findall(r'<a id="([^"]+)" data-sehir-id="\d+"[^>]*>[^<]*Y\.G\.', page)]
        found = 0
        for city in dict.fromkeys(cities):
            fn = os.path.join(out, f"{d.isoformat()}_{city}.csv")
            if os.path.exists(fn):
                found += 1
                continue
            path = (f"/raporftp/TJKPDF/{d.year}/{d.isoformat()}/CSV/GunlukYarisSonuclari/"
                    f"{d.strftime('%d.%m.%Y')}-{city}-GunlukYarisSonuclari-TR.csv")
            st2, data = get("https://medya-cdn.tjk.org" + urllib.parse.quote(path))
            time.sleep(DELAY)
            if st2 == 200 and data:
                open(fn, "wb").write(data)
                found += 1
                log.write(f"{d} {city} {st2} {len(data)}\n")
            elif st2 != 404 or not use_cdn_fallback:
                log.write(f"{d} {city} {st2} {len(data)}\n")
        log.write(f"{d} day={st} cities={found}\n")
        log.flush()
        d += datetime.timedelta(days=1)
    log.write("DONE\n")


if __name__ == "__main__":
    main()
