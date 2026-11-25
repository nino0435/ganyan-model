#!/usr/bin/env python3
"""Kumarbaz türleri simülasyonu -> reports/KUMARBAZ.md.

15 sanal kumarbaz 2022-01 .. 2026-11 arasında her yarış günü, gerçek ödemelerle oynar: 7'si ganyan (nihai oran), 8'i plase,
ikili, sıralı ikili, üçlü, çifte ve altılı (bets ve altili tablolarındaki gerçek ödemeler).
Bulgular ve uyarılar: docs/KUMARBAZ_BULGULAR.md. Canlı hatta, modellere ve uygulamaya dokunmaz.

Girdi (ikisi de git dışı): data/ganyan.db (salt okunur) ve data/v10_cache/pred_V10_HLB_CAL_*_<yıl>.pkl
(V10 canlı yapılandırmasının yıllık dışarıdan tahmini: model o yılı hiç görmeden üretir).

Kurallar (önceden yazıldı, sonuca bakıp değiştirilmedi; Değerci/Stratejik eşikleri tanı aşamasında aynı veride görüldü;
plase/ikili/sıralı/üçlü/çifte/altılı kumarbazlarının kuralları ilk çalıştırmadan önce yazıldı, Dengeli Derya Değerci'nin eşiklerini kullanır):
- Bahis kararı yalnız koşu öncesi bilinenlere dayanır. Model türleri NİHAİ ganyan oranını seçimde kullanmaz.
- Ödeme gerçek nihai ödemeden (1 TL'ye brüt dönüş): kapanışta oynayan kişi bu oranı alır.
- Kasa 10.000 TL, bahis 50 TL; kasa 10 TL altına inerse iflas. Bahsin oranı etkilemediği varsayılır.
- Birden çok kombinasyon oynanırsa koşuya ayrılan 50 TL kombinasyonlara eşit bölünür (üçlüde 3 atın 6 sırası).
- Ödeme birimi: ganyan, plase, ikili, sıralı ikili ve çifte 1 TL'ye göredir (aylık ödeme oranları yıllarca sabit). Üçlünün birimi zamanla
  değişti; Haziran 2025'ten beri 2 TL olduğu veriden çıkarıldı (UCLU_*), üçlü yalnız o tarihten sonra oynanır. Altılı birimi yalnız
  2026 için bilinir (1,25 TL, ganyan/backtest.py), altılı kumarbazları yalnız 2026 oynar.

Çalıştır:  venv/bin/python scripts/run_kumarbaz_sim.py
"""
import glob
import json
import sqlite3
import sys
import time
from collections import namedtuple
from itertools import permutations
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from ganyan.allocator import allocate_coupon_a  # noqa: E402  (altılı kuponu: repodaki dağıtıcı, Amaç A)

OUT = REPO / "reports" / "KUMARBAZ.md"
PRED_DIR = REPO / "data" / "v10_cache"
FIRST, LAST = "2022-01-01", "2026-12-31"
BANK0, BASE, MIN_BET = 10_000.0, 50.0, 10.0
K = 4                       # günde en çok oynanan koşu (Bitik ve Değerci/Stratejik hariç)
NPATH, NDAY = 300, 300      # yol örneklemesi: 300 günlük (yaklaşık 1 yarış yılı) 300 yol
NBOOT = 2000                # bahis başına getirinin güven aralığı için gün-kümeli örnekleme sayısı
LOW_TAKEOUT_S = 1.40        # koşunun Σ(1/ganyan)'ı bunun altındaysa kesinti yaklaşık %26 ve altı
YEARS = [2022, 2023, 2024, 2025, 2026]
UCLU_FROM, UCLU_BIRIM_TL = "2025-06-01", 2.0    # üçlü ödemesi "birim bilet" başınadır; birim 0,25 TL'den büyüdü, Haz 2025'ten beri 2 TL
UNIT_TL, ALT_BUDGET = 1.25, 200.0               # altılı: birim bilet (2026) ve günlük kupon bütçesi (160 kombinasyon)
SINCE = {"Üçlü Ümit": UCLU_FROM, "Altılı Ayşe": "2026-01-01", "Kuponcu Kemal": "2026-01-01"}   # ödeme birimi bilinen dönem

Bet = namedtuple("Bet", "odds win p agfp rid w", defaults=(1.0,))   # w: bahis tutarı / BASE (altılı kuponunda 1 değil)


# ----------------------------------------------------------------------------- veri
def load_pred(years=YEARS):
    parts = []
    for y in years:
        fs = sorted(glob.glob(str(PRED_DIR / f"pred_V10_HLB_CAL_*_{y}.pkl")))
        if len(fs) != 1:
            raise SystemExit(f"{y} için tam 1 pred_V10_HLB_CAL dosyası bekleniyordu, bulunan: {fs}")
        parts.append(pd.read_pickle(fs[0]))
    return pd.concat(parts, ignore_index=True)


def ro():
    return sqlite3.connect(f"file:{REPO}/data/ganyan.db?mode=ro", uri=True)


def load(first=FIRST, last=LAST, years=YEARS):
    con = ro()
    d = pd.read_sql(
        """select ru.race_id, ru.prog_no, ru.horse_key, ru.finish, ru.ganyan, ru.agf_close,
                  r.date, r.city, r.race_no, r.post_time
           from runners ru join races r using(race_id)
           where r.date between ? and ? and r.status = 'result'
             and ifnull(ru.scratched, 0) = 0 and ru.ganyan > 0""",
        con, params=[first, last])
    con.close()
    d = d.merge(load_pred(years), on=["race_id", "horse_key"], how="left")
    d["win"] = (d.finish == 1).astype(int)
    d = d[d.groupby("race_id").win.transform("sum") >= 1].copy()      # sonuçlanmış koşular
    g = d.groupby("race_id")
    s = g.agf_close.transform("sum")
    d["agfp"] = np.where(s > 0, d.agf_close / s, np.nan)
    d["n"] = g.prog_no.transform("size")
    d["inv"] = 1.0 / d.ganyan
    d["S"] = g.inv.transform("sum")                  # Σ(1/ganyan) = 1 / (1 - kesinti)
    d["year"] = d.date.str[:4].astype(int)
    return d


