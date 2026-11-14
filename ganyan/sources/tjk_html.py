"""Parse TJK daily HTML pages (2005+) into the same schema as parse_results_file."""
import datetime
import html
import re
import urllib.parse

from ganyan.parse_results import (
    EQUIP_CODES,
    POST_TIME_RE,
    clean_horse_name,
    money_tl,
    num,
    parse_bet_line,
    race_time,
    weight,
)

XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}

_TOOLTIP_RE = re.compile(
    r'<(a|span)\b[^>]*\bclass=["\'][^"\']*\b(?:tooltiptextt|tooltipTextImg\w*)\b[^"\']*["\'][^>]*>.*?</\1>',
    re.DOTALL | re.IGNORECASE,
)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_RACE_DETAILS_RE = re.compile(
    r'<div\b[^>]*\bclass=["\'][^"\']*\brace-details\b[^"\']*["\'][^>]*>',
    re.IGNORECASE,
)
_TEVZI_TITLE_RE = re.compile(
    r'<div\b[^>]*\bclass=["\'][^"\']*\btevzi-title\b[^"\']*["\'][^>]*>',
    re.IGNORECASE,
)
_TEVZI_ITEM_RE = re.compile(
    r'<div\b[^>]*\bclass=["\'][^"\']*\btevzi-item\b[^"\']*["\'][^>]*>\s*'
    r"<div\b[^>]*>(.*?)</div>\s*<div\b[^>]*>(.*?)</div>\s*</div>",
    re.DOTALL | re.IGNORECASE,
)
_RUNNER_CELL_RE = re.compile(
    r'<td\b[^>]*\bclass=["\'][^"\']*\bgunluk-GunlukYarisSonuclari-([A-Za-z0-9_]+)\b[^"\']*["\'][^>]*>(.*?)</td>',
    re.DOTALL | re.IGNORECASE,
)
_BAHIS_CARD_H4_RE = re.compile(
    r'<div\b[^>]*\bclass=["\'][^"\']*\bbahisSonucCard\b[^"\']*["\'][^>]*>\s*<h4\b[^>]*>(.*?)</h4>',
    re.DOTALL | re.IGNORECASE,
)


def day_results_url(date):
    """Build TJK daily results landing page URL (lists domestic & foreign cities)."""
    d = datetime.date.fromisoformat(str(date)) if isinstance(date, str) else date
    q_date = urllib.parse.quote(d.strftime("%d/%m/%Y"), safe="")
    return f"https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisSonuclari?QueryParameter_Tarih={q_date}"


def city_results_url(date, city, sehir_id):
    """Build TJK XHR city results URL (requires X-Requested-With: XMLHttpRequest)."""
    d = datetime.date.fromisoformat(str(date)) if isinstance(date, str) else date
    q_date = urllib.parse.quote(d.strftime("%d/%m/%Y"), safe="")
    q_city = urllib.parse.quote(str(city), safe="")
    q_sid = urllib.parse.quote(str(sehir_id), safe="")
    return (
        "https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukYarisSonuclari"
        f"?SehirId={q_sid}&QueryParameter_Tarih={q_date}&SehirAdi={q_city}&Era=past"
    )


def _clean_text(fragment):
    """Strip scripts, tooltips, tags, and HTML entities; collapse whitespace."""
    if not fragment:
        return ""
    s = _SCRIPT_STYLE_RE.sub(" ", fragment)
    s = _TOOLTIP_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _clean_opt(fragment):
    """Clean cell text and normalize empty / dash placeholders to None."""
    s = _clean_text(fragment)
    if not s or s in ("-", "--", "---", "—", "–"):
        return None
    return s


def _html_race_time(raw):
    """Convert TJK HTML time ('1.26.56' or '0.48.50') to seconds via parse_results.race_time."""
    s = (raw or "").strip()
    if not s or s in ("-", "Derecesiz", "Koşmaz"):
        return None
    s = re.sub(r"^(\d+)\.(\d+\.\d+)$", r"\1:\2", s)
    return race_time(s)


