"""Parse TJK daily program CSVs into structured dicts for SQLite."""
import re
from ganyan.parse_results import (
    HEADER_RE,
    POST_TIME_RE,
    RACE_RE,
    clean_horse_name,
    num,
    race_time,
    weight,
)

SON6_RE = re.compile(r"([KÇS])(\d{1,2})")
ALTILI_START_RE = re.compile(r"(\d+)\.\s*6['’‘][Ll][İIıi]\s+GANYAN\s+Bu\s+ko[şs]udan\s+ba[şs]lar")


def parse_son6(s):
    """Parse Son 6 Yarış string like 'K2K1Ç9K6K1K6' into [('K', 2), ('K', 1), ...]."""
    if not isinstance(s, str) or not s.strip():
        return []
    return [(m.group(1), int(m.group(2))) for m in SON6_RE.finditer(s.strip())]


def int_or_none(s):
    v = num(s)
    return int(v) if v is not None else None


def parse_program_file(path, date=None, city=None):
    """Parse a TJK daily program CSV file into races and runners lists."""
    text = open(path, encoding="utf-8-sig", errors="replace").read().replace("\r", "")
    lines = text.split("\n")

    yg_no = None
    for line in lines[:5]:
        hm = HEADER_RE.match(line.strip())
        if hm:
            if not city:
                city = hm.group(1).strip()
            yg_no = int(hm.group(2))
            if not date:
                date = f"{hm.group(5)}-{hm.group(4)}-{hm.group(3)}"
            break

    races = []
    runners = []
    altili = []
    cur_race = None

    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue

        am = ALTILI_START_RE.search(line_s)
        if am and cur_race is not None:
            start_race = cur_race["race_no"]
            altili.append({
                "date": date,
                "city": city,
                "which": int(am.group(1)),
                "start_race": start_race,
                "end_race": start_race + 5,
            })

        m = RACE_RE.match(line_s)
        if m:
            race_no = int(m.group(1))
            f = [x.strip() for x in line_s.split(";")]
            first_field = m.group(2).strip()
            if ";" in first_field:
                first_field = first_field.split(";", 1)[0].strip()
            tm = POST_TIME_RE.search(first_field)
            post_time = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None

            dist_i = next((i for i, x in enumerate(f) if re.fullmatch(r"\d+m", x)), None)
            race_id = f"{date}_{city}_{race_no}"
            cur_race = {
                "race_id": race_id,
                "date": date,
                "city": city,
                "race_no": race_no,
                "post_time": post_time,
                "yg_no": yg_no,
                "cls": f[1] if len(f) > 1 else "",
                "breed": "Arap" if "Arap" in line_s else ("Ingiliz" if "ngiliz" in line_s else "Diger"),
                "distance": int(f[dist_i][:-1]) if dist_i is not None else None,
                "surface": f[dist_i + 1] if dist_i is not None and dist_i + 1 < len(f) else "",
                "status": "scheduled",
            }
            races.append(cur_race)
            continue

        if cur_race is None:
            continue

        if re.match(r"^\d+;", line_s):
            c = line_s.split(";")
            if len(c) < 16:
                continue
            prog_no = int(c[0].strip())
            agf = re.search(r"%\s*([\d.]+)\((\d+)\)", c[10].strip())
            yas = c[2].split()
            age_f = num(yas[0].rstrip("y")) if yas else None
            age = int(age_f) if age_f is not None else None
            year = int(date[:4])
            birth_year = (year - age) if age is not None else None
            sire = c[3].strip()
            dam = c[4].strip()
            horse_key = f"{sire}|{dam}|{birth_year if birth_year is not None else '<NA>'}"
            name_raw = re.sub(r"\s*\(Koşmaz\)", "", c[1]).strip()
            name_clean = clean_horse_name(c[1])
            gate_f = num(c[9])
            son6_raw = c[12].strip() if c[12].strip() else None
            runners.append({
                "race_id": cur_race["race_id"],
                "prog_no": prog_no,
                "horse_key": horse_key,
                "name": name_clean,
                "name_raw": name_raw,
                "age": age,
                "sex": yas[-1] if len(yas) > 1 else "",
                "sire": sire,
                "dam": dam,
                "weight": weight(c[5]),
                "jockey": c[6].strip(),
                "owner": c[7].strip(),
                "trainer": c[8].strip(),
                "gate": int(gate_f) if gate_f is not None else None,
                "hp": num(c[11]),
                "agf_pct": float(agf.group(1)) if agf else None,
                "agf_rank": int(agf.group(2)) if agf else None,
                "son6": parse_son6(son6_raw),
                "son6_raw": son6_raw,
                "kgs": int_or_none(c[13]),
                "s20": int_or_none(c[14]),
                "best_time_s": race_time(c[15]),
            })

    # TJK AGF açılmadan hemen önce tüm atlara geçici '%0(1)..%0(N)' basabiliyor;
    # koşu toplam AGF'si 0 ise henüz yayınlanmamış kabul et.
    agf_sums = {}
    for r in runners:
        if r["agf_pct"] is not None:
            agf_sums[r["race_id"]] = agf_sums.get(r["race_id"], 0.0) + r["agf_pct"]
    for r in runners:
        if r["agf_pct"] is not None and agf_sums.get(r["race_id"], 0.0) <= 0.0:
            r["agf_pct"] = None
            r["agf_rank"] = None

    return {
        "date": date,
        "city": city,
        "yg_no": yg_no,
        "races": races,
        "runners": runners,
        "altili": altili,
    }
