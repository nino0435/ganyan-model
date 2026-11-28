"""Paylaşılan kumarbaz seçim/ödeme mantığı — hem geriye dönük sim (scripts/run_kumarbaz_sim.py)
hem de canlı sanal bayi (scripts/run_virtual_bayi.py) için.

Kurallar docs/KUMARBAZ_BULGULAR.md'dekiyle birebir aynı (sadece Altılı Ayşe / Kuponcu Kemal
burada yok: hangi 6 koşunun altılı olduğu koşu öncesinde bilinmiyor, bkz. docs).
"""
from collections import namedtuple
from itertools import permutations

import numpy as np

from ganyan.allocator import allocate_coupon_a

BANK0, BASE, MIN_BET = 10_000.0, 50.0, 10.0
K = 4                       # günde en çok oynanan koşu (Bitik ve Değerci/Stratejik hariç)
UCLU_FROM, UCLU_BIRIM_TL = "2025-06-01", 2.0
BET = {"plase": "PLASE", "ikili": "İKİLİ", "sirali": "SIRALI İKİLİ", "uclu": "ÜÇLÜ BAHİS", "cifte": "ÇİFTE"}
M = {"plase": 1, "ikili": 2, "sirali": 2, "uclu": 3}
UNIT = {"ÜÇLÜ BAHİS": UCLU_BIRIM_TL}

Pick = namedtuple("Pick", "persona bet_type race_id combo p agfp w")   # combo: tuple(prog_no,...) seçim sırasıyla


class DayRace:
    """Tek koşu, canlı karar anındaki bilgiyle (sonuç YOK): prog, p (model), agfp (AGF payı), odds (canlı ganyan)."""

    __slots__ = ("rid", "prog", "p", "agfp", "odds", "n", "hasp")

    def __init__(self, rid, prog, p, agfp, odds):
        self.rid = rid
        self.prog = np.asarray(prog, dtype=int)
        self.p = np.asarray(p, dtype=float)
        self.agfp = np.asarray(agfp, dtype=float)
        self.odds = np.asarray(odds, dtype=float)
        self.n = len(self.prog)
        self.hasp = bool(self.n > 0 and np.isfinite(self.p).all() and np.isfinite(self.agfp).all())


def _by_time(c):
    return sorted(c, key=lambda x: x[1])


def _pick1(day, i, j, persona, bet_type="ganyan"):
    r = day[i]
    return Pick(persona, bet_type, r.rid, (int(r.prog[j]),), float(r.p[j]), float(r.agfp[j]), 1.0)


def p_temkinli(day, persona="Temkinli Tarık"):
    c = sorted((float(r.odds.min()) if np.isfinite(r.odds).any() else np.inf, i, int(np.argmin(r.odds)))
               for i, r in enumerate(day) if np.isfinite(r.odds).any())[:K]
    return [_pick1(day, i, j, persona) for _, i, j in _by_time(c)]


def p_cesur(day, persona="Cesur Cemal"):
    c = []
    for i, r in enumerate(day):
        m = np.flatnonzero(r.odds >= 10)
        if len(m):
            c.append((-r.n, i, int(m[np.argmin(r.odds[m])])))
    return [_pick1(day, i, j, persona) for _, i, j in _by_time(sorted(c)[:K])]


def p_bitik(day, persona="Bitik Bilal"):
    out = []
    for i, r in enumerate(day[:6]):
        if np.isfinite(r.odds).any():
            out.append(_pick1(day, i, int(np.argmin(r.odds)), persona))
    return out


def p_mantikli(day, persona="Mantıklı Mehmet"):
    c = sorted((-float(r.p.max()), i, int(np.argmax(r.p))) for i, r in enumerate(day) if r.hasp)[:K]
    return [_pick1(day, i, j, persona) for _, i, j in _by_time(c)]


def _fark(day):
    """Değerci kuralı: p >= %8 ve p/agfp >= 1,5 olan atlar, günde en çok 6, en emin olunan sıraya göre."""
    c = []
    for i, r in enumerate(day):
        if not r.hasp:
            continue
        ratio = r.p / np.maximum(r.agfp, 0.003)
        ok = (r.p >= 0.08) & (ratio >= 1.5)
        if ok.any():
            j = int(np.argmax(np.where(ok, ratio, -1.0)))
            c.append((-float(ratio[j]), i, j))
    return sorted(c)[:6]


def p_degerci(day, persona="Değerci Deniz"):
    return [_pick1(day, i, j, persona) for _, i, j in _by_time(_fark(day))]


