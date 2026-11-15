"""Daily collector for hipodrom.com author coupons, race comments, and program list."""
from __future__ import annotations

import argparse
import csv
import datetime
import gzip
import hashlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.hipodrom_tips import (
    COMMENTS_URL,
    COUPONS_URL,
    IST_TZ,
    PROGRAMS_URL,
    coupon_hash,
    parse_comments,
    parse_coupons,
    parse_programs,
)
from ganyan.tjk import get as tjk_get

ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("coupons", COUPONS_URL),
    ("comments", COMMENTS_URL),
    ("programs", PROGRAMS_URL),
)

COUPON_FIELDS = [
    "captured_at",
    "coupon_id",
    "author",
    "author_id",
    "coupon_name",
    "game_type",
    "hippodrome",
    "foreign",
    "program_id",
    "race_date",
    "start_time",
    "created_at",
    "status",
    "leg_no",
    "picks",
    "coupon_hash",
]

COMMENT_FIELDS = [
    "captured_at",
    "comment_id",
    "program_id",
    "race_no",
    "author",
    "author_id",
    "picks",
    "text_len",
    "text_hash",
]

PROGRAM_FIELDS = [
    "captured_at",
    "program_id",
    "hippodrome",
    "name",
    "foreign",
]


def _resolve_now(now: datetime.datetime | str | int | float | None) -> datetime.datetime:
    """Normalize injected `now` into a timezone-aware Europe/Istanbul datetime."""
    if now is None:
        return datetime.datetime.now(IST_TZ)
    if isinstance(now, datetime.datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=IST_TZ)
        return now.astimezone(IST_TZ)
    if isinstance(now, str):
        dt = datetime.datetime.fromisoformat(now)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=IST_TZ)
        return dt.astimezone(IST_TZ)
    if isinstance(now, (int, float)) and not isinstance(now, bool):
        return datetime.datetime.fromtimestamp(now, tz=IST_TZ)
    raise TypeError(f"Unsupported now value: {now!r}")


