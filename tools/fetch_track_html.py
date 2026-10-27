"""Resumable downloader for TJK daily city conditions-race HTML blocks (§1.3b)."""
import gzip
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ganyan.tjk import DELAY, UA

SEHIR_ID_MAP = {
    "Adana": 1,
    "İzmir": 2,
    "İstanbul": 3,
    "Bursa": 4,
    "Ankara": 5,
    "Şanlıurfa": 6,
    "Elazığ": 7,
    "Diyarbakır": 8,
    "Kocaeli": 9,
    "Antalya": 10,
}


def fetch_conditions_block(date_str, city, tries=3, timeout=30):
    """Fetch city results XHR page (gzipped) and extract the div.conditions-race inner HTML."""
    sid = SEHIR_ID_MAP[city]
    ds = f"{date_str[8:10]}/{date_str[5:7]}/{date_str[:4]}"
    q_ds = urllib.parse.quote(ds, safe="")
    q_c = urllib.parse.quote(city)
    url = (
        f"https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukYarisSonuclari?"
        f"SehirId={sid}&QueryParameter_Tarih={q_ds}&SehirAdi={q_c}"
    )
    headers = {
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Encoding": "gzip",
    }
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                txt = raw.decode("utf-8", "replace")
                m = re.search(r'class="conditions-race"[^>]*>(.*?)</div>', txt, re.DOTALL)
                return m.group(1).strip() if m else ""
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def main():
    out_dir = "data/raw/html_cond"
    os.makedirs(out_dir, exist_ok=True)
    conn = sqlite3.connect("data/ganyan.db", timeout=30)
    pairs = conn.execute(
        "SELECT DISTINCT date, city FROM races WHERE status = 'result' ORDER BY date, city"
    ).fetchall()
    conn.close()

    total = len(pairs)
    downloaded = 0
    skipped = 0
    failed = 0
    t0 = time.time()

    for idx, (d, c) in enumerate(pairs, 1):
        fn = os.path.join(out_dir, f"{d}_{c}.html")
        if os.path.exists(fn) and os.path.getsize(fn) > 0:
            skipped += 1
            continue
        block = fetch_conditions_block(d, c)
        time.sleep(DELAY)
        if block is not None:
            with open(fn, "w", encoding="utf-8") as f:
                f.write(block)
            downloaded += 1
        else:
            failed += 1
        if (downloaded + failed) % 50 == 0:
            el = time.time() - t0
            print(
                f"Track HTML progress: {idx}/{total} (downloaded={downloaded}, skipped={skipped}, failed={failed}, elapsed={el:.0f}s)",
                flush=True,
            )

    print(
        f"DONE: total={total}, downloaded={downloaded}, skipped={skipped}, failed={failed}, elapsed={time.time()-t0:.0f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