class Race:
    __slots__ = ("rid", "odds", "win", "p", "agfp", "n", "hasp", "prog", "ex")

    def __init__(self, rid, odds, win, p, agfp, prog=None, ex=None):
        self.rid, self.odds, self.win, self.p, self.agfp = rid, odds, win, p, agfp
        self.n = len(odds)
        self.hasp = bool(np.isfinite(p).all() and np.isfinite(agfp).all())
        self.prog = prog           # program numaraları (eksikse None: diğer bahisler oynanamaz)
        self.ex = ex or {}         # {"PLASE": [(kombinasyon, ödeme)], ...}: sonuçlanmış diğer bahisler


def build_days(d, ex=None):
    d = d.sort_values(["date", "post_time", "city", "race_no", "prog_no"], kind="stable").reset_index(drop=True)
    rid = d.race_id.values
    cut = np.r_[0, np.flatnonzero(rid[1:] != rid[:-1]) + 1, len(d)]
    o, w, p, a, dt, pr = d.ganyan.values, d.win.values, d.p.values, d.agfp.values, d.date.values, d.prog_no.values
    ex = ex or {}
    days = {}
    for i, j in zip(cut[:-1], cut[1:]):
        g = pr[i:j]
        days.setdefault(dt[i], []).append(Race(rid[i], o[i:j], w[i:j], p[i:j], a[i:j],
                                               None if np.isnan(g).any() else g.astype(int), ex.get(rid[i])))
    return days


def mk(r, j):
    return Bet(float(r.odds[j]), int(r.win[j]), float(r.p[j]), float(r.agfp[j]), r.rid)


# ----------------------------------------------------------------------------- kumarbaz türleri
def _by_time(c):                     # c: (anahtar, koşu_sırası, at_sırası) -> koşu sırasına göre
    return sorted(c, key=lambda x: x[1])


def p_temkinli(day):                 # günün en güvenli 4 favorisi
    c = sorted((float(r.odds.min()), i, int(np.argmin(r.odds))) for i, r in enumerate(day))[:K]
    return [mk(day[i], j) for _, i, j in _by_time(c)]


def p_cesur(day):                    # en kalabalık 4 sahada oranı >= 10 olan en kısa oranlı at
    c = []
    for i, r in enumerate(day):
        m = np.flatnonzero(r.odds >= 10)
        if len(m):
            c.append((-r.n, i, int(m[np.argmin(r.odds[m])])))
    return [mk(day[i], j) for _, i, j in _by_time(sorted(c)[:K])]


def p_bitik(day):                    # günün ilk 6 koşusunda favori
    return [mk(r, int(np.argmin(r.odds))) for r in day[:6]]


def p_mantikli(day):                 # modelin en emin olduğu 4 koşuda modelin 1. tercihi
    c = sorted((-float(r.p.max()), i, int(np.argmax(r.p))) for i, r in enumerate(day) if r.hasp)[:K]
    return [mk(day[i], j) for _, i, j in _by_time(c)]


def _fark(day):                      # modelin ihtimali AGF payının >= 1,5 katı ve p >= %8 (nihai oran YOK)
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


def p_degerci(day):
    return [mk(day[i], j) for _, i, j in _by_time(_fark(day))]


RNG = np.random.default_rng(42)


def p_rastgele(day):                 # kontrol: günde 4 rastgele koşu, rastgele at
    idx = sorted(RNG.choice(len(day), size=min(K, len(day)), replace=False).tolist())
    return [mk(day[i], int(RNG.integers(day[i].n))) for i in idx]


# ----------------------------------------------------------------------------- diğer bahisler (plase, ikili, sıralı ikili, üçlü, çifte, altılı)
BET = {"plase": "PLASE", "ikili": "İKİLİ", "sirali": "SIRALI İKİLİ", "uclu": "ÜÇLÜ BAHİS", "cifte": "ÇİFTE"}
M = {"plase": 1, "ikili": 2, "sirali": 2, "uclu": 3}      # modelin kaç tercihi oynanır
UNIT = {"ÜÇLÜ BAHİS": UCLU_BIRIM_TL}                       # ödemeyi 1 TL'ye çeviren bölen (öbür bahislerde 1)

Alt = namedtuple("Alt", "rids legs pay")                   # 6 ayağın race_id'si, resmi kazananlar (küme), 1 birim biletin ikramiyesi
AltRec = namedtuple("AltRec", "date rid pay m a")          # m, a: model ve AGF kuponu = (maliyet TL, tutma ihtimali, 6/6 tuttu mu)
ALT_RES = {}                                               # tarih -> [AltRec]; main doldurur


def parse_combo(s):
    """'2/5' -> ({2}, {5}); '3,6/4' -> ({3, 6}, {4}) (virgül: aynı bahis kalemindeki atlar); bozuksa None."""
    try:
        return tuple({int(x) for x in part.split(",")} for part in s.split("/"))
    except ValueError:
        return None


def load_bets(con, first=FIRST, last=LAST):
    """{race_id: {bahis: [(kombinasyon, ödeme)]}}. k. çifte = k. ve k+1. koşunun kazananları, kayıt 2. ayağın koşusunda."""
    q = ("select race_id, bet, combo, payout from bets where substr(race_id, 1, 10) between ? and ? "
         "and (bet in ('PLASE', 'İKİLİ', 'SIRALI İKİLİ', 'ÜÇLÜ BAHİS') or bet like '%. ÇİFTE')")
    ex = {}
    for rid, bet, combo, pay in con.execute(q, (first, last)):
        if bet.endswith("ÇİFTE"):
            if int(bet.split(".")[0]) + 1 != int(rid.rsplit("_", 1)[1]):
                continue
            bet = "ÇİFTE"
        pos = parse_combo(combo)
        if pos is None or not pay or pay <= 0 or (bet == "PLASE" and len(pos) != 1):    # çok ayaklı "7'li plase" satırları elenir
            continue
        ex.setdefault(rid, {}).setdefault(bet, []).append((pos, float(pay)))
    return ex


