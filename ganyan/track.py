"""Normalize TJK HTML track condition strings and extract per-surface conditions (§2.2)."""
import html
import re

SPAN_RE = re.compile(r'<span class="raceWeather\w+">(.*?)</span>', re.DOTALL)
WORD_RE = re.compile(r"^([^0-9]+?)(?:\s+([\d.,]+))?$")

# Explicit (surface, raw_word) -> normalized track_cond ∈ {'kuru', 'normal', 'nemli', 'islak', 'agir', 'yumusak', 'bilinmiyor'}
# Spec §2.2: "eşleme tablosunu ganyan/track.py içinde tek sözlük olarak yaz, 1.3'teki ham değerlerin tamamını kapsasın;
# eşleşmeyen değer test kırmızısı olsun. Kum ve çim için aynı kelime farklı anlam taşıyabilir — surface'i de anahtar yap."
TRACK_COND_MAP = {
    # Kum
    ("Kum", "Kuru"): "kuru",
    ("Kum", "Normal"): "normal",
    ("Kum", "İyi"): "normal",
    ("Kum", "Nemli"): "nemli",
    ("Kum", "Islak"): "islak",
    ("Kum", "Sulu"): "islak",
    ("Kum", "Ağır"): "agir",
    ("Kum", "Çok Ağır"): "agir",
    ("Kum", "Yumuşak"): "yumusak",
    ("Kum", "Biraz Yumuşak"): "yumusak",
    ("Kum", "Çok Yumuşak"): "yumusak",
    # Çim
    ("Çim", "Kuru"): "kuru",
    ("Çim", "Normal"): "normal",
    ("Çim", "İyi"): "normal",
    ("Çim", "Nemli"): "nemli",
    ("Çim", "Islak"): "islak",
    ("Çim", "Sulu"): "islak",
    ("Çim", "Yumuşak"): "yumusak",
    ("Çim", "Biraz Yumuşak"): "yumusak",
    ("Çim", "Çok Yumuşak"): "yumusak",
    ("Çim", "Ağır"): "agir",
    ("Çim", "Biraz Ağır"): "agir",
    ("Çim", "Çok Ağır"): "agir",
    # Sentetik
    ("Sentetik", "Kuru"): "kuru",
    ("Sentetik", "Normal"): "normal",
    ("Sentetik", "İyi"): "normal",
    ("Sentetik", "Nemli"): "nemli",
    ("Sentetik", "Islak"): "islak",
    ("Sentetik", "Sulu"): "islak",
    ("Sentetik", "Yumuşak"): "yumusak",
    ("Sentetik", "Biraz Yumuşak"): "yumusak",
    ("Sentetik", "Çok Yumuşak"): "yumusak",
    ("Sentetik", "Ağır"): "agir",
    ("Sentetik", "Çok Ağır"): "agir",
}

VALID_TRACK_CONDS = frozenset({"kuru", "normal", "nemli", "islak", "agir", "yumusak", "bilinmiyor"})


def parse_conditions_html(html_block):
    """Extract dict of {surface_prefix: full_raw_span_text} from div.conditions-race HTML."""
    if not html_block:
        return {}
    out = {}
    for m in SPAN_RE.finditer(html_block):
        raw_span = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
        if ":" in raw_span:
            surf_part, _ = raw_span.split(":", 1)
            surf = surf_part.strip()
            out[surf] = raw_span
    return out


def extract_cond_key(surface, track_cond_raw):
    """Turn (surface, track_cond_raw like 'Çim: Yumuşak 3,7') into lookup key ('Çim', 'Yumuşak')."""
    if not track_cond_raw:
        return (surface, "")
    val = track_cond_raw.split(":", 1)[1].strip() if ":" in track_cond_raw else track_cond_raw.strip()
    m = WORD_RE.match(val)
    word = m.group(1).strip() if m else val
    return (surface, word)


def normalize_track_cond(surface, track_cond_raw):
    """Normalize raw track condition for a given race surface into VALID_TRACK_CONDS.

    Raises KeyError if a non-empty track_cond_raw is not covered by TRACK_COND_MAP (§2.2).
    """
    if not track_cond_raw or not str(track_cond_raw).strip():
        return "bilinmiyor"
    key = extract_cond_key(surface, str(track_cond_raw))
    if key not in TRACK_COND_MAP:
        raise KeyError(f"Unmapped (surface, track_cond_raw) key: {key} (from {track_cond_raw!r})")
    return TRACK_COND_MAP[key]


def load_html_cond_into_db(conn, html_dir="data/raw/html_cond"):
    """Load downloaded div.conditions-race HTML blocks into races.track_cond_raw and races.track_cond."""
    import os

    races = conn.execute("SELECT race_id, date, city, surface FROM races").fetchall()
    by_day_city = {}
    updates = []
    for race_id, d, c, surf in races:
        key = (d, c)
        if key not in by_day_city:
            fn = os.path.join(html_dir, f"{d}_{c}.html")
            if os.path.exists(fn):
                with open(fn, encoding="utf-8") as f:
                    by_day_city[key] = parse_conditions_html(f.read())
            else:
                by_day_city[key] = {}
        conds = by_day_city[key]
        raw_val = conds.get(surf)
        norm_val = normalize_track_cond(surf, raw_val)
        updates.append((raw_val, norm_val, race_id))

    conn.executemany(
        "UPDATE races SET track_cond_raw = ?, track_cond = ? WHERE race_id = ?",
        updates,
    )
    conn.commit()
    return len(updates)