def _load_state(state_path: Path) -> dict[str, Any]:
    """Load collector state from disk or return clean empty state."""
    empty = {"raw": {}, "coupons": {}, "comments": {}, "programs": []}
    if not state_path.exists():
        return empty
    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"UYARI: state okunamadı ({exc}), sıfırdan başlanıyor")
        return empty
    if not isinstance(loaded, dict):
        return empty

    raw = loaded.get("raw")
    coupons = loaded.get("coupons")
    comments = loaded.get("comments")
    programs = loaded.get("programs")
    return {
        "raw": {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {},
        "coupons": {str(k): str(v) for k, v in coupons.items()} if isinstance(coupons, dict) else {},
        "comments": {str(k): str(v) for k, v in comments.items()} if isinstance(comments, dict) else {},
        "programs": list(programs) if isinstance(programs, list) else [],
    }


def _save_state_atomic(state_path: Path, state: dict[str, Any]) -> None:
    """Atomically write state JSON in UTF-8."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=state_path.parent, prefix=".hipodrom_state_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_name, state_path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _append_csv(
    csv_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
    create_if_missing: bool = False,
) -> None:
    """Append rows to CSV, writing header if file does not yet exist."""
    exists = csv_path.exists() and csv_path.stat().st_size > 0
    if not rows and (exists or not create_if_missing):
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if exists else "w"
    with open(csv_path, mode, encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        if not exists:
            writer.writeheader()
        if rows:
            writer.writerows(rows)


def _archive_bytes(raw_bytes: bytes, doc: dict[str, Any]) -> bytes:
    """Strip any `au.em` email fields before archiving raw JSON so emails are never saved."""
    cleaned_data = []
    has_em = False
    for item in doc.get("data", []):
        if isinstance(item, dict) and isinstance(item.get("au"), dict) and "em" in item["au"]:
            has_em = True
            au_clean = {k: v for k, v in item["au"].items() if k != "em"}
            cleaned_data.append({**item, "au": au_clean})
        else:
            cleaned_data.append(item)
    if not has_em:
        return raw_bytes
    cleaned_doc = {**doc, "data": cleaned_data}
    return json.dumps(cleaned_doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _fetch_endpoint(
    ep_name: str,
    url: str,
    fetcher: Callable[[str], Any],
) -> tuple[bytes, dict[str, Any]] | None:
    """Fetch one endpoint and validate HTTP 200 + JSON envelope."""
    try:
        resp = fetcher(url)
    except Exception as exc:
        print(f"UYARI: {ep_name} ağ hatası: {exc}")
        return None

    if isinstance(resp, tuple) and len(resp) == 2:
        status, body = resp
    elif isinstance(resp, (bytes, bytearray)):
        status, body = 200, bytes(resp)
    elif isinstance(resp, str):
        status, body = 200, resp.encode("utf-8")
    else:
        print(f"UYARI: {ep_name} geçersiz yanıt biçimi")
        return None

    if status != 200:
        print(f"UYARI: {ep_name} HTTP {status}")
        return None

    if isinstance(body, str):
        raw_bytes = body.encode("utf-8")
    elif isinstance(body, (bytes, bytearray)):
        raw_bytes = bytes(body)
    else:
        print(f"UYARI: {ep_name} boş/geçersiz gövde")
        return None

    if not raw_bytes:
        print(f"UYARI: {ep_name} boş yanıt")
        return None

    try:
        doc = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        print(f"UYARI: {ep_name} geçersiz JSON")
        return None

    if not isinstance(doc, dict) or doc.get("success") is not True or not isinstance(doc.get("data"), list):
        print(f"UYARI: {ep_name} success=false veya data eksik")
        return None

    return raw_bytes, doc


def run(
    out_dir: str | os.PathLike[str],
    now: datetime.datetime | str | int | float | None = None,
    get_fn: Callable[[str], Any] | None = None,
    sleep_fn: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """Collect hipodrom coupons, comments, and programs into `out_dir`."""
    out_path = Path(out_dir)
    now_dt = _resolve_now(now)
    captured_at = now_dt.isoformat(timespec="seconds")
    day_str = now_dt.strftime("%Y-%m-%d")
    hms_str = now_dt.strftime("%H%M%S")

    fetcher = tjk_get if get_fn is None else get_fn
    sleeper = time.sleep if sleep_fn is None else sleep_fn

    state_path = out_path / "hipodrom_state.json"
    state = _load_state(state_path)
    raw_state: dict[str, str] = dict(state["raw"])
    coupons_state: dict[str, str] = dict(state["coupons"])
    comments_state: dict[str, str] = dict(state["comments"])
    programs_state: list[Any] = list(state["programs"])

    raw_to_write: list[tuple[str, bytes]] = []
    coupon_csv_rows: list[dict[str, Any]] = []
    comment_csv_rows: list[dict[str, Any]] = []
    program_csv_rows: list[dict[str, Any]] = []
    succeeded: set[str] = set()

    new_coupons = 0
    new_comments = 0
    new_programs = 0

    for idx, (ep_name, url) in enumerate(ENDPOINTS):
        if idx > 0:
            sleeper(1.0)
        fetched = _fetch_endpoint(ep_name, url, fetcher)
        if fetched is None:
            continue
        raw_bytes, doc = fetched
        succeeded.add(ep_name)

        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        if raw_state.get(ep_name) != raw_sha:
            raw_state[ep_name] = raw_sha
            raw_to_write.append((ep_name, _archive_bytes(raw_bytes, doc)))

        if ep_name == "coupons":
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in parse_coupons(doc):
                grouped.setdefault(str(row["coupon_id"]), []).append(row)
            for cid, leg_rows in grouped.items():
                chash = coupon_hash(leg_rows)
                if coupons_state.get(cid) != chash:
                    coupons_state[cid] = chash
                    new_coupons += 1
                    for lr in leg_rows:
                        coupon_csv_rows.append({"captured_at": captured_at, **lr, "coupon_hash": chash})

        elif ep_name == "comments":
            for row in parse_comments(doc):
                cid = str(row["comment_id"])
                thash = row["text_hash"]
                if comments_state.get(cid) != thash:
                    comments_state[cid] = thash
                    new_comments += 1
                    comment_csv_rows.append({"captured_at": captured_at, **row})

        elif ep_name == "programs":
            known_programs = set(programs_state)
            for row in parse_programs(doc):
                pid = row["program_id"]
                if pid not in known_programs:
                    known_programs.add(pid)
                    programs_state.append(pid)
                    new_programs += 1
                    program_csv_rows.append({"captured_at": captured_at, **row})

    changed = bool(raw_to_write or coupon_csv_rows or comment_csv_rows or program_csv_rows)
    if not changed:
        print("değişmedi")
        return {"coupons": 0, "comments": 0, "programs": 0, "changed": False}

    out_path.mkdir(parents=True, exist_ok=True)

    if raw_to_write:
        raw_dir = out_path / "raw_hipodrom" / day_str
        raw_dir.mkdir(parents=True, exist_ok=True)
        for ep_name, raw_bytes in raw_to_write:
            gz_path = raw_dir / f"{hms_str}_{ep_name}.json.gz"
            with gzip.open(gz_path, "wb") as gz_f:
                gz_f.write(raw_bytes)

    _append_csv(
        out_path / "hipodrom_coupons.csv",
        COUPON_FIELDS,
        coupon_csv_rows,
        create_if_missing=("coupons" in succeeded),
    )
    _append_csv(
        out_path / "hipodrom_comments.csv",
        COMMENT_FIELDS,
        comment_csv_rows,
        create_if_missing=("comments" in succeeded),
    )
    _append_csv(
        out_path / "hipodrom_programs.csv",
        PROGRAM_FIELDS,
        program_csv_rows,
        create_if_missing=("programs" in succeeded),
    )

    new_state = {
        "raw": raw_state,
        "coupons": coupons_state,
        "comments": comments_state,
        "programs": programs_state,
    }
    _save_state_atomic(state_path, new_state)

    print(f"kupon: {new_coupons} yeni, yorum: {new_comments} yeni, program: {new_programs} yeni")
    return {
        "coupons": new_coupons,
        "comments": new_comments,
        "programs": new_programs,
        "changed": True,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collect hipodrom.com daily coupons and comments.")
    ap.add_argument("--out-dir", default="tips_data", help="Output directory (default: tips_data)")
    args = ap.parse_args(argv)
    try:
        run(args.out_dir)
    except Exception as exc:
        print(f"UYARI: beklenmeyen hata: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
