"""Archive daily Milliyet 'Altılı ganyanda bugün' tip images and raw article HTML."""
import argparse
import csv
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.milliyet_tips import AUTHOR_URL, image_ext, parse_article, parse_listing
from ganyan.tjk import get as tjk_get

IST_TZ = ZoneInfo("Europe/Istanbul")
CSV_COLUMNS = [
    "captured_at",
    "published",
    "url",
    "image_url",
    "image_file",
    "sha256",
    "bytes",
]
MIN_IMAGE_BYTES = 1000
_ISO_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _resolve_now(now) -> datetime.datetime:
    if now is None:
        return datetime.datetime.now(IST_TZ)
    if isinstance(now, str):
        now = datetime.datetime.fromisoformat(now)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST_TZ)
    return now.astimezone(IST_TZ)


def _article_date(published: str | None, dt_now: datetime.datetime) -> str:
    if published:
        m = _ISO_DATE_PREFIX_RE.match(published.strip())
        if m:
            try:
                datetime.date.fromisoformat(m.group(1))
                return m.group(1)
            except ValueError:
                pass
    return dt_now.strftime("%Y-%m-%d")


def _safe_get(get_fn, url: str) -> tuple[int | None, bytes]:
    try:
        st, body = get_fn(url)
    except Exception as exc:
        print(f"UYARI: ağ hatası ({url}): {exc}", flush=True)
        return None, b""
    return st, (body if isinstance(body, (bytes, bytearray)) else b"")


def _load_state(state_path: Path) -> dict[str, str]:
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception as exc:
        print(f"UYARI: state okunamadı ({state_path}): {exc}", flush=True)
    return {}


def _save_state(state_path: Path, state: dict[str, str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, state_path)


def run(out_dir="tips_data", max_articles: int = 3, now=None, get_fn=None) -> dict[str, int]:
    """Fetch author listing and archive up to max_articles unseen daily tip images."""
    dt_now = _resolve_now(now)
    captured_at = dt_now.isoformat(timespec="seconds")
    fetch = tjk_get if get_fn is None else get_fn

    base_dir = Path(out_dir)
    state_path = base_dir / "milliyet_state.json"
    csv_path = base_dir / "milliyet.csv"
    img_dir = base_dir / "milliyet"
    raw_dir = base_dir / "raw_milliyet"

    st_list, list_bytes = _safe_get(fetch, AUTHOR_URL)
    if st_list != 200 or not list_bytes:
        print(f"UYARI: yazar sayfası indirilemedi: {AUTHOR_URL} (durum={st_list})", flush=True)
        print("yeni: 0, atlanan: 0", flush=True)
        return {"new": 0, "skipped": 0}

    entries = parse_listing(list_bytes.decode("utf-8", "replace"))
    candidates = entries[: max(0, int(max_articles))]
    state = _load_state(state_path)

    new_count = 0
    skipped_count = 0

    for entry in candidates:
        url = entry["url"]
        if url in state:
            skipped_count += 1
            continue

        st_art, art_bytes = _safe_get(fetch, url)
        if st_art != 200 or not art_bytes:
            print(f"UYARI: makale indirilemedi: {url} (durum={st_art})", flush=True)
            skipped_count += 1
            continue

        info = parse_article(art_bytes.decode("utf-8", "replace"))
        image_url = info.get("image_url")
        if not image_url:
            print(f"UYARI: makalede resim bulunamadı: {url}", flush=True)
            skipped_count += 1
            continue

        st_img, img_bytes = _safe_get(fetch, image_url)
        img_bytes = bytes(img_bytes)
        ext = image_ext(img_bytes) if st_img == 200 and len(img_bytes) > MIN_IMAGE_BYTES else None
        if st_img != 200 or len(img_bytes) <= MIN_IMAGE_BYTES or ext is None:
            print(
                f"UYARI: resim geçersiz veya indirilemedi: {image_url} "
                f"(durum={st_img}, boyut={len(img_bytes)})",
                flush=True,
            )
            skipped_count += 1
            continue

        sha256 = hashlib.sha256(img_bytes).hexdigest()
        date_str = _article_date(info.get("published"), dt_now)
        img_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)

        img_path = img_dir / f"{date_str}.{ext}"
        if img_path.exists():
            if img_path.read_bytes() != img_bytes:
                ts = dt_now.strftime("%H%M%S")
                img_path = img_dir / f"{date_str}_{ts}.{ext}"
                idx = 2
                while img_path.exists() and img_path.read_bytes() != img_bytes:
                    img_path = img_dir / f"{date_str}_{ts}_{idx}.{ext}"
                    idx += 1
                if not img_path.exists():
                    img_path.write_bytes(img_bytes)
        else:
            img_path.write_bytes(img_bytes)

        raw_path = raw_dir / f"{date_str}.html.gz"
        raw_path.write_bytes(gzip.compress(bytes(art_bytes)))

        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with open(csv_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    "captured_at": captured_at,
                    "published": info.get("published") or "",
                    "url": url,
                    "image_url": image_url,
                    "image_file": f"milliyet/{img_path.name}",
                    "sha256": sha256,
                    "bytes": len(img_bytes),
                }
            )

        state[url] = sha256
        _save_state(state_path, state)
        new_count += 1

    print(f"yeni: {new_count}, atlanan: {skipped_count}", flush=True)
    return {"new": new_count, "skipped": skipped_count}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="tips_data")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--max-articles", type=int, default=3)
    args = ap.parse_args(argv)
    try:
        run(out_dir=args.out_dir, max_articles=args.max_articles)
    except Exception as exc:
        print(f"UYARI: beklenmeyen hata: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
