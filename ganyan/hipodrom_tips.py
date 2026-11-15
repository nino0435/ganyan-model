"""Pure parsers and hashing helpers for hipodrom.com tips endpoints."""
from __future__ import annotations

import datetime
import hashlib
import html
import json
import re
from collections.abc import Iterable
from typing import Any
from zoneinfo import ZoneInfo

IST_TZ = ZoneInfo("Europe/Istanbul")

COUPONS_URL = "https://api.hipodrom.com/api/web/v1/tjk/predefined-coupons"
COMMENTS_URL = "https://api.hipodrom.com/api/web/v1/tjk/all-comments"
PROGRAMS_URL = "https://api.hipodrom.com/api/web/v1/tjk/predefined-coupon/hippodrome-list"

_STRONG_RE = re.compile(r"<strong\b[^>]*>(.*?)</strong>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_PICK_NUM_RE = re.compile(r"^\s*\(\s*(\d+)\s*\)")


def _decode_doc(payload: bytes | bytearray | str | dict[str, Any]) -> dict[str, Any] | None:
    """Decode bytes/str/dict payload and validate top-level hipodrom envelope."""
    if isinstance(payload, (bytes, bytearray)):
        try:
            doc = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
    elif isinstance(payload, str):
        try:
            doc = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return None
    elif isinstance(payload, dict):
        doc = payload
    else:
        return None

    if not isinstance(doc, dict) or doc.get("success") is not True:
        return None
    if not isinstance(doc.get("data"), list):
        return None
    return doc


def _clean_author(au: Any) -> tuple[str, int | str | None]:
    """Extract cleaned author full name and author_id without touching email."""
    if not isinstance(au, dict):
        return "", None
    fi = str(au.get("fi") or "").strip()
    la = str(au.get("la") or "").strip()
    author = " ".join(f"{fi} {la}".split())
    aid = au.get("id")
    if isinstance(aid, bool):
        aid = None
    return author, aid


def _ms_to_ist_date(ms: Any) -> str:
    """Convert epoch milliseconds to YYYY-MM-DD in Europe/Istanbul."""
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        return ""
    try:
        return datetime.datetime.fromtimestamp(ms / 1000.0, tz=IST_TZ).date().isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def _ms_to_ist_iso(ms: Any) -> str:
    """Convert epoch milliseconds to ISO-8601 seconds timestamp in Europe/Istanbul."""
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        return ""
    try:
        return datetime.datetime.fromtimestamp(ms / 1000.0, tz=IST_TZ).isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return ""


def parse_coupons(payload: bytes | bytearray | str | dict[str, Any]) -> list[dict[str, Any]]:
    """Parse predefined-coupons into one row per coupon leg (1-based list position)."""
    doc = _decode_doc(payload)
    if doc is None:
        return []

    rows: list[dict[str, Any]] = []
    for item in doc["data"]:
        if not isinstance(item, dict):
            continue
        coupon_id = item.get("id")
        lgr = item.get("lgr")
        if not coupon_id or not isinstance(lgr, list) or not lgr:
            continue

        author, author_id = _clean_author(item.get("au"))
        hpd = item.get("hpd") if isinstance(item.get("hpd"), dict) else {}
        program_id = item.get("ri")
        if isinstance(program_id, bool):
            program_id = None

        base = {
            "coupon_id": str(coupon_id),
            "author": author,
            "author_id": author_id,
            "coupon_name": str(item.get("n") or "").strip(),
            "game_type": str(item.get("gt") or "").strip(),
            "hippodrome": str(hpd.get("ky") or "").strip(),
            "foreign": bool(hpd.get("isf", False)),
            "program_id": program_id,
            "race_date": _ms_to_ist_date(item.get("rd")),
            "start_time": str(item.get("rst") or "").strip(),
            "created_at": _ms_to_ist_iso(item.get("cd")),
            "status": str(item.get("s") or "").strip(),
        }

        coupon_rows: list[dict[str, Any]] = []
        valid_legs = True
        for leg_no, leg in enumerate(lgr, start=1):
            if not isinstance(leg, dict) or not isinstance(leg.get("rns"), list):
                valid_legs = False
                break
            picks = ",".join(str(n) for n in leg["rns"] if not isinstance(n, bool) and n is not None)
            coupon_rows.append({**base, "leg_no": leg_no, "picks": picks})

        if valid_legs:
            rows.extend(coupon_rows)

    return rows


def parse_comments(payload: bytes | bytearray | str | dict[str, Any]) -> list[dict[str, Any]]:
    """Parse all-comments without retaining comment body text."""
    doc = _decode_doc(payload)
    if doc is None:
        return []

    rows: list[dict[str, Any]] = []
    for item in doc["data"]:
        if not isinstance(item, dict):
            continue
        comment_id = item.get("i")
        if comment_id is None or isinstance(comment_id, bool):
            continue

        co_raw = item.get("co")
        co = co_raw if isinstance(co_raw, str) else ("" if co_raw is None else str(co_raw))
        author, author_id = _clean_author(item.get("au"))

        seen_nums: list[str] = []
        seen_set: set[str] = set()
        for inner in _STRONG_RE.findall(co):
            inner_text = html.unescape(_TAG_RE.sub("", inner))
            m = _PICK_NUM_RE.match(inner_text)
            if m:
                num_str = str(int(m.group(1)))
                if num_str not in seen_set:
                    seen_set.add(num_str)
                    seen_nums.append(num_str)

        plain_text = html.unescape(_TAG_RE.sub("", co)).strip()
        text_hash = hashlib.sha256(co.encode("utf-8")).hexdigest()[:16]

        program_id = item.get("ri")
        if isinstance(program_id, bool):
            program_id = None
        race_no = item.get("rn")
        if isinstance(race_no, bool):
            race_no = None

        rows.append(
            {
                "comment_id": comment_id,
                "program_id": program_id,
                "race_no": race_no,
                "author": author,
                "author_id": author_id,
                "picks": ",".join(seen_nums),
                "text_len": len(plain_text),
                "text_hash": text_hash,
            }
        )

    return rows


def parse_programs(payload: bytes | bytearray | str | dict[str, Any]) -> list[dict[str, Any]]:
    """Parse hippodrome-list program entries."""
    doc = _decode_doc(payload)
    if doc is None:
        return []

    rows: list[dict[str, Any]] = []
    for item in doc["data"]:
        if not isinstance(item, dict):
            continue
        program_id = item.get("ri")
        if program_id is None or isinstance(program_id, bool):
            continue
        hpd = item.get("hpd") if isinstance(item.get("hpd"), dict) else {}
        rows.append(
            {
                "program_id": program_id,
                "hippodrome": str(hpd.get("ky") or "").strip(),
                "name": str(hpd.get("n") or "").strip(),
                "foreign": bool(hpd.get("isf", False)),
            }
        )

    return rows


def _leg_sort_key(row: dict[str, Any]) -> int:
    val = row.get("leg_no", 0)
    if isinstance(val, bool):
        return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def coupon_hash(rows_of_one_coupon: Iterable[dict[str, Any]]) -> str:
    """Return first 16 hex chars of SHA-256 over all leg picks of one coupon."""
    ordered = sorted(
        (r for r in rows_of_one_coupon if isinstance(r, dict)),
        key=_leg_sort_key,
    )
    joined = "|".join(str(r.get("picks", "")) for r in ordered)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
