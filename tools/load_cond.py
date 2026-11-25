"""Parse TJK city-day going/weather blocks from cond_backfill.sqlite and load empty ganyan.db cells."""
import argparse
from collections import Counter
import hashlib
import html
import os
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ganyan.track import (  # noqa: E402
    TRACK_COND_MAP,
    extract_cond_key,
    normalize_track_cond,
    parse_conditions_html,
)
from tools.backfill_cond import SEHIR_ID_MAP  # noqa: E402

MIN_APPLY_COVERAGE = 0.995


class CoverageError(RuntimeError):
    """Raised when backfill coverage over known-SehirId result days is below threshold."""

DAY_COND_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS day_cond (
    date TEXT NOT NULL,
    city TEXT NOT NULL,
    cim_raw TEXT,
    kum_raw TEXT,
    sentetik_raw TEXT,
    hava_raw TEXT,
    temp_c REAL,
    rh REAL,
    sky TEXT,
    windy INTEGER,
    PRIMARY KEY (date, city)
);
"""

_TR_LOWER_TABLE = str.maketrans({"I": "ı", "İ": "i"})

_RACE_WEATHER_SPAN_RE = re.compile(r'<span\s+class="raceWeather\w+"[^>]*>.*?</span>', re.DOTALL | re.IGNORECASE)
_FLOAT_RIGHT_SPAN_RE = re.compile(r'<span[^>]*float\s*:\s*right[^>]*>.*?(?:</span>|$)', re.DOTALL | re.IGNORECASE)
_ANCHOR_RE = re.compile(r"<a\b[^>]*>.*?</a>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_HAVA_PREFIX_RE = re.compile(r"hava\s*[:;.]?\s*(.*)", re.IGNORECASE)
_HAVA_HINT_RE = re.compile(
    r"\b(?:nem|sıcaklık|sicaklik|bulut\w*|açık|acik|yağmur\w*|yagmur\w*|yağış\w*|yagis\w*|sağanak|saganak|sağnak|sagnak|karlı|karli|sisli|rüzg[aâ]r\w*|ruzg[aâ]r\w*)\b|°\s*c",
    re.IGNORECASE,
)

_RH_PATTERNS = (
    re.compile(r"\bnem\s*[:=,./\s]*[%&]?\s*(\d{1,3}(?:[.,]\d+)?)\s*%?"),
    re.compile(r"[%&]\s*(\d{1,3}(?:[.,]\d+)?)\s*nem\b"),
    re.compile(r"%\s*(\d{1,3}(?:[.,]\d+)?)"),
    re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%"),
)

_WIND_CALM_RE = re.compile(r"\b(?:rüzgarsız|ruzgarsiz|rüzgar\s*yok|ruzgar\s*yok)\b")
_WIND_SPEED_RE = re.compile(r"(?:rüzg[aâ]r|ruzg[aâ]r)[^,;)]*?(\d+(?:[.,]\d+)?)\s*km(?:/(?:sa|s|h))?")
_WIND_WORD_RE = re.compile(r"(?:rüzg[aâ]r|ruzg[aâ]r|fırtın|firtin|esintil|lodos|poyraz)")
_WIND_STRIP_RE = re.compile(
    r",?\s*\(?\s*(?:rüzg[aâ]r(?:sız|lı|li)?|ruzg[aâ]r(?:siz|li)?|fırtın\w*|firtin\w*|esintil\w*|lodos|poyraz)\s*\)?"
)
_KM_STRIP_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*km(?:/(?:sa|s|h))?\b")

_TEMP_PATTERNS = (
    re.compile(
        r"(?<![a-zçğıöşü0-9])(-?\d{1,2}(?:[.,]\d+)?)\s*"
        r"(?:°\s*c|c\s*°|['\"´`’]\s*c|derece|°|['\"´`’]|c(?![a-zçğıöşü0-9]))"
    ),
    re.compile(r"(?:sıcaklık|sicaklik)\s*[:=]?\s*(-?\d{1,2}(?:[.,]\d+)?)"),
    re.compile(r"(?<![a-zçğıöşü0-9.])(-?\d{1,2}(?:[.,]\d+)?)(?=\s*[,;]|$|\s+[a-zçğıöşü])"),
)

_SKY_RULES = (
    ("karli", re.compile(r"kar\s*yağ|karla\s*karışık|karlı|karli|sulu\s*kar|\bkar\b|tipi")),
    (
        "yagisli",
        re.compile(r"yağmur|yagmur|yağış|yagis|sağanak|saganak|sağnak|sagnak|çisele|cisele|g\.g\.s\.|gök\s*gürültü|gok\s*gurultu|dolu"),
    ),
    ("sisli", re.compile(r"sisli|\bsis\b|puslu|\bpus\b|dumanlı|dumanli|tozlu")),
    ("parcali_bulutlu", re.compile(r"parçalı|parcali|p\.\s*bulut|par\.\s*bulut")),
    ("cok_bulutlu", re.compile(r"çok\s*bulut|cok\s*bulut|ç\.\s*bulut|kapalı|kapali|yoğun\s*bulut|yogun\s*bulut")),
    ("az_bulutlu", re.compile(r"az\s*bulut|azbulut|a\.\s*bulut|hafif\s*bulut")),
    ("bulutlu", re.compile(r"bulutlu|\bbulut\b")),
    ("acik", re.compile(r"açık|acik|güneşli|gunesli|güneş|gunes|berrak")),
)

_NOISE_RESIDUAL_RE = re.compile(r"\b(?:hava|sıcaklık|sicaklik|gökyüzü|gokyuzu|nem|derece)\b")


def tr_lower(text):
    """Turkish-safe lowercase (I -> ı, İ -> i) without combining dot artifacts."""
    if text is None:
        return ""
    return str(text).translate(_TR_LOWER_TABLE).lower().replace("\u0307", "")


def ensure_day_cond_table(conn):
    """Create day_cond table idempotently in ganyan.db."""
    conn.executescript(DAY_COND_SCHEMA_SQL)
    conn.commit()


def _open_ro_sqlite(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"SQLite dosyası bulunamadı: {path}")
    conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True, timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
    except sqlite3.Error:
        pass
    return conn


def _to_float_tr(num_str):
    return float(str(num_str).replace(",", ".").strip())


def extract_hava_raw(block):
    """Extract cleaned 'Hava:' text portion from a div.conditions-race HTML block."""
    if not block:
        return None
    s = _RACE_WEATHER_SPAN_RE.sub(" ", str(block))
    s = _FLOAT_RIGHT_SPAN_RE.sub(" ", s)
    s = _ANCHOR_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = re.sub(r"\bPDF\s*B[üu]lten\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None

    m = _HAVA_PREFIX_RE.search(s)
    if m:
        val = re.sub(r"^[,;:\s]+|[,;:\s]+$", "", m.group(1)).strip()
        return val if val else None

    if _HAVA_HINT_RE.search(tr_lower(s)):
        val = re.sub(r"^[,;:\s]+|[,;:\s]+$", "", s).strip()
        return val if val else None
    return None


def parse_hava_text(hava_raw):
    """Parse temp_c, rh, sky, windy, and sky_residual from cleaned TJK weather text."""
    if not hava_raw or not str(hava_raw).strip():
        return {"temp_c": None, "rh": None, "sky": None, "windy": None, "sky_residual": None}

    work = tr_lower(re.sub(r"\s+", " ", html.unescape(str(hava_raw))).strip())

    # 1. Relative humidity (rh) — extract and strip before temperature to avoid digit collisions
    rh = None
    for pat in _RH_PATTERNS:
        m = pat.search(work)
        if m:
            val = _to_float_tr(m.group(1))
            if 0.0 <= val <= 100.0:
                rh = val
                work = f"{work[:m.start()]} {work[m.end():]}"
                break

    # 2. Wind flag (windy) — extract and strip before temperature so '29 km/sa' is not read as temp
    if _WIND_CALM_RE.search(work):
        windy = 0
    else:
        ms = _WIND_SPEED_RE.search(work)
        if ms:
            windy = 1 if _to_float_tr(ms.group(1)) >= 15.0 else 0
        elif _WIND_WORD_RE.search(work):
            windy = 1
        else:
            windy = 0
    work = _WIND_SPEED_RE.sub(" ", work)
    work = _KM_STRIP_RE.sub(" ", work)
    work = _WIND_STRIP_RE.sub(" ", work)

    # 3. Temperature (temp_c)
    temp_c = None
    for pat in _TEMP_PATTERNS:
        for m in pat.finditer(work):
            val = _to_float_tr(m.group(1))
            if -25.0 <= val <= 55.0:
                temp_c = val
                work = f"{work[:m.start()]} {work[m.end():]}"
                break
        if temp_c is not None:
            break

    # 4. Sky class
    sky = None
    for cls_name, pat in _SKY_RULES:
        if pat.search(work):
            sky = cls_name
            break

    sky_residual = None
    if sky is None:
        rem = _NOISE_RESIDUAL_RE.sub(" ", work)
        rem = re.sub(r"[%&°'\"´`’(),.;:/\-]+", " ", rem)
        rem = re.sub(r"\s+", " ", rem).strip()
        if rem:
            sky_residual = rem

    return {
        "temp_c": temp_c,
        "rh": rh,
        "sky": sky,
        "windy": windy,
        "sky_residual": sky_residual,
    }


def parse_day_block(block):
    """Parse track conditions per surface + weather fields from a city-day HTML block."""
    conds = parse_conditions_html(block) if block else {}
    hava_raw = extract_hava_raw(block)
    wx = parse_hava_text(hava_raw)
    return {
        "cim_raw": conds.get("Çim"),
        "kum_raw": conds.get("Kum"),
        "sentetik_raw": conds.get("Sentetik"),
        "conds": conds,
        "hava_raw": hava_raw,
        **wx,
    }


def _resolve_max_result_date(db_path):
    """Return latest result-race date in ganyan.db (fallback '2024-10-24' if empty)."""
    conn = _open_ro_sqlite(db_path)
    try:
        row = conn.execute("SELECT MAX(date) FROM races WHERE status = 'result'").fetchone()
    finally:
        conn.close()
    if row and row[0]:
        return str(row[0])
    return "2024-10-24"


def _is_filled_cell(raw_val, norm_val):
    has_raw = raw_val is not None and str(raw_val).strip() != ""
    has_norm = norm_val is not None and str(norm_val).strip() not in ("", "bilinmiyor")
    return has_raw or has_norm


def _get_post_cutoff_filled_ids(conn, cutoff="2024-10-25"):
    rows = conn.execute(
        """
        SELECT race_id, track_cond_raw, track_cond
        FROM races
        WHERE date >= ?
        ORDER BY race_id
        """,
        (cutoff,),
    ).fetchall()
    return [rid for rid, raw_v, norm_v in rows if _is_filled_cell(raw_v, norm_v)]


def compute_post_cutoff_digest(conn, cutoff="2024-10-25", race_ids=None):
    """Compute count and deterministic SHA-256 digest of filled races.track_cond* cells for date >= cutoff."""
    rows = conn.execute(
        """
        SELECT race_id, track_cond_raw, track_cond
        FROM races
        WHERE date >= ?
        ORDER BY race_id
        """,
        (cutoff,),
    ).fetchall()
    h = hashlib.sha256()
    filled = 0
    raw_filled = 0
    id_set = set(race_ids) if race_ids is not None else None
    for rid, raw_v, norm_v in rows:
        include = (rid in id_set) if id_set is not None else _is_filled_cell(raw_v, norm_v)
        if not include:
            continue
        filled += 1
        if raw_v is not None and str(raw_v).strip() != "":
            raw_filled += 1
        h.update(f"{rid}\t{raw_v or ''}\t{norm_v or ''}\n".encode("utf-8"))
    return {"rows": len(rows), "filled": filled, "raw_filled": raw_filled, "sha256": h.hexdigest()}


def run_load_cond(
    backfill_path="data/cond_backfill.sqlite",
    db_path="data/ganyan.db",
    apply=False,
    d_from="2015-01-01",
    d_to=None,
):
    """Parse backfill day blocks, report coverage & unknown tokens, and optionally write to ganyan.db."""
    if d_to is None:
        d_to = _resolve_max_result_date(db_path)

    bf_conn = _open_ro_sqlite(backfill_path)
    try:
        bf_rows = bf_conn.execute(
            "SELECT date, city, http, block FROM day WHERE date BETWEEN ? AND ? ORDER BY date, city",
            (d_from, d_to),
        ).fetchall()
    finally:
        bf_conn.close()

    parsed_days = {}
    unknown_track_conds = Counter()
    unknown_sky = Counter()
    unparsed_temp_examples = []
    unparsed_rh_examples = []
    sky_counts = Counter()

    for d_str, city, http_code, block in bf_rows:
        info = parse_day_block(block if http_code == 200 else "")
        info["http"] = http_code
        parsed_days[(d_str, city)] = info

        for surf, raw_v in info["conds"].items():
            key = extract_cond_key(surf, raw_v)
            if key not in TRACK_COND_MAP:
                unknown_track_conds[(surf, key[1], raw_v)] += 1

        if info["hava_raw"]:
            if info["sky"]:
                sky_counts[info["sky"]] += 1
            else:
                unknown_sky[info["sky_residual"] or "<bos>"] += 1
            if info["temp_c"] is None and len(unparsed_temp_examples) < 15:
                unparsed_temp_examples.append((d_str, city, info["hava_raw"]))
            if info["rh"] is None and len(unparsed_rh_examples) < 15:
                unparsed_rh_examples.append((d_str, city, info["hava_raw"]))

    ro_conn = _open_ro_sqlite(db_path)
    try:
        pre_filled_ids = _get_post_cutoff_filled_ids(ro_conn, cutoff="2024-10-25")
        digest_before = compute_post_cutoff_digest(ro_conn, cutoff="2024-10-25")
        race_rows = ro_conn.execute(
            """
            SELECT race_id, date, city, surface, track_cond_raw, track_cond
            FROM races
            WHERE status = 'result' AND date BETWEEN ? AND ?
            ORDER BY date, city, race_id
            """,
            (d_from, d_to),
        ).fetchall()
    finally:
        ro_conn.close()

    expected_days = {(d_str, city) for _, d_str, city, *_ in race_rows if city in SEHIR_ID_MAP}
    covered_days = {pair for pair in expected_days if pair in parsed_days}
    coverage_expected = len(expected_days)
    coverage_covered = len(covered_days)
    coverage_ratio = (coverage_covered / coverage_expected) if coverage_expected else 0.0

    if apply and coverage_ratio < MIN_APPLY_COVERAGE:
        raise CoverageError(
            f"Kapsama yetersiz: {coverage_covered}/{coverage_expected} "
            f"(%{coverage_ratio * 100:.2f}) < %{MIN_APPLY_COVERAGE * 100:.1f} — --apply reddedildi."
        )

    day_cond_rows = []
    for (d_str, city), info in sorted(parsed_days.items()):
        day_cond_rows.append(
            (
                d_str,
                city,
                info["cim_raw"],
                info["kum_raw"],
                info["sentetik_raw"],
                info["hava_raw"],
                info["temp_c"],
                info["rh"],
                info["sky"],
                info["windy"],
            )
        )

    race_updates = []
    skipped_already_filled = 0
    skipped_unknown_map = 0
    post_cutoff_new_filled_planned = 0
    post_cutoff_compared = 0
    post_cutoff_norm_mismatch = 0
    post_cutoff_raw_mismatch = 0
    post_cutoff_crawl_missing = 0
    post_cutoff_mismatch_examples = []
    yearly = {}

    def _yr_bucket(yr):
        if yr not in yearly:
            yearly[yr] = {
                "db_days": set(),
                "bf_days": set(),
                "hava_days": 0,
                "temp_ok": 0,
                "rh_ok": 0,
                "sky_ok": 0,
                "windy_1": 0,
                "cim_tot": 0,
                "cim_bf_tot": 0,
                "cim_bf_fill": 0,
                "cim_fill": 0,
                "kum_tot": 0,
                "kum_bf_tot": 0,
                "kum_bf_fill": 0,
                "kum_fill": 0,
                "sen_tot": 0,
                "sen_fill": 0,
            }
        return yearly[yr]

    for (d_str, city), info in parsed_days.items():
        b = _yr_bucket(d_str[:4])
        b["bf_days"].add((d_str, city))
        if info["hava_raw"]:
            b["hava_days"] += 1
            if info["temp_c"] is not None:
                b["temp_ok"] += 1
            if info["rh"] is not None:
                b["rh_ok"] += 1
            if info["sky"] is not None:
                b["sky_ok"] += 1
            if info["windy"] == 1:
                b["windy_1"] += 1

    for rid, d_str, city, surf, cur_raw, cur_norm in race_rows:
        yr = d_str[:4]
        b = _yr_bucket(yr)
        b["db_days"].add((d_str, city))
        has_bf = (d_str, city) in parsed_days
        info = parsed_days.get((d_str, city))

        if surf == "Çim":
            b["cim_tot"] += 1
            if has_bf:
                b["cim_bf_tot"] += 1
        elif surf == "Kum":
            b["kum_tot"] += 1
            if has_bf:
                b["kum_bf_tot"] += 1
        elif surf == "Sentetik":
            b["sen_tot"] += 1

        already_filled = _is_filled_cell(cur_raw, cur_norm)
        if already_filled:
            skipped_already_filled += 1
            if surf == "Çim":
                b["cim_fill"] += 1
                if has_bf:
                    b["cim_bf_fill"] += 1
            elif surf == "Kum":
                b["kum_fill"] += 1
                if has_bf:
                    b["kum_bf_fill"] += 1
            elif surf == "Sentetik":
                b["sen_fill"] += 1

            if d_str >= "2024-10-25" and info is not None and info.get("http") == 200:
                crawl_raw = info["conds"].get(surf)
                if crawl_raw:
                    try:
                        crawl_norm = normalize_track_cond(surf, crawl_raw)
                    except KeyError:
                        crawl_norm = "<unknown>"
                    post_cutoff_compared += 1
                    if (cur_norm or "").strip().lower() != crawl_norm.lower():
                        post_cutoff_norm_mismatch += 1
                        if len(post_cutoff_mismatch_examples) < 10:
                            post_cutoff_mismatch_examples.append(
                                (rid, surf, cur_raw, cur_norm, crawl_raw, crawl_norm)
                            )
                    if (cur_raw or "").strip() != crawl_raw.strip():
                        post_cutoff_raw_mismatch += 1
                else:
                    post_cutoff_crawl_missing += 1
            continue

        if not info:
            continue

        raw_val = info["conds"].get(surf)
        if raw_val:
            try:
                norm_val = normalize_track_cond(surf, raw_val)
            except KeyError:
                skipped_unknown_map += 1
                continue
            target_raw, target_norm = raw_val, norm_val
            if surf == "Çim":
                b["cim_fill"] += 1
                b["cim_bf_fill"] += 1
            elif surf == "Kum":
                b["kum_fill"] += 1
                b["kum_bf_fill"] += 1
            elif surf == "Sentetik":
                b["sen_fill"] += 1
        else:
            target_raw, target_norm = None, "bilinmiyor"

        if (cur_raw or None) == target_raw and (cur_norm or None) == target_norm:
            continue
        race_updates.append((target_raw, target_norm, rid))
        if d_str >= "2024-10-25" and _is_filled_cell(target_raw, target_norm):
            post_cutoff_new_filled_planned += 1

    applied_day_cond = 0
    applied_races = 0
    post_cutoff_new_filled_applied = 0
    if apply:
        db_conn = sqlite3.connect(str(db_path), timeout=60)
        try:
            ensure_day_cond_table(db_conn)
            db_conn.executemany(
                """
                INSERT INTO day_cond (
                    date, city, cim_raw, kum_raw, sentetik_raw,
                    hava_raw, temp_c, rh, sky, windy
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, city) DO UPDATE SET
                    cim_raw = excluded.cim_raw,
                    kum_raw = excluded.kum_raw,
                    sentetik_raw = excluded.sentetik_raw,
                    hava_raw = excluded.hava_raw,
                    temp_c = excluded.temp_c,
                    rh = excluded.rh,
                    sky = excluded.sky,
                    windy = excluded.windy
                """,
                day_cond_rows,
            )
            applied_day_cond = len(day_cond_rows)

            if race_updates:
                db_conn.executemany(
                    """
                    UPDATE races
                    SET track_cond_raw = ?, track_cond = ?
                    WHERE race_id = ?
                      AND (track_cond_raw IS NULL OR TRIM(track_cond_raw) = '')
                      AND (track_cond IS NULL OR TRIM(track_cond) = '' OR track_cond = 'bilinmiyor')
                    """,
                    race_updates,
                )
                applied_races = len(race_updates)
            db_conn.commit()

            digest_after = compute_post_cutoff_digest(db_conn, cutoff="2024-10-25", race_ids=pre_filled_ids)
            digest_after_all = compute_post_cutoff_digest(db_conn, cutoff="2024-10-25")
            if digest_before != digest_after:
                raise RuntimeError(
                    f"2024-10-25+ bütünlük hatası! Önce={digest_before}, Sonra={digest_after}"
                )
            post_cutoff_new_filled_applied = digest_after_all["filled"] - digest_before["filled"]
        finally:
            db_conn.close()
    else:
        digest_after = dict(digest_before)

    return {
        "apply": bool(apply),
        "d_from": d_from,
        "d_to": d_to,
        "backfill_days": len(parsed_days),
        "races_scanned": len(race_rows),
        "coverage_expected": coverage_expected,
        "coverage_covered": coverage_covered,
        "coverage_ratio": coverage_ratio,
        "planned_day_cond_rows": len(day_cond_rows),
        "planned_race_updates": len(race_updates),
        "applied_day_cond_rows": applied_day_cond,
        "applied_race_updates": applied_races,
        "skipped_already_filled": skipped_already_filled,
        "skipped_unknown_map": skipped_unknown_map,
        "post_cutoff_new_filled_planned": post_cutoff_new_filled_planned,
        "post_cutoff_new_filled_applied": post_cutoff_new_filled_applied,
        "post_cutoff_compared": post_cutoff_compared,
        "post_cutoff_norm_mismatch": post_cutoff_norm_mismatch,
        "post_cutoff_raw_mismatch": post_cutoff_raw_mismatch,
        "post_cutoff_crawl_missing": post_cutoff_crawl_missing,
        "post_cutoff_mismatch_examples": post_cutoff_mismatch_examples,
        "unknown_track_conds": dict(unknown_track_conds),
        "unknown_sky": dict(unknown_sky),
        "sky_counts": dict(sky_counts),
        "unparsed_temp_examples": unparsed_temp_examples,
        "unparsed_rh_examples": unparsed_rh_examples,
        "yearly": yearly,
        "digest_before": digest_before,
        "digest_after": digest_after,
    }


def _pct(num, den):
    return f"{(100.0 * num / den):5.1f}%" if den > 0 else "  —  "


def format_report(res):
    """Format concise human-readable dry-run / apply report."""
    mode = "APPLY" if res["apply"] else "DRY-RUN"
    lines = [
        f"=== load_cond ({mode}) [{res['d_from']} .. {res['d_to']}] ===",
        f"Tarama günü (backfill): {res['backfill_days']} | Taranan DB koşusu: {res['races_scanned']}",
        f"Kapsama (SehirId bilinen günler): {res['coverage_covered']}/{res['coverage_expected']} "
        f"(%{res['coverage_ratio'] * 100:.2f}, eşik >= %{MIN_APPLY_COVERAGE * 100:.1f})",
        f"Planlanan day_cond satırı: {res['planned_day_cond_rows']} | Planlanan races güncellemesi: {res['planned_race_updates']}",
    ]
    if res["apply"]:
        lines.append(
            f"Uygulanan day_cond satırı: {res['applied_day_cond_rows']} | Güncellenen races satırı: {res['applied_race_updates']}"
        )
    lines.append(
        f"Atlanan dolu hücre: {res['skipped_already_filled']} | Eşlenmeyen pist kelimesi nedeniyle atlanan: {res['skipped_unknown_map']}"
    )
    db_b = res["digest_before"]
    db_a = res["digest_after"]
    lines.append(
        f"2024-10-25+ Bütünlük (dolu hücreler): satır={db_b['rows']} önceki_dolu={db_b['filled']} "
        f"sha256={db_b['sha256'][:16]} -> {db_a['sha256'][:16]} (AYNI={db_b == db_a}) | "
        f"yeni_doldurulan={res['post_cutoff_new_filled_applied']} (planlanan={res['post_cutoff_new_filled_planned']})"
    )
    lines.append(
        f"2024-10-25+ Crawl vs DB dolu karşılaştırma: karşılaştırılan={res['post_cutoff_compared']} | "
        f"norm_fark={res['post_cutoff_norm_mismatch']} | ham_fark={res['post_cutoff_raw_mismatch']} | "
        f"crawl_eksik={res['post_cutoff_crawl_missing']}"
    )
    for ex in res.get("post_cutoff_mismatch_examples", [])[:5]:
        lines.append(f"  - 2024-10-25+ fark: {ex[0]} ({ex[1]}) DB={ex[2]!r}/{ex[3]!r} vs Crawl={ex[4]!r}/{ex[5]!r}")
    lines.append("")
    lines.append(
        "Yıl  | DB Gün | BF Gün | Çim(Tüm)    | Çim(BF)     | Kum(Tüm)    | Kum(BF)     | Hava Gün | Temp% |  Nem% | Sky%  | Rüzg"
    )
    lines.append(
        "-----+--------+--------+-------------+-------------+-------------+-------------+----------+-------+-------+-------+-----"
    )

    tot = {
        "db_days": 0,
        "bf_days": 0,
        "cim_fill": 0,
        "cim_bf_fill": 0,
        "cim_tot": 0,
        "cim_bf_tot": 0,
        "kum_fill": 0,
        "kum_bf_fill": 0,
        "kum_tot": 0,
        "kum_bf_tot": 0,
        "hava_days": 0,
        "temp_ok": 0,
        "rh_ok": 0,
        "sky_ok": 0,
        "windy_1": 0,
    }
    for yr in sorted(res["yearly"]):
        b = res["yearly"][yr]
        n_db = len(b["db_days"])
        n_bf = len(b["bf_days"])
        tot["db_days"] += n_db
        tot["bf_days"] += n_bf
        for k in (
            "cim_fill",
            "cim_bf_fill",
            "cim_tot",
            "cim_bf_tot",
            "kum_fill",
            "kum_bf_fill",
            "kum_tot",
            "kum_bf_tot",
            "hava_days",
            "temp_ok",
            "rh_ok",
            "sky_ok",
            "windy_1",
        ):
            tot[k] += b[k]
        lines.append(
            f"{yr} | {n_db:6d} | {n_bf:6d} | "
            f"{_pct(b['cim_fill'], b['cim_tot'])}({b['cim_tot']:4d}) | "
            f"{_pct(b['cim_bf_fill'], b['cim_bf_tot'])}({b['cim_bf_tot']:4d}) | "
            f"{_pct(b['kum_fill'], b['kum_tot'])}({b['kum_tot']:4d}) | "
            f"{_pct(b['kum_bf_fill'], b['kum_bf_tot'])}({b['kum_bf_tot']:4d}) | "
            f"{b['hava_days']:8d} | {_pct(b['temp_ok'], b['hava_days'])} | "
            f"{_pct(b['rh_ok'], b['hava_days'])} | {_pct(b['sky_ok'], b['hava_days'])} | {b['windy_1']:4d}"
        )

    lines.append(
        "-----+--------+--------+-------------+-------------+-------------+-------------+----------+-------+-------+-------+-----"
    )
    lines.append(
        f"TOPL | {tot['db_days']:6d} | {tot['bf_days']:6d} | "
        f"{_pct(tot['cim_fill'], tot['cim_tot'])}({tot['cim_tot']:4d}) | "
        f"{_pct(tot['cim_bf_fill'], tot['cim_bf_tot'])}({tot['cim_bf_tot']:4d}) | "
        f"{_pct(tot['kum_fill'], tot['kum_tot'])}({tot['kum_tot']:4d}) | "
        f"{_pct(tot['kum_bf_fill'], tot['kum_bf_tot'])}({tot['kum_bf_tot']:4d}) | "
        f"{tot['hava_days']:8d} | {_pct(tot['temp_ok'], tot['hava_days'])} | "
        f"{_pct(tot['rh_ok'], tot['hava_days'])} | {_pct(tot['sky_ok'], tot['hava_days'])} | {tot['windy_1']:4d}"
    )

    lines.append("")
    lines.append(f"Gökyüzü dağılımı: {dict(sorted(res['sky_counts'].items(), key=lambda kv: -kv[1]))}")
    lines.append(f"Bilinmeyen track_cond sayısı: {sum(res['unknown_track_conds'].values())} ({len(res['unknown_track_conds'])} çeşit)")
    for k, cnt in sorted(res["unknown_track_conds"].items(), key=lambda kv: -kv[1])[:20]:
        lines.append(f"  - track_cond? {k}: {cnt}")
    lines.append(f"Çözülemeyen gökyüzü sayısı: {sum(res['unknown_sky'].values())} ({len(res['unknown_sky'])} çeşit)")
    for k, cnt in sorted(res["unknown_sky"].items(), key=lambda kv: -kv[1])[:20]:
        lines.append(f"  - sky? {k!r}: {cnt}")
    if res["unparsed_temp_examples"]:
        lines.append(f"Çözülemeyen sıcaklık örnekleri: {res['unparsed_temp_examples'][:10]}")
    if res["unparsed_rh_examples"]:
        lines.append(f"Çözülemeyen nem örnekleri: {res['unparsed_rh_examples'][:10]}")

    return "\n".join(lines)


def build_arg_parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backfill", default="data/cond_backfill.sqlite")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--dry-run", action="store_true", help="Read-only dry-run (default)")
    ap.add_argument("--apply", action="store_true", help="Write day_cond and empty races.track_cond* cells")
    ap.add_argument("--from", dest="d_from", default="2015-01-01")
    ap.add_argument("--to", dest="d_to", default=None, help="Varsayılan: DB'deki son sonuçlu gün")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    if args.dry_run and args.apply:
        print("HATA: --dry-run ve --apply birlikte kullanılamaz.", file=sys.stderr)
        return 2
    try:
        res = run_load_cond(
            backfill_path=args.backfill,
            db_path=args.db,
            apply=args.apply,
            d_from=args.d_from,
            d_to=args.d_to,
        )
    except CoverageError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    print(format_report(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