def load_altili(con):
    """{tarih: [Alt]}: 6 ayaklı, resmi kazananları ve ikramiyesi belli altılılar."""
    out = {}
    for date, city, a, b, legs, pay in con.execute(
            "select date, city, start_race, end_race, legs, payout from altili where date between ? and ?", (FIRST, LAST)):
        try:
            legs = [set(int(x) for x in leg) for leg in json.loads(legs)]
        except (ValueError, TypeError):
            continue
        if b - a != 5 or len(legs) != 6 or not pay or pay <= 0:
            continue
        out.setdefault(date, []).append(Alt(tuple(f"{date}_{city}_{k}" for k in range(a, b + 1)), legs, float(pay)))
    return out


def hv(spec, p, ix):
    """Modelin (p) bu bahsi tutturma ihtimali, Harville (sıralı seçim) varsayımıyla. ix: seçilen atların sırası."""
    p = np.clip(p, 1e-9, 1 - 1e-9)
    if spec == "plase":                                  # ilk ikiye girer
        a = ix[0]
        q = np.delete(p, a)
        return float(p[a] * (1.0 + np.sum(q / (1.0 - q))))
    a, b = ix[0], ix[1]
    if spec == "ikili":
        return float(p[a] * p[b] * (1.0 / (1.0 - p[a]) + 1.0 / (1.0 - p[b])))
    if spec == "sirali":
        return float(p[a] * p[b] / (1.0 - p[a]))
    tot = 0.0                                            # üçlü: 3 atın 6 sırası
    for x, y, z in permutations(ix[:3]):
        tot += p[x] * p[y] * p[z] / ((1.0 - p[x]) * max(1.0 - p[x] - p[y], 1e-9))
    return float(tot)


def paid(rows, combo):
    """combo ile eşleşen satırların ödemesi (aynı sırada; virgüllü kalemde atlardan biri yeter; ölü yarışta birden çok satır)."""
    return sum(pay for pos, pay in rows if len(pos) == len(combo) and all(int(c) in s for c, s in zip(combo, pos)))


def combos_of(spec, pr):
    if spec == "plase":
        return [(int(pr[0]),)]
    if spec == "ikili":
        return [tuple(sorted((int(pr[0]), int(pr[1]))))]
    if spec == "sirali":
        return [(int(pr[0]), int(pr[1]))]
    return list(permutations(int(x) for x in pr))        # üçlü: 3 atın 6 sırası


def ok(r, spec):
    """Koşuda bu bahis oynanmış ve model, AGF, program numaraları hazır mı (spec=None: yalnız hazırlık)."""
    if not r.hasp or r.prog is None:
        return False
    return spec is None or (bool(r.ex.get(BET[spec])) and (spec != "uclu" or r.rid[:10] >= UCLU_FROM))


def wager(r, spec, ix):
    """Koşuya 1 birimlik bahis: kombinasyonlara eşit bölünür. odds = yatırılan 1 TL'ye toplam geri dönüş."""
    bet = BET[spec]
    cs = combos_of(spec, r.prog[ix])
    got = sum(paid(r.ex[bet], c) for c in cs) / UNIT.get(bet, 1.0)
    return Bet(got / len(cs), int(got > 0), hv(spec, r.p, ix), hv(spec, r.agfp, ix), r.rid)


def rastgele(r, spec):
    """Rastgele kombinasyon oynayanın beklenen sonucu (kesin hesap): bütün kombinasyonların ortalaması."""
    n, rows = r.n, r.ex[BET[spec]]
    nc = {"plase": n, "ikili": n * (n - 1) / 2, "sirali": n * (n - 1), "uclu": n * (n - 1) * (n - 2) / 6}[spec]
    ret = sum(pay for _, pay in rows) / UNIT.get(BET[spec], 1.0) / (6 if spec == "uclu" else 1) / nc
    hit = len(rows) / nc
    return Bet(ret / hit, hit, np.nan, np.nan, r.rid)


def cifte_pairs(day):
    """(2. ayağın sırası, 1. ayak, 2. ayak): ardışık iki koşuda çifte ödemesi var ve ikisi de hazır."""
    by = {r.rid: r for r in day}
    for i, r in enumerate(day):
        date, city, no = r.rid.rsplit("_", 2)
        a = by.get(f"{date}_{city}_{int(no) - 1}")
        if a is not None and ok(a, None) and ok(r, "cifte"):
            yield i, a, r


def wager_cifte(a, ja, r, jr):
    got = paid(r.ex["ÇİFTE"], (int(a.prog[ja]), int(r.prog[jr])))
    return Bet(got, int(got > 0), float(a.p[ja] * r.p[jr]), float(a.agfp[ja] * r.agfp[jr]), r.rid)


def rastgele_cifte(a, r):
    nc = a.n * r.n
    ret = sum(pay for _, pay in r.ex["ÇİFTE"]) / nc
    hit = len(r.ex["ÇİFTE"]) / nc
    return Bet(ret / hit, hit, np.nan, np.nan, r.rid)


def _model_pick(day, spec, m):       # bahsin oynandığı koşularda en emin olunan K koşuda modelin ilk m tercihi
    c = []
    for i, r in enumerate(day):
        if ok(r, spec):
            ix = np.argsort(-r.p, kind="stable")[:m]
            c.append((-hv(spec, r.p, ix), i, ix))
    return [wager(day[i], spec, ix) for _, i, ix in _by_time(sorted(c, key=lambda x: x[:2])[:K])]


def p_plase(day):
    return _model_pick(day, "plase", 1)


def p_ikili(day):
    return _model_pick(day, "ikili", 2)


def p_sirali(day):
    return _model_pick(day, "sirali", 2)


def p_uclu(day):
    return _model_pick(day, "uclu", 3)


