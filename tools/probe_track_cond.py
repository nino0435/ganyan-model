"""Probe CSV files and TJK HTML pages for track condition (pist durumu) information (§1)."""
import os
import re
from collections import Counter


def scan_csv_dir(label, ddir):
    files = sorted(f for f in os.listdir(ddir) if f.endswith(".csv"))
    col_counts = {}
    after_surf_counts = Counter()
    line0_fields = Counter()
    keyword_hits = Counter()
    all_race_lines = 0
    kw_re = re.compile(r"\b(Islak|Ağır|Yumuşak|Normal|Nemli|Sulu|Çok Ağır|Çok Yumuşak|İyi|Kuru)\b", re.IGNORECASE)

    for fn in files:
        text = open(os.path.join(ddir, fn), encoding="utf-8-sig", errors="replace").read().replace("\r", "")
        lines = text.split("\n")
        if lines:
            for i, p in enumerate(lines[0].split(";")):
                if i >= 1 and p.strip():
                    line0_fields[(i, p.strip())] += 1
        for line in lines:
            if re.match(r"^\d+\.\s*Kosu\s*:", line):
                all_race_lines += 1
                parts = [x.strip() for x in line.split(";")]
                for idx in range(5, len(parts)):
                    val = parts[idx]
                    col_counts.setdefault(idx, Counter())[val] += 1
                dist_i = next((i for i, x in enumerate(parts) if re.fullmatch(r"\d+m", x)), None)
                if dist_i is not None:
                    for idx2 in range(dist_i + 1, len(parts)):
                        v2 = parts[idx2]
                        if v2:
                            after_surf_counts[(idx2 - (dist_i + 1), v2)] += 1
            elif not re.match(r"^\d+;", line):
                m = kw_re.search(line)
                if m:
                    keyword_hits[line.strip()[:80]] += 1

    print(f"=== {label}: {len(files)} files, {all_race_lines} race header lines ===")
    print("Line 0 fields (top 15):", line0_fields.most_common(15))
    print("Keyword hits in non-runner lines (top 15):", keyword_hits.most_common(15))
    print("After surface non-empty fields (top 30):", after_surf_counts.most_common(30))
    non_rekor = {k: v for k, v in after_surf_counts.items() if not k[1].startswith("Rekor Derece")}
    print("After surface NON-Rekor Derece fields:", non_rekor)
    for idx in sorted(col_counts.keys()):
        non_empty = {k: v for k, v in col_counts[idx].items() if k != ""}
        empty_n = col_counts[idx].get("", 0)
        top = sorted(non_empty.items(), key=lambda x: -x[1])[:10]
        print(f"  Col {idx+1} (0-idx {idx}): empty={empty_n}, non-empty distinct={len(non_empty)}, top={top}")


def probe_html():
    import time
    import urllib.parse
    from ganyan.tjk import DELAY, get

    out_dir = "data/raw/html_probe"
    os.makedirs(out_dir, exist_ok=True)

    # Probe 3 dates x 2 cities across Results and Program pages as specified in §1.2
    probes = [
        ("2026-10-24", "24/10/2026", "Ankara", "2"),
        ("2026-10-24", "24/10/2026", "İstanbul", "3"),
        ("2026-01-15", "15/01/2026", "İzmir", "5"),
        ("2026-01-15", "15/01/2026", "Adana", "1"),
        ("2025-12-10", "10/12/2025", "İstanbul", "3"),
        ("2025-12-10", "10/12/2025", "Bursa", "4"),
    ]
    kw_re = re.compile(r"(Pist|Islak|Ağır|Yumuşak|Normal|Nemli|Sulu|Hava|Derece|Çim|Kum)", re.IGNORECASE)

    # 1. Day page probe
    for page_type in ["GunlukYarisSonuclari", "GunlukYarisProgrami"]:
        d_iso, ds, _, _ = probes[0]
        url = (
            f"https://www.tjk.org/TR/YarisSever/Info/Page/{page_type}?QueryParameter_Tarih="
            + urllib.parse.quote(ds, safe="")
        )
        print(f"Fetching day page {page_type} for {d_iso}...")
        st, body = get(url, tries=3, timeout=30)
        time.sleep(DELAY)
        print(f"  status={st}, bytes={len(body)}")
        if st == 200 and body:
            fn = os.path.join(out_dir, f"day_{page_type}_{d_iso}.html")
            open(fn, "wb").write(body)
            txt = body.decode("utf-8", "replace")
            matches = re.findall(r".{0,60}(?:Islak|Ağır|Yumuşak|Normal|Nemli|Sulu|Hava\s*Durumu|Pist\s*Durumu).{0,60}", txt, re.IGNORECASE)
            print(f"  condition matches ({len(matches)}):", matches[:10])

    # 2. City XHR page probe
    for d_iso, ds, city, sehir_id in probes:
        for page_type in ["GunlukYarisSonuclari", "GunlukYarisProgrami"]:
            url = (
                f"https://www.tjk.org/TR/YarisSever/Info/Sehir/{page_type}?"
                f"SehirId={sehir_id}&QueryParameter_Tarih={urllib.parse.quote(ds, safe='')}&"
                f"SehirAdi={urllib.parse.quote(city)}&Era=past"
            )
            print(f"Fetching city XHR {page_type} {d_iso} {city}...")
            st, body = get(url, tries=3, timeout=30, extra_headers={"X-Requested-With": "XMLHttpRequest"})
            time.sleep(DELAY)
            print(f"  status={st}, bytes={len(body)}")
            if st == 200 and body:
                fn = os.path.join(out_dir, f"city_{page_type}_{d_iso}_{city}.html")
                open(fn, "wb").write(body)
                txt = body.decode("utf-8", "replace")
                matches = re.findall(r".{0,60}(?:Islak|Ağır|Yumuşak|Normal|Nemli|Sulu|Hava|Pist).{0,60}", txt, re.IGNORECASE)
                print(f"  matches ({len(matches)}):", [m.strip() for m in matches[:10]])


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    scan_csv_dir("RESULTS", "data/raw/results")
    scan_csv_dir("PROGRAM", "data/raw/program")
    probe_html()