def p_rastgele(day, persona="Rastgele Remzi", seed=42):
    rng = np.random.default_rng(seed)
    idx = sorted(rng.choice(len(day), size=min(K, len(day)), replace=False).tolist()) if day else []
    return [_pick1(day, i, int(rng.integers(day[i].n)), persona) for i in idx]


# ----------------------------------------------------------------------------- diğer bahisler (plase, ikili, sıralı, üçlü, çifte)
def hv(spec, p, ix):
    """Modelin bu bahsi tutturma ihtimali, Harville varsayımıyla."""
    p = np.clip(p, 1e-9, 1 - 1e-9)
    if spec == "plase":
        a = ix[0]
        q = np.delete(p, a)
        return float(p[a] * (1.0 + np.sum(q / (1.0 - q))))
    a, b = ix[0], ix[1]
    if spec == "ikili":
        return float(p[a] * p[b] * (1.0 / (1.0 - p[a]) + 1.0 / (1.0 - p[b])))
    if spec == "sirali":
        return float(p[a] * p[b] / (1.0 - p[a]))
    tot = 0.0
    for x, y, z in permutations(ix[:3]):
        tot += p[x] * p[y] * p[z] / ((1.0 - p[x]) * max(1.0 - p[x] - p[y], 1e-9))
    return float(tot)


def _model_pick(day, spec, m, persona):
    c = []
    for i, r in enumerate(day):
        if not r.hasp or r.n < m:
            continue
        ix = np.argsort(-r.p, kind="stable")[:m]
        c.append((-hv(spec, r.p, ix), i, ix))
    out = []
    for _, i, ix in _by_time(sorted(c, key=lambda x: x[:2])[:K]):
        r = day[i]
        combo = tuple(int(r.prog[x]) for x in ix)
        out.append(Pick(persona, spec, r.rid, combo, hv(spec, r.p, ix), hv(spec, r.agfp, ix), 1.0))
    return out


def p_plase(day):
    return _model_pick(day, "plase", 1, "Plase Pınar")


def p_ikili(day):
    return _model_pick(day, "ikili", 2, "İkili İlhan")


def p_sirali(day):
    return _model_pick(day, "sirali", 2, "Sıralı Sibel")


def p_uclu(day):
    return _model_pick(day, "uclu", 3, "Üçlü Ümit")


def p_dengeli(day, persona="Dengeli Derya"):
    out = []
    for _, i, j in _by_time(_fark(day)):
        r = day[i]
        out.append(Pick(persona, "plase", r.rid, (int(r.prog[j]),), hv("plase", r.p, [j]), hv("plase", r.agfp, [j]), 1.0))
    return out


def cifte_pairs(day):
    """(1. ayak, 2. ayak): ardışık iki koşu, aynı şehir, 2. ayak = 1. ayak + 1."""
    by = {r.rid: r for r in day}
    for r in day:
        date, city, no = r.rid.rsplit("_", 2)
        a = by.get(f"{date}_{city}_{int(no) - 1}")
        if a is not None and a.hasp and r.hasp:
            yield a, r


def p_cifte(day, persona="Çifte Çağla"):
    c = []
    for a, r in cifte_pairs(day):
        c.append((-float(a.p.max() * r.p.max()), a.rid, r.rid, a, r))
    c = sorted(c, key=lambda x: x[:3])[:K]
    out = []
    for _, _, _, a, r in c:
        ja, jr = int(np.argmax(a.p)), int(np.argmax(r.p))
        combo = (int(a.prog[ja]), int(r.prog[jr]))
        out.append(Pick(persona, "cifte", f"{a.rid}|{r.rid}", combo,
                         float(a.p[ja] * r.p[jr]), float(a.agfp[ja] * r.agfp[jr]), 1.0))
    return out


# ----------------------------------------------------------------------------- altılı (Ayşe/Kemal)
ALT_BUDGET, ALT_UNIT_TL = 200.0, 1.25     # 2026 birimi; docs/KUMARBAZ_BULGULAR.md Uyarı 5
AltiliGroup = namedtuple("AltiliGroup", "city which race_ids")


def _leg_vals(r, which):
    arr = r.p if which == "model" else r.agfp
    return [(int(pno), float(p), float(a)) for pno, p, a in zip(r.prog, arr, r.agfp)]


def altili_coupon(legs_day, which):
    """6 ayağın DayRace'leri (sırayla) -> allocate_coupon_a sonucu, ya da None (hazır değilse)."""
    if len(legs_day) != 6 or any(not r.hasp for r in legs_day):
        return None
    legs = [_leg_vals(r, which) for r in legs_day]
    c = allocate_coupon_a(legs, ALT_BUDGET, unit_tl=ALT_UNIT_TL)
    if c["cost"] <= 0:
        return None
    return c