def p_dengeli(day):                  # Değerci'nin atı, ama plase (yalnız plase oynanan koşularda)
    sub = [r for r in day if ok(r, "plase")]
    return [wager(sub[i], "plase", np.array([j])) for _, i, j in _by_time(_fark(sub))]


def p_cifte(day):                    # en emin olunan K çiftede iki koşunun da modelin 1. tercihi
    c = [(-float(a.p.max() * r.p.max()), i, (a, r)) for i, a, r in cifte_pairs(day)]
    return [wager_cifte(a, int(np.argmax(a.p)), r, int(np.argmax(r.p))) for _, _, (a, r) in _by_time(sorted(c, key=lambda x: x[:2])[:K])]


def _leg(r, sc):
    return [(int(pr), float(s), float(g)) for pr, s, g in zip(r.prog, sc, r.agfp)]


def _coupon(legs, alt):
    """Dağıtıcı (Amaç A, ALT_BUDGET): (maliyet TL, kuponun tutma ihtimali, 6/6 tuttu mu)."""
    c = allocate_coupon_a(legs, ALT_BUDGET, unit_tl=UNIT_TL)
    return c["cost"], c["hit_prob"], int(all(set(s) & g for s, g in zip(c["selected"], alt.legs)))


def build_altili(days, alt):
    """Her altılı için model ve AGF kuponu (tüm yıllar; para yalnız 2026'da anlamlı): {tarih: [AltRec]}."""
    out = {}
    for date, lst in alt.items():
        by = {r.rid: r for r in days.get(date, [])}
        for a in lst:
            rs = [by.get(x) for x in a.rids]
            if any(r is None or not ok(r, None) for r in rs):
                continue
            m = _coupon([_leg(r, r.p) for r in rs], a)
            g = _coupon([_leg(r, r.agfp) for r in rs], a)
            if m[0] > 0 and g[0] > 0:
                out.setdefault(date, []).append(AltRec(date, a.rids[0], a.pay, m, g))
    return out


def _p_altili(day, who):             # günün altılıları arasında, kuponu kendi olasılığıyla en çok tutacak olanı oynar
    recs = ALT_RES.get(day[0].rid[:10], []) if day else []
    if not recs:
        return []
    r = max(recs, key=lambda x: (getattr(x, who)[1], x.rid))
    cost, prob, hit = getattr(r, who)
    return [Bet(r.pay / cost, hit, prob, (r.a if who == "m" else r.m)[1], r.rid, cost / BASE)]


def p_altili_model(day):
    return _p_altili(day, "m")


def p_altili_agf(day):
    return _p_altili(day, "a")


# ad, bahis biçimi, seçici, tür, kural
PERSONAS = [
    ("Temkinli Tarık", "flat", p_temkinli, "Favori sever",
     "Günün en güçlü 4 favorisine (kapanış oranı en kısa) 50 TL"),
    ("Cesur Cemal", "flat", p_cesur, "Sürpriz avcısı",
     "En kalabalık 4 sahada oranı 10 ve üstü olan en kısa oranlı ata 50 TL"),
    ("Bitik Bilal", "bitik", p_bitik, "Kaybı kovalayan",
     "Günün ilk 6 koşusunda favori; kaybedince bahsi ikiye katlar, kazanınca 50 TL'ye döner, kasası yettiğince"),
    ("Mantıklı Mehmet", "flat", p_mantikli, "Modeli izleyen",
     "Modelin en emin olduğu 4 koşuda modelin 1. tercihine 50 TL"),
    ("Değerci Deniz", "flat", p_degerci, "Fark arayan",
     "Modelin ihtimali AGF payının 1,5 katı ve %8 üstü olan atlar, günde en çok 6, 50 TL"),
    ("Stratejik Selin", "kelly", p_degerci, "Hesaplı",
     "Değerci'nin seçimi, ama bahis çeyrek Kelly (kasanın en çok %2'si, günlük en çok %8)"),
    ("Plase Pınar", "flat", p_plase, "Güvenli oyuncu",
     "Plase oynanan koşularda modelin en emin olduğu 4 koşuda modelin 1. tercihine plase (ilk ikiye girmesi yeter) 50 TL"),
    ("Dengeli Derya", "flat", p_dengeli, "Değeri güvenli oynayan",
     "Değerci'nin atları (model ihtimali AGF payının 1,5 katı ve %8 üstü), plase oynanan koşularda, günde en çok 6, plase 50 TL"),
    ("İkili İlhan", "flat", p_ikili, "Eşleştirmeci",
     "İkili oynanan koşularda modelin en emin olduğu 4 koşuda modelin ilk 2 tercihi (sırası önemsiz) 50 TL"),
    ("Sıralı Sibel", "flat", p_sirali, "Sıra bilen",
     "Sıralı ikili oynanan koşularda modelin en emin olduğu 4 koşuda modelin 1. ve 2. tercihi sırasıyla 50 TL"),
    ("Üçlü Ümit", "flat", p_uclu, "Büyük vurgun avcısı",
     "Üçlü oynanan koşularda modelin en emin olduğu 4 koşuda modelin ilk 3 tercihinin 6 sırası, 50 TL bölünerek; yalnız Haz 2025'ten sonra"),
    ("Çifte Çağla", "flat", p_cifte, "İkiye katlayan",
     "Art arda iki koşunun (çifte) en emin olunan 4 çiftesinde iki koşunun da modelin 1. tercihi, 50 TL"),
    ("Altılı Ayşe", "flat", p_altili_model, "Kuponcu (model)",
     "Günün altılıları arasında modelin en çok tutturacağı olana 200 TL'lik kupon (en çok 160 kombinasyon, repodaki dağıtıcı, model olasılıkları); yalnız 2026"),
    ("Kuponcu Kemal", "flat", p_altili_agf, "Kuponcu (kalabalığı izler)",
     "Aynı kupon, ama AGF'ye (kalabalığın seçimine) göre doldurulur; yalnız 2026"),
    ("Rastgele Remzi", "flat", p_rastgele, "Kontrol (hiçbir şey bilmez)",
     "Günde 4 rastgele koşuda rastgele at, 50 TL"),
]