def parse_day_cities(day_html):
    """Extract domestic [(city, sehir_id)] pairs from a TJK GunlukYarisSonuclari day page.

    Domestic tabs carry either modern '(N. Y.G.)' or older '(N. Yarış Günü)' text.
    """
    if not day_html:
        return []
    seen = {}
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", day_html, flags=re.DOTALL | re.IGNORECASE):
        attrs, inner = m.group(1), m.group(2)
        if not re.search(r"Y\.G\.|Yarış\s+Günü", _clean_text(inner)):
            continue
        id_m = re.search(r'(?<![\w-])id=["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        sid_m = re.search(r'\bdata-sehir-id=["\'](\d+)["\']', attrs, flags=re.IGNORECASE)
        if id_m and sid_m:
            city = html.unescape(id_m.group(1)).strip()
            sehir_id = sid_m.group(1).strip()
            if city and city not in seen:
                seen[city] = sehir_id
    return list(seen.items())


def _parse_at_adi_cell(at_html, derece_txt):
    """Extract (name, name_raw, prog_no, tjk_at_id, scratched) from td.gunluk-...-AtAdi3."""
    at_id_m = re.search(r"QueryParameter_AtId=(\d+)", at_html or "", flags=re.IGNORECASE)
    tjk_at_id = int(at_id_m.group(1)) if at_id_m else None

    link_m = re.search(
        r'<a\b[^>]*href=["\'][^"\']*AtKosuBilgileri[^"\']*["\'][^>]*>(.*?)</a>',
        at_html or "",
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not link_m:
        no_tip = _TOOLTIP_RE.sub(" ", at_html or "")
        link_m = re.search(r"<a\b[^>]*>(.*?)</a>", no_tip, flags=re.DOTALL | re.IGNORECASE)

    link_txt = _clean_text(link_m.group(1)) if link_m else _clean_text(at_html)
    link_txt = re.sub(r"\s*\((?:Koşmaz|Satılık)\)\s*", " ", link_txt).strip()

    prog_m = re.search(r"\((\d+)\)\s*$", link_txt)
    if prog_m:
        prog_no = int(prog_m.group(1))
        base_name = link_txt[: prog_m.start()].strip()
    else:
        prog_no = None
        base_name = link_txt.strip()

    equip_spans = re.findall(
        r'<span\b[^>]*\bid=["\']aciklamaFancyShrt["\'][^>]*>(.*?)</span>',
        at_html or "",
        flags=re.DOTALL | re.IGNORECASE,
    )
    equip_codes = [c for c in (_clean_text(x) for x in equip_spans) if c]

    name_raw = " ".join([base_name, *equip_codes]).strip()
    name_clean = clean_horse_name(name_raw, equip_codes=EQUIP_CODES)

    at_plain = _clean_text(at_html)
    scratched = int("Koşmaz" in at_plain or derece_txt == "Koşmaz")
    return name_clean, name_raw, prog_no, tjk_at_id, scratched


def _parse_pedigree_cell(baba_html):
    """Extract (sire, dam) from td.gunluk-...-Baba without breaking hyphenated sire names."""
    sire_m = re.search(
        r"<a\b[^>]*QueryParameter_BabaAdi=[^>]*>(.*?)</a>",
        baba_html or "",
        flags=re.DOTALL | re.IGNORECASE,
    )
    dam_m = re.search(
        r"<a\b[^>]*QueryParameter_AnneAdi=[^>]*>(.*?)</a>",
        baba_html or "",
        flags=re.DOTALL | re.IGNORECASE,
    )
    if sire_m and dam_m:
        return _clean_text(sire_m.group(1)), _clean_text(dam_m.group(1))

    plain = _clean_text(baba_html)
    if " / " in plain:
        plain = plain.split(" / ", 1)[0].strip()
    if "-" in plain:
        sire, dam = plain.split("-", 1)
        return sire.strip(), dam.strip()
    return plain.strip(), ""


def _parse_agf_cell(agf_html):
    """Extract (agf_close, agf_close_rank) from td.gunluk-...-AGFORAN (prefers exact title)."""
    if not agf_html:
        return None, None
    titles = [
        html.unescape(t).replace(",", ".")  # title="1. 6'LI GANYAN : %19,75(2)" içinde ' olabilir
        for _q, t in re.findall(r'\btitle=(["\'])(.*?)\1', agf_html, flags=re.IGNORECASE | re.DOTALL)
    ]
    haystack = " ".join(titles) + " " + _clean_text(agf_html).replace(",", ".")
    m = re.search(r"%\s*([\d.]+)\s*\((\d+)\)", haystack)
    if not m:
        return None, None
    return float(m.group(1)), int(m.group(2))


def _parse_race_header(block, date, city, yg_no, fallback_idx):
    """Extract race dict (matching parse_results_file) and prize_1 from a race HTML slice."""
    rno_m = re.search(
        r'<h3\b[^>]*\bclass=["\'][^"\']*\brace-no\b[^"\']*["\'][^>]*>(.*?)</h3>',
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )
    rno_html = rno_m.group(1) if rno_m else ""
    rno_no_special = re.sub(
        r'<span\b[^>]*\bclass=["\'][^"\']*\bozelKosuAdi\b[^"\']*["\'][^>]*>.*?</span>',
        " ",
        rno_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    rno_txt = _clean_text(rno_no_special)
    no_m = re.search(r"(\d+)\.\s*Ko[şs]u", rno_txt, flags=re.IGNORECASE)
    race_no = int(no_m.group(1)) if no_m else fallback_idx
    tm = POST_TIME_RE.search(rno_txt)
    post_time = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None

    cfg_m = re.search(
        r'<h3\b[^>]*\bclass=["\'][^"\']*\brace-config\b[^"\']*["\'][^>]*>(.*?)</h3>',
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cfg_html = cfg_m.group(1) if cfg_m else ""
    cfg_before_eid = re.split(r"<span>\s*E\.İ\.D\.", cfg_html, maxsplit=1, flags=re.IGNORECASE)[0]
    cls_m = re.search(r"<a\b[^>]*>(.*?)</a>", cfg_before_eid, flags=re.DOTALL | re.IGNORECASE)
    cfg_plain = _clean_text(cfg_before_eid)
    cfg_plain = re.split(r",?\s*E\.İ\.D\.", cfg_plain, maxsplit=1)[0].rstrip(" ,")

    cls_val = _clean_text(cls_m.group(1)) if cls_m else (cfg_plain.split(",", 1)[0].strip() if cfg_plain else "")
    breed = "Arap" if "Arap" in cfg_plain else ("Ingiliz" if "ngiliz" in cfg_plain else "Diger")

    distance = None
    surface = ""
    ds_m = re.search(
        r",\s*(\d{3,4})\s*m?\s*([A-Za-zÇĞİÖŞÜçğıöşü]+(?:\s*\([^)]+\))?)\s*$",
        cfg_plain,
    )
    if not ds_m:
        ds_m = re.search(
            r"\b(\d{3,4})\s*m?\s*(Çim|Kum(?:\s*\([^)]+\))?|Sentetik)\b",
            cfg_plain,
            flags=re.IGNORECASE,
        )
    if ds_m:
        distance = int(ds_m.group(1))
        surface = ds_m.group(2).strip()

    prize_1 = None
    pr_m = re.search(
        r"Ikramiye\s*:.*?<dt>\s*1\.\)\s*</dt>\s*<dd>(.*?)</dd>",
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if pr_m:
        dd_html = re.sub(
            r'<span\b[^>]*\bclass=["\'][^"\']*\btlsymbol\b[^"\']*["\'][^>]*>.*?</span>',
            " ",
            pr_m.group(1),
            flags=re.DOTALL | re.IGNORECASE,
        )
        dd_txt = re.sub(r"[₺]|TL|\bt\b", "", _clean_text(dd_html), flags=re.IGNORECASE).strip()
        prize_1 = money_tl(dd_txt)

    race_id = f"{date}_{city}_{race_no}"
    race_dict = {
        "race_id": race_id,
        "date": date,
        "city": city,
        "race_no": race_no,
        "post_time": post_time,
        "yg_no": yg_no,
        "cls": cls_val,
        "breed": breed,
        "distance": distance,
        "surface": surface,
        "status": "result",
    }
    return race_dict, prize_1


def _parse_son800(block):
    """Extract (son800_raw, son800_s) from div.bsinfo-Son800 if present."""
    m = re.search(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bbsinfo-Son800\b[^"\']*["\'][^>]*>(.*?)</div>',
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None, None
    raw = _clean_text(m.group(1))
    if not raw or "Son 800" not in raw:
        return None, None
    tm = re.search(r"Son\s*800\s*:\s*([0-9]+(?:\.[0-9]+)+)", raw, flags=re.IGNORECASE)
    son800_s = _html_race_time(tm.group(1)) if tm else None
    if son800_s is not None and son800_s <= 0:
        son800_s = None
    return raw, son800_s


def _parse_race_bets(block, race_id, date, city, race_no):
    """Normalize bahisSonucCard blocks to CSV bet line format and delegate to parse_bet_line."""
    parts = []
    for h4_m in _BAHIS_CARD_H4_RE.finditer(block):
        spans = [
            _clean_text(s)
            for s in re.findall(r"<span\b[^>]*>(.*?)</span>", h4_m.group(1), flags=re.DOTALL | re.IGNORECASE)
        ]
        if len(spans) < 3:
            continue
        bet_name, combo, pay_txt = spans[0], spans[1], spans[2]
        if bet_name == "6'LI GANYAN":
            bet_name = "1. 6'LI GANYAN"
        pay_norm = re.sub(r"\s+", " ", pay_txt.replace("₺", "TL")).strip()
        parts.append(f"{bet_name}({combo}) :{pay_norm}")

    if not parts:
        return [], []
    return parse_bet_line(", ".join(parts), race_id, date, city, race_no)


def _parse_pools(html_text, date, city):
    """Extract 'Dağıtılacak Tutarlar' rows into pools list."""
    pools = []
    for m in _TEVZI_ITEM_RE.finditer(html_text or ""):
        bet_name = _clean_text(m.group(1))
        amt_txt = re.sub(r"[₺]|TL", "", _clean_text(m.group(2)), flags=re.IGNORECASE).strip()
        amt = money_tl(amt_txt)
        if bet_name and amt is not None:
            pools.append({
                "date": date,
                "city": city,
                "bet": bet_name,
                "amount": amt,
            })
    return pools


def parse_results_html(html_text, date, city):
    """Parse a TJK city results HTML fragment into races, runners, bets, altili + extras."""
    date = str(date)
    yg_no = None
    if html_text and city:
        head_plain = _clean_text(html_text[:6000])
        yg_m = re.search(
            rf"{re.escape(city)}\s*\(\s*(\d+)\.\s*(?:Y\.G\.|Yarış\s+Günü)\s*\)",
            head_plain,
        )
        if yg_m:
            yg_no = int(yg_m.group(1))

    races = []
    runners = []
    bets = []
    altili = []
    race_extra = []
    runner_extra = []
    pools = _parse_pools(html_text, date, city)

    if not html_text:
        return {
            "date": date,
            "city": city,
            "yg_no": yg_no,
            "races": races,
            "runners": runners,
            "bets": bets,
            "altili": altili,
            "race_extra": race_extra,
            "runner_extra": runner_extra,
            "pools": pools,
        }

    race_starts = [m.start() for m in _RACE_DETAILS_RE.finditer(html_text)]
    tevzi_m = _TEVZI_TITLE_RE.search(html_text)
    doc_end = tevzi_m.start() if tevzi_m else len(html_text)
    year = int(date[:4])

    for idx, start in enumerate(race_starts, 1):
        end = race_starts[idx] if idx < len(race_starts) else max(start, doc_end)
        block = html_text[start:end]

        cur_race, prize_1 = _parse_race_header(block, date, city, yg_no, idx)
        race_id = cur_race["race_id"]

        tbody_m = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", block, flags=re.DOTALL | re.IGNORECASE)
        tbody_html = tbody_m.group(1) if tbody_m else ""

        cur_runners = []
        cur_runner_extras = []
        row_idx = 0

        for tr_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", tbody_html, flags=re.DOTALL | re.IGNORECASE):
            cells = {cm.group(1): cm.group(2) for cm in _RUNNER_CELL_RE.finditer(tr_m.group(1))}
            if "AtAdi3" not in cells:
                continue
            row_idx += 1

            sonuc_txt = _clean_text(cells.get("SONUCNO", ""))
            sonuc_int = int(sonuc_txt) if sonuc_txt.isdigit() else None
            derece_txt = _clean_text(cells.get("Derece", ""))

            name_clean, name_raw, prog_no, tjk_at_id, scratched = _parse_at_adi_cell(
                cells.get("AtAdi3", ""), derece_txt
            )
            sire, dam = _parse_pedigree_cell(cells.get("Baba", ""))

            yas_tokens = _clean_text(cells.get("Yas", "")).split()
            age_f = num(yas_tokens[0].rstrip("y")) if yas_tokens else None
            age = int(age_f) if age_f is not None else None
            sex = yas_tokens[-1] if len(yas_tokens) > 1 else ""
            birth_year = (year - age) if age is not None else None
            horse_key = f"{sire}|{dam}|{birth_year if birth_year is not None else '<NA>'}"

            gate_f = num(_clean_text(cells.get("StartId", "")))
            hp_val = num(_clean_text(cells.get("Hc", "")))
            agf_close, agf_close_rank = _parse_agf_cell(cells.get("AGFORAN", ""))

            cur_runners.append({
                "race_id": race_id,
                "prog_no": prog_no,
                "horse_key": horse_key,
                "name": name_clean,
                "name_raw": name_raw,
                "age": age,
                "sex": sex,
                "sire": sire,
                "dam": dam,
                "weight": weight(_clean_text(cells.get("Kilo", ""))),
                "jockey": _clean_text(cells.get("JokeAdi", "")),
                "owner": _clean_text(cells.get("SahipAdi", "")),
                "trainer": _clean_text(cells.get("AntronorAdi", "")),
                "gate": int(gate_f) if gate_f is not None else None,
                "hp": hp_val,
                "finish": None,
                "time_s": _html_race_time(derece_txt),
                "ganyan": num(_clean_text(cells.get("Gny", ""))),
                "agf_close": agf_close,
                "agf_close_rank": agf_close_rank,
                "scratched": scratched,
                "_sonuc_int": sonuc_int,
                "_row_idx": row_idx,
            })
            cur_runner_extras.append({
                "race_id": race_id,
                "horse_key": horse_key,
                "fark": _clean_opt(cells.get("Fark")),
                "gec_cikis": _clean_opt(cells.get("GecCikis")),
                "hp_result": hp_val,
                "tjk_at_id": tjk_at_id,
                "source": "tjk_html",
            })

        has_winner = any((not r["scratched"]) and r["_sonuc_int"] == 1 for r in cur_runners)
        for r in cur_runners:
            s_int = r.pop("_sonuc_int")
            r_idx = r.pop("_row_idx")
            if r["scratched"]:
                r["finish"] = None
            elif s_int is not None and s_int > 0:
                r["finish"] = s_int
            elif has_winner:
                r["finish"] = r_idx
            else:
                r["finish"] = None

        active = [r for r in cur_runners if not r["scratched"]]
        winners = sum(1 for r in active if r["finish"] == 1)
        cur_race["status"] = "cancelled" if winners == 0 else "result"

        races.append(cur_race)
        runners.extend(cur_runners)
        runner_extra.extend(cur_runner_extras)

        son800_raw, son800_s = _parse_son800(block)
        race_extra.append({
            "race_id": race_id,
            "son800_raw": son800_raw,
            "son800_s": son800_s,
            "prize_1": prize_1,
            "source": "tjk_html",
        })

        r_bets, r_altili = _parse_race_bets(block, race_id, date, city, cur_race["race_no"])
        bets.extend(r_bets)
        altili.extend(r_altili)

    return {
        "date": date,
        "city": city,
        "yg_no": yg_no,
        "races": races,
        "runners": runners,
        "bets": bets,
        "altili": altili,
        "race_extra": race_extra,
        "runner_extra": runner_extra,
        "pools": pools,
    }
