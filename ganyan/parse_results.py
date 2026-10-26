"""Parse TJK daily result CSVs into structured dicts for SQLite."""
import re

EQUIP_CODES = frozenset({"DB", "GKR", "K", "KG", "SK", "SKG"})

HEADER_RE = re.compile(r"^([^;]+);\(\s*(\d+)\.\s*Yarış Günü\);(\d{2})/(\d{2})/(\d{4})")
RACE_RE = re.compile(r"^(\d+)\.\s*Kosu\s*:(.*)")
TIME_RE = re.compile(r"^(?:(\d+):)?(\d+)\.(\d+)$")
POST_TIME_RE = re.compile(r"(\d{1,2})\.(\d{2})")


def num(s):
    s = (s or "").strip().replace(",", ".")
    m = re.match(r"^-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def weight(s):
    vals = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", (s or "").replace(",", "."))]
    return round(sum(vals), 4) if vals else None


def race_time(s):
    m = TIME_RE.match((s or "").strip())
    if not m:
        return None
    return round(int(m.group(1) or 0) * 60 + int(m.group(2)) + float("0." + m.group(3)), 4)


def money_tl(s):
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def clean_horse_name(raw_name, equip_codes=EQUIP_CODES):
    """Strip '(Koşmaz)' and trailing equipment codes from a horse name."""
    s = re.sub(r"\s*\(Koşmaz\)", "", (raw_name or "")).strip()
    tokens = s.split()
    while len(tokens) > 1 and tokens[-1] in equip_codes:
        tokens.pop()
    return " ".join(tokens)


def parse_bet_line(line, race_id, date, city, race_no):
    """Extract bets and altili records from a bet summary line."""
    bets = []
    altili = []

    # 1. & 2. 6'LI GANYAN
    for m in re.finditer(r"([12])\.\s*6'LI GANYAN\(([0-9,/]+)\)\s*:([0-9.,]+)\s*TL", line):
        which = int(m.group(1))
        legs_raw = m.group(2).split("/")
        if len(legs_raw) == 6 and race_no is not None:
            legs = [[int(x) for x in leg.split(",") if x.strip().isdigit()] for leg in legs_raw]
            pay = money_tl(m.group(3))
            if pay is not None:
                altili.append({
                    "date": date,
                    "city": city,
                    "which": which,
                    "start_race": race_no - 5,
                    "end_race": race_no,
                    "legs": legs,
                    "payout": pay,
                })

    # GANYAN(n) :X TL — must NOT be preceded by 'Lİ, 'LÜ, 'LI, 'LU (e.g., 6'LI GANYAN, 5'Lİ GANYAN, 7'Lİ GANYAN)
    for m in re.finditer(r"(?<![0-9'LİIÜU\s]\s)(?<!'LI\s)(?<!'Lİ\s)(?<!'LÜ\s)(?<!'LU\s)\bGANYAN\((\d+)\)\s*:([0-9.,]+)\s*TL", line):
        # Double check prefix just before match start
        prefix = line[max(0, m.start() - 6):m.start()]
        if re.search(r"['LİIÜU]\s*$", prefix):
            continue
        pay = money_tl(m.group(2))
        if pay is not None:
            bets.append({
                "race_id": race_id,
                "bet": "GANYAN",
                "combo": m.group(1),
                "payout": pay,
            })

    # Other standard bets (İKİLİ, SIRALI İKİLİ, ÜÇLÜ BAHİS, PLASE, PLASE İKİLİ, ÇİFTE, TABELA BAHİS, SIRALI 5 Lİ BAHİS)
    for m in re.finditer(
        r"((?:\d+\.\s*)?ÇİFTE|SIRALI İKİLİ|PLASE İKİLİ|İKİLİ|ÜÇLÜ BAHİS|PLASE|SIRALI 5 Lİ BAHİS|TABELA BAHİS SIRASIZ|TABELA BAHİS)\(([0-9,/]+)\)\s*:([0-9.,]+)\s*TL",
        line,
    ):
        pay = money_tl(m.group(3))
        if pay is not None:
            bets.append({
                "race_id": race_id,
                "bet": m.group(1).strip(),
                "combo": m.group(2),
                "payout": pay,
            })

    return bets, altili


def parse_results_file(path, date=None, city=None):
    """Parse a TJK daily results CSV file into races, runners, bets, and altili lists."""
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
    bets = []
    altili = []

    cur_race = None
    cur_runners = []

    def finalize_race():
        if cur_race is None:
            return
        active = [r for r in cur_runners if not r["scratched"]]
        winners = sum(1 for r in active if r["finish"] == 1)
        cur_race["status"] = "cancelled" if winners == 0 else "result"
        races.append(cur_race)
        runners.extend(cur_runners)

    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
        m = RACE_RE.match(line_s)
        if m:
            finalize_race()
            cur_runners = []
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
                "status": "result",
            }
            continue

        if cur_race is None:
            continue

        if re.match(r"^\d+;", line_s):
            c = line_s.split(";")
            if len(c) < 15:
                continue
            scratched = int("Koşmaz" in c[1] or c[12].strip() == "Koşmaz")
            # AGF field can have two percentages on double-altili races: "%19.75(2)  %21.44(2)" -> first match
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
            cur_runners.append({
                "race_id": cur_race["race_id"],
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
                "finish": int(c[0]) if not scratched else None,
                "time_s": race_time(c[12]),
                "ganyan": num(c[13]),
                "agf_close": float(agf.group(1)) if agf else None,
                "agf_close_rank": int(agf.group(2)) if agf else None,
                "scratched": scratched,
            })
        elif "GANYAN" in line_s or "İKİLİ" in line_s or "ÇİFTE" in line_s:
            b, a = parse_bet_line(line_s, cur_race["race_id"], date, city, cur_race["race_no"])
            bets.extend(b)
            altili.extend(a)

    finalize_race()
    return {
        "date": date,
        "city": city,
        "yg_no": yg_no,
        "races": races,
        "runners": runners,
        "bets": bets,
        "altili": altili,
    }