# ----------------------------------------------------------------------------- oyun
def stake(kind, bank, streak, b, open_, spent):
    if kind == "flat":
        return BASE * b.w
    if kind == "bitik":
        return BASE * 2.0 ** min(streak, 40)
    # kelly: tahmini ödeme AGF'den (yaklaşık %30 kesinti varsayımı), nihai oran kullanılmaz
    bhat = 0.70 / max(b.agfp, 0.003)
    edge = b.p * bhat - 1.0
    if edge <= 0 or bhat <= 1.0:
        return 0.0
    f = min(0.25 * edge / (bhat - 1.0), 0.02)
    return max(0.0, min(f * bank, 0.08 * open_ - spent))


def simulate(plans, kind):
    bank, streak = BANK0, 0
    n = hits = 0
    staked = ret = big = 0.0
    peak, mdd, bust = BANK0, 0.0, None
    for di, bets in enumerate(plans):
        open_, spent = bank, 0.0
        for b in bets:
            s = min(stake(kind, bank, streak, b, open_, spent), bank)
            if s < MIN_BET:
                continue
            bank -= s
            spent += s
            staked += s
            n += 1
            if b.win:
                got = s * b.odds
                bank += got
                ret += got
                hits += 1
                streak = 0
                big = max(big, got)
            else:
                streak += 1
            peak = max(peak, bank)
            mdd = max(mdd, 1.0 - bank / peak)
        if bank < MIN_BET:
            bust = di
            break
    return dict(final=bank, bust=bust, n=n, hits=hits, staked=staked, ret=ret, mdd=mdd, big=big)


def pooled(plans):
    bets = [b for day in plans for b in day]
    o = np.array([b.odds for b in bets])
    w = np.array([b.win for b in bets])
    t = np.array([b.w for b in bets])
    hit = o[w == 1]
    return dict(n=len(bets), per_day=len(bets) / len(plans), hit=w.mean(), roi=(t * w * o).sum() / t.sum() - 1,
                avg=hit.mean() if len(hit) else np.nan, med=float(np.median(hit)) if len(hit) else np.nan)


def unit_roi_n(bets):
    """(bahis sayısı, TL başına getiri)."""
    if not bets:
        return 0, float("nan")
    t = np.array([b.w for b in bets])
    return len(bets), float((t * np.array([b.win * b.odds for b in bets])).sum() / t.sum() - 1)


def _parts(plans):
    """Gün başına (yatırılan tutar, geri dönüş), BASE'in katı olarak."""
    nb = np.array([sum(b.w for b in p) for p in plans], float)
    rs = np.array([sum(b.w * b.win * b.odds for b in p) for p in plans], float)
    return nb, rs


def unit_roi_ci(plans, boot_idx):
    """Gün-kümeli örnekleme: TL başına getirinin noktası ve %95 aralığı."""
    nb, rs = _parts(plans)
    samp = rs[boot_idx].sum(1) / nb[boot_idx].sum(1) - 1
    lo, hi = np.percentile(samp, [2.5, 97.5])
    return rs.sum() / nb.sum() - 1, float(lo), float(hi)


def roi_diff_ci(plans_a, plans_b, boot_idx):
    """A'nın getirisi eksi B'nin getirisi (aynı günler, aynı örnekleme): noktası ve %95 aralığı."""
    (na, ra), (nb_, rb) = _parts(plans_a), _parts(plans_b)
    samp = ra[boot_idx].sum(1) / na[boot_idx].sum(1) - rb[boot_idx].sum(1) / nb_[boot_idx].sum(1)
    lo, hi = np.percentile(samp, [2.5, 97.5])
    return ra.sum() / na.sum() - rb.sum() / nb_.sum(), float(lo), float(hi)


# ----------------------------------------------------------------------------- kesinti dönemleri
def rejim(d):
    r = d.drop_duplicates("race_id").copy()
    r["ym"] = r.date.str[:7]
    c = (1 - 1 / r.groupby("ym").S.median()).round(2)
    runs, cur = [], None
    for ym, v in c.items():
        if cur and cur[2] == v:
            cur[1] = ym
        else:
            cur = [ym, ym, v]
            runs.append(cur)
    return runs


def cita(d):
    """Ganyan çıtaları (1 TL'lik bahis, bütün koşular): (ad, isabet, getiri) — rastgele at, favori (kapanış oranı), modelin 1. tercihi."""
    roi = lambda x: x.win.mul(x.ganyan).mean() - 1
    fav = d.loc[d.groupby("race_id").ganyan.idxmin()]
    m = d[d.p.notna()]
    mt = m.loc[m.groupby("race_id").p.idxmax()]
    return [("Her koşuda rastgele at", d.win.mean(), roi(d)),
            ("Her koşuda favori (kapanış oranı)", fav.win.mean(), roi(fav)),
            ("Her koşuda modelin 1. tercihi", mt.win.mean(), roi(mt))]


def bench(days, dates, spec, who):
    """Bu bahsin oynandığı bütün koşularda tek tip oyun (1 birim): who = model | favori | rastgele. Gün gün plan listesi."""
    plans = []
    for x in dates:
        out = []
        if spec == "cifte":
            for _, a, r in cifte_pairs(days[x]):
                if who == "rastgele":
                    out.append(rastgele_cifte(a, r))
                else:
                    f = (lambda q: int(np.argmax(q.p))) if who == "model" else (lambda q: int(np.argmin(q.odds)))
                    out.append(wager_cifte(a, f(a), r, f(r)))
        else:
            for r in days[x]:
                if not ok(r, spec):
                    continue
                if who == "rastgele":
                    out.append(rastgele(r, spec))
                else:
                    out.append(wager(r, spec, np.argsort(-r.p if who == "model" else r.odds, kind="stable")[:M[spec]]))
        plans.append(out)
    return plans


