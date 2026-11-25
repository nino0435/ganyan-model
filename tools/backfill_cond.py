"""Resumable backfill of TJK city-day going/weather blocks and per-race condition text.

Fetches the same XHR city results page the daily pipeline uses, but keeps only:
  * the raw `div.conditions-race` block (surface going + "Hava:" text), per (date, city)
  * per race: race number, post time, `race-config` text and the `aciklamaFancy` rules text
Everything lands in a separate SQLite file (default data/cond_backfill.sqlite); data/ganyan.db is
never touched here. Re-running skips pairs already stored, so it can be stopped and resumed.

Polite by design: a few workers, a fixed pause after every request, and an immediate stop on
HTTP 403/429 or a streak of server errors (it never keeps hammering a site that pushes back).
"""
import argparse
import datetime as dt
import gzip
import html
import os
import random
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ganyan.tjk import UA  # noqa: E402

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

BLOCK_RE = re.compile(r'class="conditions-race"[^>]*>(.*?)</div>', re.DOTALL)
RACE_SPLIT_RE = re.compile(r'<div id="(\d+)" sehir="[^"]*">')
RACE_NO_RE = re.compile(r"(\d+)\.\s*Ko[sş]u\s*(\d{1,2}[.:]\d{2})?")
CONFIG_RE = re.compile(r'<h3 class="race-config">(.*?)</h3>', re.DOTALL)
ACIKLAMA_RE = re.compile(r'class="aciklamaFancy"[^>]*title="([^"]*)"', re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")

SCHEMA = """
CREATE TABLE IF NOT EXISTS day (
    date TEXT NOT NULL, city TEXT NOT NULL, http INTEGER, bytes INTEGER,
    block TEXT, n_races INTEGER, fetched_at TEXT,
    PRIMARY KEY (date, city)
);
CREATE TABLE IF NOT EXISTS race (
    date TEXT NOT NULL, city TEXT NOT NULL, race_no INTEGER NOT NULL,
    kosu_kodu TEXT, post_time TEXT, config_text TEXT, aciklama TEXT,
    PRIMARY KEY (date, city, race_no)
);
"""


def clean_text(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", s or ""))).strip()


def city_url(date_str, city):
    ds = f"{date_str[8:10]}/{date_str[5:7]}/{date_str[:4]}"
    return (
        "https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukYarisSonuclari?"
        f"SehirId={SEHIR_ID_MAP[city]}&QueryParameter_Tarih={urllib.parse.quote(ds, safe='')}"
        f"&SehirAdi={urllib.parse.quote(city)}"
    )


def parse_page(txt):
    """Return (block_html_or_empty, [race dicts]) from a city results XHR page."""
    m = BLOCK_RE.search(txt)
    block = m.group(1).strip() if m else ""
    starts = [(mm.start(), mm.group(1)) for mm in RACE_SPLIT_RE.finditer(txt)]
    races = []
    for i, (pos, code) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(txt)
        seg = txt[pos:end]
        mno = RACE_NO_RE.search(clean_text(seg[: seg.find("</h3>") + 5] if "</h3>" in seg else seg[:600]))
        if not mno:
            continue
        mc = CONFIG_RE.search(seg)
        ma = ACIKLAMA_RE.search(seg)
        races.append(
            {
                "race_no": int(mno.group(1)),
                "kosu_kodu": code,
                "post_time": (mno.group(2) or "").replace(".", ":"),
                "config_text": clean_text(mc.group(1)) if mc else "",
                "aciklama": clean_text(ma.group(1)) if ma else "",
            }
        )
    return block, races


class Stop(Exception):
    pass


def fetch_page(date_str, city, state, tries=3, timeout=40):
    headers = {"User-Agent": UA, "X-Requested-With": "XMLHttpRequest", "Accept-Encoding": "gzip"}
    last = None
    for i in range(tries):
        if state["stop"].is_set():
            raise Stop("stop flag set")
        try:
            req = urllib.request.Request(city_url(date_str, city), headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                state["err_streak"] = 0
                return r.status, raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429):
                state["stop"].set()
                state["stop_reason"] = f"HTTP {e.code} ({date_str} {city}) - site pushes back, stopping"
                raise Stop(state["stop_reason"])
            if e.code == 404:
                return 404, ""
        except Exception as e:  # network hiccup / timeout / 5xx
            last = e
        state["err_streak"] += 1
        if state["err_streak"] >= 8:
            state["stop"].set()
            state["stop_reason"] = f"8 errors in a row, last: {last!r}"
            raise Stop(state["stop_reason"])
        time.sleep(2 * (i + 1))
    return None, ""


def worker(pairs, out_path, delay, state, lock):
    conn = sqlite3.connect(out_path, timeout=60)
    try:
        for d, c in pairs:
            if state["stop"].is_set():
                return
            try:
                code, txt = fetch_page(d, c, state)
            except Stop:
                return
            if code is None:
                time.sleep(delay)
                continue
            block, races = parse_page(txt) if code == 200 else ("", [])
            now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            with lock:
                conn.execute(
                    "INSERT OR REPLACE INTO day VALUES (?,?,?,?,?,?,?)",
                    (d, c, code, len(txt), block, len(races), now),
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO race VALUES (?,?,?,?,?,?,?)",
                    [
                        (d, c, r["race_no"], r["kosu_kodu"], r["post_time"], r["config_text"], r["aciklama"])
                        for r in races
                    ],
                )
                conn.commit()
                state["done"] += 1
                if state["done"] % 50 == 0:
                    el = time.time() - state["t0"]
                    rate = state["done"] / el
                    left = (state["total"] - state["done"]) / rate if rate else 0
                    print(
                        f"[{time.strftime('%H:%M:%S')}] {state['done']}/{state['total']} "
                        f"son={d} {c} ({rate:.2f}/sn, kalan ~{left/60:.0f} dk)",
                        flush=True,
                    )
            time.sleep(delay + random.uniform(0, 0.3))
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/ganyan.db", help="source of (date, city) pairs (read-only)")
    ap.add_argument("--out", default="data/cond_backfill.sqlite")
    ap.add_argument("--from", dest="d_from", default="2013-01-01")
    ap.add_argument("--to", dest="d_to", default="2024-10-24")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--delay", type=float, default=1.0, help="pause (s) after every request, per worker")
    ap.add_argument("--limit", type=int, default=0, help="only first N pending pairs (0 = all)")
    ap.add_argument("--sample", type=int, default=0, help="random N pending pairs instead of newest-first")
    ap.add_argument("--pairs-from-file", default="", help="optional file with 'YYYY-MM-DD<TAB>city' lines")
    args = ap.parse_args()

    src = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=60)
    if args.pairs_from_file:
        with open(args.pairs_from_file, encoding="utf-8") as f:
            pairs = [tuple(ln.rstrip("\n").split("\t")) for ln in f if ln.strip()]
    else:
        pairs = src.execute(
            "SELECT DISTINCT date, city FROM races WHERE status='result' AND date BETWEEN ? AND ? "
            "ORDER BY date DESC, city",
            (args.d_from, args.d_to),
        ).fetchall()
    src.close()
    unknown = sorted({c for _, c in pairs if c not in SEHIR_ID_MAP})
    if unknown:
        print("SehirId bilinmeyen şehirler atlandı:", unknown)
    pairs = [(d, c) for d, c in pairs if c in SEHIR_ID_MAP]

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out = sqlite3.connect(args.out, timeout=60)
    out.executescript(SCHEMA)
    have = {(d, c) for d, c in out.execute("SELECT date, city FROM day WHERE http IN (200, 404)")}
    out.close()
    pending = [p for p in pairs if p not in have]
    if args.sample:
        random.Random(0).shuffle(pending)
        pending = pending[: args.sample]
    elif args.limit:
        pending = pending[: args.limit]
    print(f"toplam çift={len(pairs)}  zaten var={len(pairs) - len([p for p in pairs if p not in have])}  "
          f"indirilecek={len(pending)}  işçi={args.workers}  bekleme={args.delay}s", flush=True)
    if not pending:
        return

    state = {
        "stop": threading.Event(), "stop_reason": "", "err_streak": 0,
        "done": 0, "total": len(pending), "t0": time.time(),
    }
    lock = threading.Lock()
    chunks = [pending[i :: args.workers] for i in range(args.workers)]
    threads = [threading.Thread(target=worker, args=(ch, args.out, args.delay, state, lock)) for ch in chunks]
    for t in threads:
        t.start()
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        state["stop"].set()
        state["stop_reason"] = "KeyboardInterrupt"
        for t in threads:
            t.join()
    el = time.time() - state["t0"]
    print(f"BİTTİ: indirilen={state['done']}/{state['total']} süre={el/60:.1f} dk "
          f"{'DURDU: ' + state['stop_reason'] if state['stop'].is_set() else 'tamam'}", flush=True)
    sys.exit(2 if state["stop"].is_set() else 0)


if __name__ == "__main__":
    main()
