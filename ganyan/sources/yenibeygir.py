"""Parse yenibeygir.com daily/race result pages (2010+) and store speed ratings."""
import datetime
import html
import re
import unicodedata

from ganyan.parse_results import EQUIP_CODES, clean_horse_name
from ganyan.tjk import DOMESTIC_CITIES

SOURCE = "yenibeygir"
FETCH_SOURCE = "yenibeygir_sonuc"

YB_EQUIP_CODES = EQUIP_CODES | frozenset({
    "BB",
    "CG",
    "ÇG",
    "DS",
    "GK",
    "OG",
    "ÖG",
    "SGKR",
    "TGK",
    "YP",
})

_TR_SLUG_MAP = str.maketrans({
    "ç": "c", "Ç": "c",
    "ğ": "g", "Ğ": "g",
    "ı": "i", "I": "i", "İ": "i",
    "ö": "o", "Ö": "o",
    "ş": "s", "Ş": "s",
    "ü": "u", "Ü": "u",
    "â": "a", "Â": "a",
    "î": "i", "Î": "i",
    "û": "u", "Û": "u",
})

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_SUP_BLOCK_RE = re.compile(r"<sup\b[^>]*>(.*?)</sup>", re.DOTALL | re.IGNORECASE)
_RACE_ROW_RE = re.compile(
    r'<div\b[^>]*\bclass=["\'][^"\']*\byarisRow\b[^"\']*["\'][^>]*>',
    re.IGNORECASE,
)
_KOSAN_TABLE_RE = re.compile(
    r'<table\b[^>]*\bclass=["\'][^"\']*\bkosanAtlar\b[^"\']*["\'][^>]*>(.*?)</table>',
    re.DOTALL | re.IGNORECASE,
)
_ATISIM_LINK_RE = re.compile(
    r'<a\b[^>]*\bclass=["\'][^"\']*\batisimlink\b[^"\']*["\'][^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Za-z]{2,4}\)\s*$")
_NUM_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def city_slug(city):
    """Return lowercase ASCII slug for a Turkish city name (e.g. 'Şanlıurfa' -> 'sanliurfa')."""
    s = str(city or "").strip().translate(_TR_SLUG_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


_SLUG_TO_CITY = {city_slug(c): c for c in DOMESTIC_CITIES}


def _parse_date(date):
    if isinstance(date, datetime.datetime):
        return date.date()
    if isinstance(date, datetime.date):
        return date
    s = str(date).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.date.fromisoformat(s)
    m = re.fullmatch(r"(\d{2})[-./](\d{2})[-./](\d{4})", s)
    if m:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return datetime.date.fromisoformat(s)


def results_url(date, city, race_no=None):
    """Build yenibeygir.com daily or single-race results URL."""
    d = _parse_date(date)
    slug = city_slug(city)
    base = f"https://yenibeygir.com/{d.strftime('%d-%m-%Y')}/{slug}"
    if race_no is not None:
        return f"{base}/{int(race_no)}/sonuclar"
    return f"{base}/sonuclar"


def _clean_text(fragment):
    if not fragment:
        return ""
    s = _SCRIPT_STYLE_RE.sub(" ", fragment)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _canonical_city(raw_city):
    if not raw_city:
        return None
    cleaned = re.sub(
        r"\s*(?:At\s+Yarışı\s+Sonuçları|At\s+Yarışı\s+Bülteni|Sonuçları|Bülteni)\s*$",
        "",
        raw_city.strip(),
        flags=re.IGNORECASE,
    ).strip()
    if not cleaned:
        return None
    slug = city_slug(cleaned)
    return _SLUG_TO_CITY.get(slug, cleaned)


def _extract_page_city(html_text):
    """Read the displayed city name from inside the Yenibeygir HTML page."""
    tabs_m = re.search(
        r'<ul\b[^>]*\bclass=["\'][^"\']*\bBultenTabs\b[^"\']*["\'][^>]*>(.*?)</ul>',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if tabs_m:
        sel_m = re.search(
            r'<li\b[^>]*\bclass=["\'][^"\']*\bselected\b[^"\']*["\'][^>]*>(.*?)</li>',
            tabs_m.group(1),
            flags=re.DOTALL | re.IGNORECASE,
        )
        if sel_m:
            city = _canonical_city(_clean_text(sel_m.group(1)))
            if city:
                return city
            title_m = re.search(r'\btitle=(["\'])(.*?)\1', sel_m.group(1), flags=re.DOTALL | re.IGNORECASE)
            if title_m:
                city = _canonical_city(html.unescape(title_m.group(2)))
                if city:
                    return city

    for pattern in (
        r'<a\b[^>]*href=["\']/\d{2}-\d{2}-\d{4}/([a-z0-9-]+)(?:["\'/#?])[^>]*\bclass=["\'][^"\']*\b(?:graybuttonlink|yaris-bulten|yaris-foto|yaris-video)\b',
        r'<a\b[^>]*\bclass=["\'][^"\']*\b(?:graybuttonlink|yaris-bulten|yaris-foto|yaris-video)\b[^>]*href=["\']/\d{2}-\d{2}-\d{4}/([a-z0-9-]+)(?:["\'/#?])',
    ):
        slug_m = re.search(pattern, html_text, flags=re.IGNORECASE)
        if slug_m:
            slug = slug_m.group(1).lower()
            if slug in _SLUG_TO_CITY:
                return _SLUG_TO_CITY[slug]
            return slug

    return None


def _extract_race_no(block, fallback_idx):
    yno_m = re.search(
        r'<div\b[^>]*\bclass=["\'][^"\']*\byarisNo\b[^"\']*["\'][^>]*>(.*?)</div>',
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if yno_m:
        m = re.search(r"(\d+)", _clean_text(yno_m.group(1)))
        if m:
            return int(m.group(1))

    id_m = re.search(r'\bid=["\']kosu_(\d+)["\']', block, flags=re.IGNORECASE)
    if id_m:
        return int(id_m.group(1))

    url_m = re.search(
        r"/\d{2}-\d{2}-\d{4}/[a-z0-9-]+/(\d+)/sonuclar|#kosu_(\d+)",
        block,
        flags=re.IGNORECASE,
    )
    if url_m:
        return int(url_m.group(1) or url_m.group(2))

    return fallback_idx


def _parse_columns(thead_html):
    """Map column roles dynamically from <thead> so 2010 (no 'G. Ç') and modern layouts both work."""
    cols = {
        "sira": 0,
        "name": 1,
        "klv": None,
        "derece": None,
        "hiz": None,
        "blt": None,
        "blt_mode": "blt",
    }
    if not thead_html:
        return cols

    col_idx = 0
    for m in re.finditer(r"<th\b([^>]*)>(.*?)</th>", thead_html, flags=re.DOTALL | re.IGNORECASE):
        attrs, inner = m.group(1), m.group(2)
        label = _clean_text(inner)
        titles = " ".join(
            html.unescape(t)
            for _q, t in re.findall(r'\btitle=(["\'])(.*?)\1', attrs + " " + inner, flags=re.DOTALL | re.IGNORECASE)
        )
        probe = f"{label} {titles}".strip()

        if label == "Sıra":
            cols["sira"] = col_idx
        elif label in ("At İsmi", "At Adı"):
            cols["name"] = col_idx
        elif label == "Klv" or "Kulvar" in probe:
            cols["klv"] = col_idx
        elif label == "Derece":
            cols["derece"] = col_idx
        elif label == "Hız" or "Hız Puanı" in probe:
            cols["hiz"] = col_idx
        elif label == "Blt" or "Bülten" in probe:
            cols["blt"] = col_idx
            cols["blt_mode"] = "blt"
        elif label == "AGF" or "AGF" in probe:
            cols["blt"] = col_idx
            cols["blt_mode"] = "agf"

        span_m = re.search(r'\bcolspan=["\']?(\d+)', attrs, flags=re.IGNORECASE)
        col_idx += int(span_m.group(1)) if span_m else 1

    return cols


def _parse_atisim_cell(cell_html):
    """Extract (name, prog_no, sire, dam, scratched) from Yenibeygir horse-name cell."""
    plain_all = _clean_text(cell_html)
    scratched = "Koşmaz" in plain_all

    # Program number: prefer <span>(N)</span>, fallback to first (N) before pedigree
    span_prog = re.search(r"<span\b[^>]*>\s*\((\d+)\)\s*</span>", cell_html, flags=re.IGNORECASE)
    if span_prog:
        prog_no = int(span_prog.group(1))
    else:
        pm = re.search(r"\((\d+)\)", plain_all)
        prog_no = int(pm.group(1)) if pm else None

    # Horse name + tack codes cleaned through ganyan.parse_results.clean_horse_name
    sup_tokens = [
        t for t in (_clean_text(s) for s in _SUP_BLOCK_RE.findall(cell_html))
        if re.fullmatch(r"[A-ZÇĞİÖŞÜ]{1,6}", t)
    ]
    equip_vocab = YB_EQUIP_CODES | frozenset(sup_tokens)

    link_m = _ATISIM_LINK_RE.search(cell_html)
    if link_m:
        base_name = _clean_text(link_m.group(1))
        raw_for_clean = " ".join([base_name, *sup_tokens]).strip()
        name = clean_horse_name(raw_for_clean, equip_codes=equip_vocab)
    else:
        before_prog = re.split(r"\(\d+\)", plain_all, maxsplit=1)[0].strip()
        name = clean_horse_name(before_prog, equip_codes=equip_vocab)

    # Pedigree: non-atisimlink <a> tags hold [sire, dam]; fallback to plain text after (prog_no)
    ped_links = []
    for am in re.finditer(r"<a\b([^>]*)>(.*?)</a>", cell_html, flags=re.DOTALL | re.IGNORECASE):
        if re.search(r'\bclass=["\'][^"\']*\batisimlink\b', am.group(1), flags=re.IGNORECASE):
            continue
        txt = _clean_text(am.group(2))
        if txt:
            ped_links.append(txt)

    if len(ped_links) >= 2:
        sire, dam = ped_links[0], ped_links[1]
    else:
        after_prog = plain_all
        pm = re.search(r"\(\d+\)", plain_all)
        if pm:
            after_prog = plain_all[pm.end():]
        after_prog = re.sub(r"\s*\((?:Koşmaz|Satılık)\)\s*", " ", after_prog).strip()
        if " - " in after_prog:
            sire_s, dam_s = after_prog.split(" - ", 1)
            sire, dam = sire_s.strip(), dam_s.strip()
        elif "-" in after_prog:
            sire_s, dam_s = after_prog.split("-", 1)
            sire, dam = sire_s.strip(), dam_s.strip()
        else:
            sire = ped_links[0] if ped_links else after_prog.strip()
            dam = ""

    return name, prog_no, sire, dam, scratched


def _parse_number(raw_text):
    """Parse integer/float rating (e.g. '(55)', '(-207)', '(0)'); return None for empty/'-'."""
    if raw_text is None:
        return None
    s = raw_text.strip()
    if not s or s in ("-", "--", "---", "—", "–"):
        return None
    m = re.search(r"([+-]?\d+(?:[.,]\d+)?)", s)
    if not m:
        return None
    val = float(m.group(1).replace(",", "."))
    return int(val) if val.is_integer() else val


def _parse_strict_float(raw_text):
    """Return float if raw_text is purely numeric (optional % stripped by caller), else None."""
    if raw_text is None:
        return None
    s = str(raw_text).strip()
    if not s or not _NUM_RE.fullmatch(s):
        return None
    return float(s.replace(",", "."))


def _parse_klv(cell_html):
    if not cell_html:
        return None
    without_sup = _SUP_BLOCK_RE.sub(" ", cell_html)
    txt = _clean_text(without_sup)
    if not txt or txt in ("-", "--", "—", "–"):
        return None
    m = re.search(r"(\d+)", txt)
    return int(m.group(1)) if m else None


def _parse_blt(cell_html, blt_mode):
    """Extract raw 'blt' text: direct cell text under 'Blt', or 'Blt. Ort: X%' tooltip under 'AGF'."""
    if not cell_html:
        return None
    if blt_mode == "agf":
        for _q, title_raw in re.findall(r'\btitle=(["\'])(.*?)\1', cell_html, flags=re.DOTALL | re.IGNORECASE):
            t = html.unescape(title_raw)
            m = re.search(r"Blt\.\s*Ort\s*:\s*([+-]?\d+(?:[.,]\d+)?)", t, flags=re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    txt = _clean_text(cell_html)
    return txt if txt else None


def _find_cell_by_class(cells_with_attrs, cls_name):
    pat = re.compile(rf'\bclass=["\'][^"\']*\b{re.escape(cls_name)}\b', re.IGNORECASE)
    for idx, (attrs, _inner) in enumerate(cells_with_attrs):
        if pat.search(attrs):
            return idx
    return None


def _parse_race_table(table_html):
    thead_m = re.search(r"<thead\b[^>]*>(.*?)</thead>", table_html, flags=re.DOTALL | re.IGNORECASE)
    cols = _parse_columns(thead_m.group(1) if thead_m else "")

    tbody_m = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", table_html, flags=re.DOTALL | re.IGNORECASE)
    rows_scope = tbody_m.group(1) if tbody_m else table_html

    runners = []
    for tr_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", rows_scope, flags=re.DOTALL | re.IGNORECASE):
        tr_inner = tr_m.group(1)
        cells = re.findall(r"<td\b([^>]*)>(.*?)</td>", tr_inner, flags=re.DOTALL | re.IGNORECASE)
        if len(cells) < 4:
            continue

        sira_idx = cols["sira"]
        cls_sira = _find_cell_by_class(cells, "atno")
        if cls_sira is not None:
            sira_idx = cls_sira

        name_idx = cols["name"]
        cls_name = _find_cell_by_class(cells, "atisimcell")
        if cls_name is not None:
            name_idx = cls_name

        klv_idx = cols["klv"]
        if klv_idx is None:
            klv_idx = _find_cell_by_class(cells, "kulvarcell")

        if name_idx is None or name_idx >= len(cells):
            continue

        derece_txt = ""
        if cols["derece"] is not None and cols["derece"] < len(cells):
            derece_txt = _clean_text(cells[cols["derece"]][1])

        name, prog_no, sire, dam, scratched = _parse_atisim_cell(cells[name_idx][1])
        if derece_txt == "Koşmaz":
            scratched = True

        sira_txt = _clean_text(cells[sira_idx][1]) if (sira_idx is not None and sira_idx < len(cells)) else ""
        if scratched or not sira_txt.isdigit() or int(sira_txt) <= 0:
            finish = None
        else:
            finish = int(sira_txt)

        klv = _parse_klv(cells[klv_idx][1]) if (klv_idx is not None and klv_idx < len(cells)) else None

        hiz = None
        if cols["hiz"] is not None and cols["hiz"] < len(cells):
            hiz = _parse_number(_clean_text(cells[cols["hiz"]][1]))

        blt = None
        if cols["blt"] is not None and cols["blt"] < len(cells):
            blt = _parse_blt(cells[cols["blt"]][1], cols["blt_mode"])

        runners.append({
            "prog_no": prog_no,
            "name": name,
            "sire": sire,
            "dam": dam,
            "finish": finish,
            "hiz": hiz,
            "blt": blt,
            "klv": klv,
        })

    return runners


def parse_results_page(html_text, date):
    """Parse a Yenibeygir results HTML page into ``{city, races: [{race_no, runners}]}``."""
    _ = str(_parse_date(date)) if date else ""
    if not html_text:
        return {"city": None, "races": []}

    city = _extract_page_city(html_text)
    races = []

    row_starts = [m.start() for m in _RACE_ROW_RE.finditer(html_text)]
    if row_starts:
        for idx, start in enumerate(row_starts, 1):
            end = row_starts[idx] if idx < len(row_starts) else len(html_text)
            block = html_text[start:end]
            tbl_m = _KOSAN_TABLE_RE.search(block)
            if not tbl_m:
                continue
            race_no = _extract_race_no(block, idx)
            races.append({
                "race_no": race_no,
                "runners": _parse_race_table(tbl_m.group(1)),
            })
    else:
        for idx, tbl_m in enumerate(_KOSAN_TABLE_RE.finditer(html_text), 1):
            prefix = html_text[max(0, tbl_m.start() - 1200):tbl_m.start()]
            race_no = _extract_race_no(prefix, idx)
            races.append({
                "race_no": race_no,
                "runners": _parse_race_table(tbl_m.group(1)),
            })

    return {"city": city, "races": races}


def _tr_upper_norm(text):
    """Normalize horse/pedigree token preserving Turkish I/İ distinction and stripping '(USA)'."""
    s = _COUNTRY_SUFFIX_RE.sub("", str(text or "").strip())
    s = s.replace("\u0307", "")
    s = s.replace("i", "İ").replace("ı", "I").upper()
    return re.sub(r"\s+", " ", s).strip()


def _ascii_fold_norm(text):
    """ASCII-fold horse/pedigree token to tolerate TJK 'KALIMDOR' vs Yenibeygir 'KALİMDOR'."""
    s = _COUNTRY_SUFFIX_RE.sub("", str(text or "").strip())
    s = s.translate(_TR_SLUG_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _load_race_runners(conn, race_id, cache=None):
    if cache is not None and race_id in cache:
        return cache[race_id]
    rows = conn.execute(
        "SELECT prog_no, horse_key, name, sire, dam FROM runners WHERE race_id = ?",
        (race_id,),
    ).fetchall()
    if cache is not None:
        cache[race_id] = rows
    return rows


def match_runner_horse_key(conn, race_id, runner, cache=None):
    """Find ``horse_key`` in ``runners`` by ``(race_id, prog_no)``, fallback ``sire+dam+name``."""
    db_rows = _load_race_runners(conn, race_id, cache=cache)
    if not db_rows:
        return None

    prog_no = runner.get("prog_no")
    if prog_no is not None:
        by_prog = [r for r in db_rows if r[0] is not None and int(r[0]) == int(prog_no)]
        if len(by_prog) == 1:
            return by_prog[0][1]
        if len(by_prog) > 1:
            target_fold = _ascii_fold_norm(runner.get("name"))
            for r in by_prog:
                if _ascii_fold_norm(r[2]) == target_fold:
                    return r[1]
            return by_prog[0][1]

    r_sire = (runner.get("sire") or "").strip()
    r_dam = (runner.get("dam") or "").strip()
    r_name = (runner.get("name") or "").strip()
    if not r_name:
        return None

    # 2a. Exact (sire, dam, name)
    for _pno, hkey, d_name, d_sire, d_dam in db_rows:
        if (d_sire or "").strip() == r_sire and (d_dam or "").strip() == r_dam and (d_name or "").strip() == r_name:
            return hkey

    # 2b. Turkish uppercase + country suffix stripped ('ROYAL ABJAR' == 'ROYAL ABJAR (USA)')
    tr_key = (_tr_upper_norm(r_sire), _tr_upper_norm(r_dam), _tr_upper_norm(r_name))
    for _pno, hkey, d_name, d_sire, d_dam in db_rows:
        if (_tr_upper_norm(d_sire), _tr_upper_norm(d_dam), _tr_upper_norm(d_name)) == tr_key:
            return hkey

    # 2c. ASCII-folded (sire, dam, name) ('KALİMDOR' == 'KALIMDOR')
    fold_key = (_ascii_fold_norm(r_sire), _ascii_fold_norm(r_dam), _ascii_fold_norm(r_name))
    for _pno, hkey, d_name, d_sire, d_dam in db_rows:
        if (_ascii_fold_norm(d_sire), _ascii_fold_norm(d_dam), _ascii_fold_norm(d_name)) == fold_key:
            return hkey

    return None


def insert_ext_ratings(conn, rows, commit=True):
    """Write rating rows into ``ext_ratings`` using ``INSERT OR REPLACE``.

    ``rows`` items may be 5-tuples ``(source, race_id, horse_key, name, value)`` or
    dicts with keys ``race_id, horse_key, name, value`` (``source`` defaults to ``'yenibeygir'``).
    """
    params = []
    for r in rows or []:
        if isinstance(r, dict):
            params.append((
                r.get("source") or SOURCE,
                r["race_id"],
                r["horse_key"],
                r["name"],
                float(r["value"]),
            ))
        else:
            src, race_id, horse_key, r_name, val = r
            params.append((src or SOURCE, race_id, horse_key, r_name, float(val)))

    if params:
        conn.executemany(
            """
            INSERT OR REPLACE INTO ext_ratings (source, race_id, horse_key, name, value)
            VALUES (?, ?, ?, ?, ?)
            """,
            params,
        )
    if commit:
        conn.commit()
    return len(params)


def match_and_save_ratings(conn, parsed, date, commit=True, write=True):
    """Match parsed Yenibeygir runners against DB ``runners`` and write ``hiz`` / numeric ``blt``."""
    date_iso = _parse_date(date).isoformat()
    city = parsed.get("city")
    races = parsed.get("races") or []

    total_runners = 0
    hiz_filled = 0
    matched = 0
    unmatched = 0
    rating_rows = []
    cache = {}

    for race in races:
        race_no = race.get("race_no")
        race_id = f"{date_iso}_{city}_{race_no}"
        for runner in race.get("runners") or []:
            total_runners += 1
            hiz_val = runner.get("hiz")
            if hiz_val is not None:
                hiz_filled += 1

            horse_key = (
                match_runner_horse_key(conn, race_id, runner, cache=cache)
                if (conn is not None and city)
                else None
            )
            if horse_key is None:
                unmatched += 1
                continue

            matched += 1
            if hiz_val is not None:
                rating_rows.append((SOURCE, race_id, horse_key, "hiz", float(hiz_val)))

            blt_val = _parse_strict_float(runner.get("blt"))
            if blt_val is not None:
                rating_rows.append((SOURCE, race_id, horse_key, "blt", blt_val))

    written = 0
    if write and rating_rows:
        written = insert_ext_ratings(conn, rating_rows, commit=commit)
    elif write and commit:
        conn.commit()

    return {
        "races": len(races),
        "runners": total_runners,
        "hiz_filled": hiz_filled,
        "matched": matched,
        "unmatched": unmatched,
        "rows_written": written,
    }