def altili_bench(dates, ci_idx):
    """Bütün altılılarda model ve AGF kuponu (aynı bütçe): yıllara göre 6/6 isabeti, fark aralığı, 2026 parası."""
    recs = {x: ALT_RES.get(x, []) for x in dates}
    n = np.array([len(recs[x]) for x in dates], float)
    hm = np.array([sum(r.m[2] for r in recs[x]) for x in dates], float)
    ha = np.array([sum(r.a[2] for r in recs[x]) for x in dates], float)
    samp = (hm[ci_idx].sum(1) - ha[ci_idx].sum(1)) / n[ci_idx].sum(1)
    out = dict(n=int(n.sum()), model=hm.sum() / n.sum(), agf=ha.sum() / n.sum(), diff=(hm.sum() - ha.sum()) / n.sum(),
               lo=float(np.percentile(samp, 2.5)), hi=float(np.percentile(samp, 97.5)), by_year={}, money={})
    for y in YEARS:
        rs = [r for x in dates if x[:4] == str(y) for r in recs[x]]
        out["by_year"][y] = (len(rs), float(np.mean([r.m[2] for r in rs])), float(np.mean([r.a[2] for r in rs])))
    d26 = [x for x in dates if x >= "2026-01-01" and recs[x]]
    bi = np.random.default_rng(2).integers(0, len(d26), size=(NBOOT, len(d26)))
    for who in ("m", "a"):
        cost = np.array([sum(getattr(r, who)[0] for r in recs[x]) for x in d26])
        ret = np.array([sum(r.pay for r in recs[x] if getattr(r, who)[2]) for x in d26])
        s = ret[bi].sum(1) / cost[bi].sum(1) - 1
        out["money"][who] = dict(n=int(sum(len(recs[x]) for x in d26)), cost=float(cost.sum()), ret=float(ret.sum()),
                                 roi=float(ret.sum() / cost.sum() - 1), lo=float(np.percentile(s, 2.5)), hi=float(np.percentile(s, 97.5)))
    return out


def boots(nday):
    """Gün örneklemesi: kasa yolları için NPATH x NDAY, getiri aralığı için NBOOT x nday gün sırası."""
    return (np.random.default_rng(0).integers(0, nday, size=(NPATH, NDAY)),
            np.random.default_rng(1).integers(0, nday, size=(NBOOT, nday)))