def p_altili(groups, day_by_rid, which, persona):
    """Günün altılı gruplarından, kendi olasılığıyla (model ya da AGF) en çok tutacağı olana 200 TL'lik kupon."""
    best = None
    for g in groups:
        legs_day = [day_by_rid.get(rid) for rid in g.race_ids]
        if any(r is None for r in legs_day):
            continue
        c = altili_coupon(legs_day, which)
        if c is None:
            continue
        if best is None or c["hit_prob"] > best[0]["hit_prob"]:
            best = (c, g)
    if best is None:
        return []
    c, g = best
    combo = {"race_ids": list(g.race_ids), "selected": c["selected"], "k": c["k"]}
    return [Pick(persona, "altili", "|".join(g.race_ids), combo, c["hit_prob"], float("nan"), c["cost"] / BASE)]


def p_altili_model(groups, day_by_rid):
    return p_altili(groups, day_by_rid, "model", "Altılı Ayşe")


def p_altili_agf(groups, day_by_rid):
    return p_altili(groups, day_by_rid, "agf", "Kuponcu Kemal")


PERSONAS = [
    ("Temkinli Tarık", "flat", p_temkinli, "ganyan"),
    ("Cesur Cemal", "flat", p_cesur, "ganyan"),
    ("Bitik Bilal", "bitik", p_bitik, "ganyan"),
    ("Mantıklı Mehmet", "flat", p_mantikli, "ganyan"),
    ("Değerci Deniz", "flat", p_degerci, "ganyan"),
    ("Stratejik Selin", "kelly", lambda day: p_degerci(day, persona="Stratejik Selin"), "ganyan"),
    ("Plase Pınar", "flat", p_plase, "plase"),
    ("Dengeli Derya", "flat", p_dengeli, "plase"),
    ("İkili İlhan", "flat", p_ikili, "ikili"),
    ("Sıralı Sibel", "flat", p_sirali, "sirali"),
    ("Üçlü Ümit", "flat", p_uclu, "uclu"),
    ("Çifte Çağla", "flat", p_cifte, "cifte"),
    ("Rastgele Remzi", "flat", p_rastgele, "ganyan"),
]

# Altılı Ayşe/Kemal: fn(groups, day_by_rid) -> [Pick], diğer 13'ten farklı imza (günün altılı
# gruplarını ve tam day listesini ister, "day" tek başına yetmez).
ALTILI_PERSONAS = [
    ("Altılı Ayşe", "flat", p_altili_model, "altili"),
    ("Kuponcu Kemal", "flat", p_altili_agf, "altili"),
]


# ----------------------------------------------------------------------------- yerleştirme (bahis büyüklüğü)
def stake_tl(kind, bank, p, agfp, streak=0, open_=None, spent=0.0):
    """Bahis tutarı (TL), scripts/run_kumarbaz_sim.py::stake ile birebir.

    flat: BASE · bitik: BASE * 2**kayıp serisi · kelly: p/agfp'den çeyrek Kelly
    (kasanın en çok %2'si, günlük toplam en çok gün başı kasanın %8'i; open_ gün başı kasa, spent bugün harcanan).
    """
    if kind == "flat":
        return BASE
    if kind == "bitik":
        return BASE * 2.0 ** min(streak, 40)
    bhat = 0.70 / max(agfp, 0.003)
    edge = p * bhat - 1.0
    if edge <= 0 or bhat <= 1.0:
        return 0.0
    f = min(0.25 * edge / (bhat - 1.0), 0.02)
    open_ = bank if open_ is None else open_
    return max(0.0, min(f * bank, 0.08 * open_ - spent))


# ----------------------------------------------------------------------------- ödeme (settle)
def parse_combo(s):
    try:
        return tuple({int(x) for x in part.split(",")} for part in s.split("/"))
    except ValueError:
        return None


def paid(rows, combo):
    return sum(pay for pos, pay in rows if len(pos) == len(combo) and all(int(c) in s for c, s in zip(combo, pos)))


def combos_of(spec, combo):
    if spec == "plase":
        return [(int(combo[0]),)]
    if spec == "ikili":
        return [tuple(sorted((int(combo[0]), int(combo[1]))))]
    if spec == "sirali":
        return [(int(combo[0]), int(combo[1]))]
    return list(permutations(int(x) for x in combo))        # üçlü: 3 atın 6 sırası
