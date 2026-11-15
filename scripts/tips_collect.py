"""Daily collector for Sporx 'at-yarisi-hazir-kuponlar' tips."""
import argparse
import csv
import datetime
import gzip
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.tips import content_hash, parse_sporx_coupons
import ganyan.tjk as tjk
from ganyan.tjk import get

_ORIG_GET = get

IST_TZ = ZoneInfo("Europe/Istanbul")
SPORX_URL = "https://www.sporx.com/at-yarisi-hazir-kuponlar"
CSV_COLUMNS = [
    "captured_at",
    "tipster",
    "kind",
    "altili_name",
    "leg_no",
    "race_ref",
    "picks",
    "banko",
    "content_hash",
]


def _resolve_now(now=None):
    if now is None:
        return datetime.datetime.now(IST_TZ)
    if isinstance(now, str):
        dt = datetime.datetime.fromisoformat(now)
    elif isinstance(now, datetime.datetime):
        dt = now
    else:
        raise TypeError(f"Unsupported now type: {type(now)!r}")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST_TZ)
    return dt.astimezone(IST_TZ)


def collect_tips(out_dir="tips_data", url=SPORX_URL, now=None):
    """Fetch Sporx tips page and persist CSV + raw HTML.gz + state.json if changed."""
    fetcher = get if get is not _ORIG_GET else tjk.get
    try:
        status, raw_body = fetcher(url)
    except Exception as exc:
        print(f"HATA: ağ hatası ({exc})")
        return 0

    if status != 200 or not raw_body:
        print(f"HATA: ağ hatası (status={status})")
        return 0

    rows = parse_sporx_coupons(raw_body)
    if not rows:
        print("UYARI: parse 0 satır")
        return 0

    chash = content_hash(rows)
    out_path = Path(out_dir)
    state_path = out_path / "state.json"

    if state_path.exists():
        try:
            prev_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev_state = {}
        if prev_state.get("content_hash") == chash:
            print("değişmedi")
            return 0

    dt = _resolve_now(now)
    captured_at = dt.isoformat(timespec="seconds")
    date_part = dt.strftime("%Y-%m-%d")
    time_part = dt.strftime("%H%M%S")

    out_path.mkdir(parents=True, exist_ok=True)

    # (a) Append to <out-dir>/tips.csv with header if new/empty
    csv_path = out_path / "tips.csv"
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()
        for r in rows:
            writer.writerow({
                "captured_at": captured_at,
                "tipster": r["tipster"],
                "kind": r["kind"],
                "altili_name": r["altili_name"] if r["altili_name"] is not None else "",
                "leg_no": r["leg_no"] if r["leg_no"] is not None else "",
                "race_ref": r["race_ref"] if r["race_ref"] is not None else "",
                "picks": r["picks"] if r["picks"] is not None else "",
                "banko": r["banko"] if r["banko"] is not None else "",
                "content_hash": chash,
            })

    # (b) Write raw HTML to <out-dir>/raw/<YYYY-MM-DD>/<HHMMSS>.html.gz
    raw_dir = out_path / "raw" / date_part
    raw_dir.mkdir(parents=True, exist_ok=True)
    gz_path = raw_dir / f"{time_part}.html.gz"
    raw_bytes = raw_body if isinstance(raw_body, (bytes, bytearray)) else str(raw_body).encode("utf-8")
    with gzip.open(gz_path, "wb") as gz:
        gz.write(raw_bytes)

    # (c) Update <out-dir>/state.json
    state_payload = {
        "content_hash": chash,
        "captured_at": captured_at,
        "row_count": len(rows),
        "raw_file": f"raw/{date_part}/{time_part}.html.gz",
    }
    state_path.write_text(
        json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"yazıldı: {len(rows)} satır ({chash})")
    return 0


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(description="Sporx hazır kuponlar günlük toplayıcı")
    ap.add_argument("--out-dir", default="tips_data", help="Çıktı dizini (varsayılan: tips_data)")
    ap.add_argument("--once", action="store_true", help="Tek sefer çalıştır ve çık")
    args = ap.parse_args(argv)
    return collect_tips(out_dir=args.out_dir, now=now)


if __name__ == "__main__":
    raise SystemExit(main())