def main():
    global RNG, ALT_RES
    RNG = np.random.default_rng(42)          # her çalıştırmada aynı rastgele seçimler
    t0 = time.time()
    d = load()
    con = ro()
    ex, alt = load_bets(con), load_altili(con)
    con.close()
    days = build_days(d, ex)
    dates = sorted(days)
    ALT_RES = build_altili(days, alt)
    idx = {y: [i for i, x in enumerate(dates) if x[:4] == str(y)] for y in YEARS}
    boot, ci_idx = boots(len(dates))
    race1 = d.drop_duplicates("race_id")
    s_of = dict(zip(race1.race_id, race1.S))
    print(f"veri {time.time() - t0:.1f}s | gün {len(dates)} koşu {len(race1)} | altılı {sum(len(v) for v in ALT_RES.values())}", flush=True)

    res = {}
    for name, kind, fn, tur, kural in PERSONAS:
        since = SINCE.get(name, FIRST)                                      # ödeme biriminin bilindiği dönem
        all_plans = [fn(days[x]) if x >= since else [] for x in dates]
        ii = [i for i, x in enumerate(dates) if x >= since]
        plans = [all_plans[i] for i in ii]
        bets = [b for day in plans for b in day]
        boot_p, ci_p = boots(len(ii))
        _, lo, hi = unit_roi_ci(plans, ci_p)
        real = {y: simulate([all_plans[i] for i in idx[y]], kind) for y in YEARS}
        paths = [simulate([plans[i] for i in row], kind) for row in boot_p]
        fin = np.array([p["final"] for p in paths])
        busts = [p["bust"] for p in paths if p["bust"] is not None]
        res[name] = dict(
            pool=pooled(plans), lo=lo, hi=hi,
            by_year={y: unit_roi_n([b for i in idx[y] for b in all_plans[i]]) for y in YEARS},
            low=unit_roi_n([b for b in bets if s_of[b.rid] < LOW_TAKEOUT_S]),
            high=unit_roi_n([b for b in bets if s_of[b.rid] >= LOW_TAKEOUT_S]),
            real=real, med=np.median(fin), p10=np.percentile(fin, 10), p90=np.percentile(fin, 90),
            profit=(fin > BANK0).mean(), bust=len(busts) / NPATH,
            bust_day=float(np.median(busts)) if busts else np.nan,
            mdd=float(np.median([p["mdd"] for p in paths])),
            roi_money=np.nansum([p["ret"] for p in paths]) / max(np.sum([p["staked"] for p in paths]), 1) - 1,
            expect=float(np.nanmean([b.p for b in bets])) if bets else np.nan)
        print(f"{name:18s} {time.time() - t0:5.1f}s", flush=True)

    bench_g = cita(d)                        # kıyas çıtaları (birim bahis; 2022-2026 tüm koşular)

    # diğer bahis türlerinde modelin başarısı: model / favori / rastgele, aynı koşularda, 1 birimlik bahis
    ne = {"plase": "At ilk ikiye girer", "ikili": "İlk iki at, sırası önemsiz", "sirali": "İlk iki at, sırasıyla",
          "uclu": f"İlk üç at, sırasıyla (3 atın 6 sırası oynanır; yalnız {UCLU_FROM}'den sonra)", "cifte": "Art arda iki koşunun kazananı"}
    ad = {"plase": "Plase", "ikili": "İkili", "sirali": "Sıralı ikili", "uclu": "Üçlü", "cifte": "Çifte"}
    bt = {}
    for spec in ne:
        pl = {w: bench(days, dates, spec, w) for w in ("model", "favori", "rastgele")}
        bt[spec] = dict(pool={w: pooled(pl[w]) for w in pl}, ci={w: unit_roi_ci(pl[w], ci_idx) for w in pl},
                        diff=roi_diff_ci(pl["model"], pl["favori"], ci_idx),
                        expect=float(np.nanmean([b.p for day in pl["model"] for b in day])))
        print(f"{spec:8s} {time.time() - t0:5.1f}s", flush=True)
    ab = altili_bench(dates, ci_idx)

    L = ["# Kumarbaz simülasyonu\n"]
    L.append("> **Uyarı 1 (Kapanış oranı ve AGF):** Kumarbaz kapanışta oynayan, kapanış AGF'sini ve oranını gören kişi gibi "
             "modellenir; canlıda erken alınan AGF daha az bilgi taşır (bkz. `reports/V10.md` Uyarı 1). Bahsin oranı "
             "etkilemediği varsayılır. Canlı sonuç bu rakamlardan daha kötü beklenmelidir.\n")
    L.append("> **Uyarı 2 (Seçim eşikleri):** Değerci ve Stratejik eşikleri (p ≥ %8, model/AGF ≥ 1,5) tanı aşamasında aynı "
             "veride görüldü; bahis başına getirinin %95 aralığı sıfırı kapsıyor. Bu bir ipucudur, kanıt değildir. "
             "Dengeli Derya aynı eşikleri kullanır.\n")
    L.append("> **Uyarı 3 (Kesinti dönemleri):** TJK kesintisi aylara göre yaklaşık %26 ile %55 arasında oynuyor (aşağıdaki "
             "tablo, ganyan oranlarından çıkarım). Sonuçlar bu karışıma bağlıdır.\n")
    L.append("> **Uyarı 4 (Yol örneklemesi):** \"Kârda bitenler\" ve \"iflas\" yüzdeleri günlerin rastgele "
             "karışımıdır; bahis başına getirinin belirsizliğini yansıtmaz, o belirsizlik %95 aralık sütununda. "
             "Üçlü Ümit ve altılı kumarbazlarının yolları yalnız oynayabildikleri günlerden örneklenir.\n")
    L.append("> **Uyarı 5 (Ödeme birimleri):** Üçlüde ve altılıda ödeme \"birim bilet\" başınadır ve birim zamanla değişti. "
             f"Üçlü: ödemenin aynı koşudaki sıralı ikili ödemesine oranı Haziran 2025'te iki katına çıkıyor; birim {UCLU_BIRIM_TL:.0f} TL "
             "alındı ve rastgele oynayanın kaybının kesintiyle uyumlu çıkması bunu doğruluyor (aşağıda \"Rastgele\" satırı), ama birim "
             f"çıkarımdır, resmi değildir; üçlü yalnız {UCLU_FROM}'den sonra. Altılı: birim {UNIT_TL} TL yalnız 2026 için "
             "(`ganyan/backtest.py` varsayımı), altılı paraları yalnız 2026. Plase, ikili, sıralı ikili ve çifte 1 TL'ye göredir (oranları yıllarca sabit).\n")
    L.append(f"Kasa {BANK0:,.0f} TL, bahis {BASE:.0f} TL (altılıda kupon bedeli, en çok {ALT_BUDGET:.0f} TL), günlük oyun; gerçek ödemeler; "
             f"{len(dates)} yarış günü (2022-01 .. 2026-11), {len(race1):,} koşu.\n")
    L.append("## Kumarbaz kartları\n")
    L.append("| Kumarbaz | Tür | Nasıl oynar |\n|---|---|---|")
    for name, _, _, tur, kural in PERSONAS:
        L.append(f"| {name} | {tur} | {kural} |")
    L.append(f"\n## Sonuç: 300 günlük oyun, {NPATH} rastgele yol (gün örneklemesi)\n")
    L.append("| Kumarbaz | Bahis/gün | İsabet | Tutan bahsin ödeme katı (ort / medyan) | TL başına getiri [%95 aralık] | "
             "Kasa sonu medyan (%10–%90) | Kârda bitenler | İflas | İflasta medyan gün |")
    L.append("|---|---:|---:|---:|---|---|---:|---:|---:|")
    for name, *_ in PERSONAS:
        r = res[name]
        p = r["pool"]
        bd = "—" if np.isnan(r["bust_day"]) else f"{r['bust_day']:.0f}"
        L.append(f"| {name} | {p['per_day']:.1f} | {p['hit']:.1%} | {p['avg']:.1f} / {p['med']:.1f} | "
                 f"{p['roi']:+.1%} [{r['lo']:+.1%}, {r['hi']:+.1%}] | "
                 f"{r['med']:,.0f} ({r['p10']:,.0f}–{r['p90']:,.0f}) | {r['profit']:.0%} | {r['bust']:.0%} | {bd} |")
    L.append("\n## Gerçek takvim yılları (1 Ocak'ta 10.000 TL ile başlasaydı, kasa sonu; 2026 Kasım'a kadar)\n")
    L.append("| Kumarbaz | " + " | ".join(str(y) for y in YEARS) + " |\n|---|" + "---:|" * len(YEARS))
    for name, *_ in PERSONAS:
        cells = []
        for y in YEARS:
            x = res[name]["real"][y]
            cells.append("—" if x["n"] == 0 else f"iflas (gün {x['bust'] + 1})" if x["bust"] is not None else f"{x['final']:,.0f}")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    L.append("\nÜçlü Ümit 2025'te 1 Haziran'dan başlar (o yıl 10.000 TL ile Haziran'da), altılı kumarbazları yalnız 2026 oynar; \"—\" oynamadı demektir.")
    L.append("\n## Yıl bazında TL başına getiri (bahis sayısı)\n")
    L.append("| Kumarbaz | " + " | ".join(str(y) for y in YEARS) + " |\n|---|" + "---:|" * len(YEARS))
    for name, *_ in PERSONAS:
        L.append(f"| {name} | " + " | ".join(
            "—" if res[name]['by_year'][y][0] == 0 else f"{res[name]['by_year'][y][1]:+.1%} ({res[name]['by_year'][y][0]})"
            for y in YEARS) + " |")
    L.append(f"\n## Kesintiye göre TL başına getiri (koşunun Σ(1/ganyan) değeri {LOW_TAKEOUT_S} altı = ganyan kesintisi yaklaşık %26 ve altı)\n")
    L.append("| Kumarbaz | Kesinti düşük: getiri (bahis) | Kesinti yüksek: getiri (bahis) |\n|---|---:|---:|")
    for name, *_ in PERSONAS:
        lo_n, lo_r = res[name]["low"]
        hi_n, hi_r = res[name]["high"]
        L.append(f"| {name} | {lo_r:+.1%} ({lo_n}) | {hi_r:+.1%} ({hi_n}) |")
    L.append("\n## Kıyas çıtaları: ganyan (1 TL'lik bahis, bütün koşular)\n")
    L.append("| Yöntem | İsabet | Bahis başına getiri |\n|---|---:|---:|")
    for ad_, h, r_ in bench_g:
        L.append(f"| {ad_} | {h:.1%} | {r_:+.1%} |")
    L.append("\n## Bahis türüne göre modelin başarısı (1 birimlik bahis, bu bahsin oynandığı bütün koşular)\n")
    L.append("Üç oyun aynı koşularda oynanır: **model** (V10'un ilk tercihleri), **favori** (kapanış ganyan oranı en kısa atlar), "
             "**rastgele** (bütün kombinasyonların ortalaması, kesin hesap). Getiri = geri dönüş / yatırılan − 1. "
             "Parantez içi, modelin kendi ihtimallerinden (Harville) hesaplanan beklenen isabettir; gerçekle yakınsa model dengelidir. "
             "Ganyan karşılığı için yukarıdaki kıyas çıtalarına bakın.\n")
    L.append("| Bahis | Ne tutturulur | Koşu | Model isabet (beklenen) | Model getiri [%95] | Favori isabet | Favori getiri [%95] | "
             "Rastgele isabet | Rastgele getiri | Model − favori getiri [%95] |")
    L.append("|---|---|---:|---|---|---:|---|---:|---:|---|")
    for spec in ne:
        b = bt[spec]
        pm, pf, pr = b["pool"]["model"], b["pool"]["favori"], b["pool"]["rastgele"]
        cm, cf, cr = b["ci"]["model"], b["ci"]["favori"], b["ci"]["rastgele"]
        dd = b["diff"]
        L.append(f"| {ad[spec]} | {ne[spec]} | {pm['n']:,} | {pm['hit']:.1%} ({b['expect']:.1%}) | "
                 f"{cm[0]:+.1%} [{cm[1]:+.1%}, {cm[2]:+.1%}] | {pf['hit']:.1%} | {cf[0]:+.1%} [{cf[1]:+.1%}, {cf[2]:+.1%}] | "
                 f"{pr['hit']:.2%} | {cr[0]:+.1%} | {dd[0] * 100:+.1f} puan [{dd[1] * 100:+.1f}, {dd[2] * 100:+.1f}] |")
    L.append(f"\n### Altılı: model kuponu ve kalabalık (AGF) kuponu, aynı bütçe ({ALT_BUDGET:.0f} TL, en çok {int(ALT_BUDGET / UNIT_TL)} kombinasyon)\n")
    L.append("Altılı, art arda 6 koşunun kazananını bilmektir; kuponda her ayağa birden fazla at yazılır. İki kupon da repodaki dağıtıcıyla "
             "(Amaç A: tutma ihtimalini en çoğa çıkar) doldurulur; fark yalnız hangi olasılığı kullandıkları: modelin mi, AGF'nin mi.\n")
    L.append("| Yıl | Altılı | Model kuponu 6/6 | AGF kuponu 6/6 |\n|---|---:|---:|---:|")
    for y in YEARS:
        n_, hm_, ha_ = ab["by_year"][y]
        L.append(f"| {y} | {n_:,} | {hm_:.1%} | {ha_:.1%} |")
    L.append(f"| Hepsi | {ab['n']:,} | {ab['model']:.1%} | {ab['agf']:.1%} |")
    L.append(f"\nFark (model − AGF): {ab['diff'] * 100:+.2f} puan [%95: {ab['lo'] * 100:+.2f}, {ab['hi'] * 100:+.2f}] (gün-kümeli örnekleme).\n")
    L.append(f"2026'da para ({UNIT_TL} TL birimi varsayımıyla, günün bütün altılıları, her biri için kupon):\n")
    L.append("| Kupon | Altılı | Maliyet (TL) | Dönüş (TL) | Getiri [%95 aralık] |\n|---|---:|---:|---:|---|")
    for who, lab in (("m", "Model"), ("a", "AGF")):
        mo = ab["money"][who]
        L.append(f"| {lab} | {mo['n']:,} | {mo['cost']:,.0f} | {mo['ret']:,.0f} | {mo['roi']:+.1%} [{mo['lo']:+.1%}, {mo['hi']:+.1%}] |")
    L.append("\n## Veride görünen ganyan kesinti dönemleri (aylık medyan Σ(1/ganyan)'dan: kesinti = 1 − 1/Σ)\n")
    L.append("| Dönem | Kesinti |\n|---|---:|")
    for a, b, v in rejim(d):
        L.append(f"| {a} .. {b} | %{v * 100:.0f} |")
    L.append("\n## Ek ölçümler\n")
    for name, *_ in PERSONAS:
        r = res[name]
        L.append(f"- {name}: para ağırlıklı getiri {r['roi_money']:+.1%}, medyan en kötü düşüş {r['mdd']:.0%}, "
                 f"gerçek yıllarda en büyük tek ödeme {max(x['big'] for x in r['real'].values()):,.0f} TL, "
                 f"modelin beklediği isabet {r['expect']:.1%} (gerçek {r['pool']['hit']:.1%})")
    out = "\n".join(L)
    OUT.write_text(out + "\n", encoding="utf-8")
    print(f"\nyazıldı: {OUT}  ({time.time() - t0:.0f} sn)")


if __name__ == "__main__":
    main()
