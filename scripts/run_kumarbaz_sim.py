#!/usr/bin/env python3
"""Kumarbaz türleri simülasyonu -> reports/KUMARBAZ.md.

7 sanal kumarbaz 2022-01 .. 2026-11 arasında her yarış günü, gerçek nihai ganyan ödemeleriyle oynar.
Bulgular ve uyarılar: docs/KUMARBAZ_BULGULAR.md. Canlı hatta, modellere ve uygulamaya dokunmaz.

Girdi (ikisi de git dışı): data/ganyan.db (salt okunur) ve data/v10_cache/pred_V10_HLB_CAL_*_<yıl>.pkl
(V10 canlı yapılandırmasının yıllık dışarıdan tahmini: model o yılı hiç görmeden üretir).

Kurallar (önceden yazıldı, sonuca bakıp değiştirilmedi; Değerci/Stratejik eşikleri tanı aşamasında aynı veride görüldü):
- Bahis kararı yalnız koşu öncesi bilinenlere dayanır. Model türleri NİHAİ ganyan oranını seçimde kullanmaz.
- Ödeme gerçek nihai ganyan oranından (1 TL'ye brüt dönüş) yapılır: kapanışta oynayan kişi bu oranı alır.
- Kasa 10.000 TL, bahis 50 TL; kasa 10 TL altına inerse iflas. Bahsin oranı etkilemediği varsayılır.

Çalıştır:  venv/bin/python scripts/run_kumarbaz_sim.py
"""
import glob
import sqlite3
import time
from collections import namedtuple
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "KUMARBAZ.md"
PRED_DIR = REPO / "data" / "v10_cache"
FIRST, LAST = "2022-01-01", "2026-12-31"
BANK0, BASE, MIN_BET = 10_000.0, 50.0, 10.0
K = 4                       # günde en çok oynanan koşu (Bitik ve Değerci/Stratejik hariç)
NPATH, NDAY = 300, 300      # yol örneklemesi: 300 günlük (yaklaşık 1 yarış yılı) 300 yol
NBOOT = 2000                # bahis başına getirinin güven aralığı için gün-kümeli örnekleme sayısı
LOW_TAKEOUT_S = 1.40        # koşunun Σ(1/ganyan)'ı bunun altındaysa kesinti yaklaşık %26 ve altı
YEARS = [2022, 2023, 2024, 2025, 2026]

Bet = namedtuple("Bet", "odds win p agfp rid")


# ----------------------------------------------------------------------------- veri
def load_pred():
    parts = []
    for y in range(2022, 2027):
        fs = sorted(glob.glob(str(PRED_DIR / f"pred_V10_HLB_CAL_*_{y}.pkl")))
        if len(fs) != 1:
            raise SystemExit(f"{y} için tam 1 pred_V10_HLB_CAL dosyası bekleniyordu, bulunan: {fs}")
        parts.append(pd.read_pickle(fs[0]))
    return pd.concat(parts, ignore_index=True)


def load():
    con = sqlite3.connect(f"file:{REPO}/data/ganyan.db?mode=ro", uri=True)
    d = pd.read_sql(
        """select ru.race_id, ru.prog_no, ru.horse_key, ru.finish, ru.ganyan, ru.agf_close,
                  r.date, r.city, r.race_no, r.post_time
           from runners ru join races r using(race_id)
           where r.date between ? and ? and r.status = 'result'
             and ifnull(ru.scratched, 0) = 0 and ru.ganyan > 0""",
        con, params=[FIRST, LAST])
    con.close()
    d = d.merge(load_pred(), on=["race_id", "horse_key"], how="left")
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
    __slots__ = ("rid", "odds", "win", "p", "agfp", "n", "hasp")

    def __init__(self, rid, odds, win, p, agfp):
        self.rid, self.odds, self.win, self.p, self.agfp = rid, odds, win, p, agfp
        self.n = len(odds)
        self.hasp = bool(np.isfinite(p).all() and np.isfinite(agfp).all())


def build_days(d):
    d = d.sort_values(["date", "post_time", "city", "race_no", "prog_no"], kind="stable").reset_index(drop=True)
    rid = d.race_id.values
    cut = np.r_[0, np.flatnonzero(rid[1:] != rid[:-1]) + 1, len(d)]
    o, w, p, a, dt = d.ganyan.values, d.win.values, d.p.values, d.agfp.values, d.date.values
    days = {}
    for i, j in zip(cut[:-1], cut[1:]):
        days.setdefault(dt[i], []).append(Race(rid[i], o[i:j], w[i:j], p[i:j], a[i:j]))
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
    ("Rastgele Remzi", "flat", p_rastgele, "Kontrol (hiçbir şey bilmez)",
     "Günde 4 rastgele koşuda rastgele at, 50 TL"),
]


# ----------------------------------------------------------------------------- oyun
def stake(kind, bank, streak, b, open_, spent):
    if kind == "flat":
        return BASE
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
    hit = o[w == 1]
    return dict(n=len(bets), per_day=len(bets) / len(plans), hit=w.mean(), roi=(w * o).mean() - 1,
                avg=hit.mean() if len(hit) else np.nan, med=float(np.median(hit)) if len(hit) else np.nan)


def unit_roi_n(bets):
    """(bahis sayısı, birim bahis getirisi)."""
    if not bets:
        return 0, float("nan")
    return len(bets), float(np.mean([b.win * b.odds for b in bets]) - 1)


def unit_roi_ci(plans, boot_idx):
    """Gün-kümeli örnekleme: bahis başına getirinin noktası ve %95 aralığı."""
    nb = np.array([len(p) for p in plans], float)
    rs = np.array([sum(b.win * b.odds for b in p) for p in plans], float)
    samp = rs[boot_idx].sum(1) / nb[boot_idx].sum(1) - 1
    lo, hi = np.percentile(samp, [2.5, 97.5])
    return rs.sum() / nb.sum() - 1, float(lo), float(hi)


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


def main():
    global RNG
    RNG = np.random.default_rng(42)          # her çalıştırmada aynı rastgele seçimler
    t0 = time.time()
    d = load()
    days = build_days(d)
    dates = sorted(days)
    idx = {y: [i for i, x in enumerate(dates) if x[:4] == str(y)] for y in YEARS}
    boot = np.random.default_rng(0).integers(0, len(dates), size=(NPATH, NDAY))
    ci_idx = np.random.default_rng(1).integers(0, len(dates), size=(NBOOT, len(dates)))
    race1 = d.drop_duplicates("race_id")
    s_of = dict(zip(race1.race_id, race1.S))
    print(f"veri {time.time() - t0:.1f}s | gün {len(dates)} koşu {len(race1)}", flush=True)

    res = {}
    for name, kind, fn, tur, kural in PERSONAS:
        plans = [fn(days[x]) for x in dates]
        bets = [b for day in plans for b in day]
        _, lo, hi = unit_roi_ci(plans, ci_idx)
        real = {y: simulate([plans[i] for i in idx[y]], kind) for y in YEARS}
        paths = [simulate([plans[i] for i in row], kind) for row in boot]
        fin = np.array([p["final"] for p in paths])
        busts = [p["bust"] for p in paths if p["bust"] is not None]
        res[name] = dict(
            pool=pooled(plans), lo=lo, hi=hi,
            by_year={y: unit_roi_n([b for i in idx[y] for b in plans[i]]) for y in YEARS},
            low=unit_roi_n([b for b in bets if s_of[b.rid] < LOW_TAKEOUT_S]),
            high=unit_roi_n([b for b in bets if s_of[b.rid] >= LOW_TAKEOUT_S]),
            real=real, med=np.median(fin), p10=np.percentile(fin, 10), p90=np.percentile(fin, 90),
            profit=(fin > BANK0).mean(), bust=len(busts) / NPATH,
            bust_day=float(np.median(busts)) if busts else np.nan,
            mdd=float(np.median([p["mdd"] for p in paths])),
            roi_money=np.nansum([p["ret"] for p in paths]) / max(np.sum([p["staked"] for p in paths]), 1) - 1)
        print(f"{name:18s} {time.time() - t0:5.1f}s", flush=True)

    # kıyas çıtaları (birim bahis; 2022-2026 tüm koşular)
    roi = lambda x: x.win.mul(x.ganyan).mean() - 1
    fav = d.loc[d.groupby("race_id").ganyan.idxmin()]
    m = d[d.p.notna()]
    mt = m.loc[m.groupby("race_id").p.idxmax()]
    bench = [("Her koşuda rastgele at", d.win.mean(), roi(d)),
             ("Her koşuda favori (kapanış oranı)", fav.win.mean(), roi(fav)),
             ("Her koşuda modelin 1. tercihi", mt.win.mean(), roi(mt))]

    L = ["# Kumarbaz simülasyonu\n"]
    L.append("> **Uyarı 1 (Kapanış oranı ve AGF):** Kumarbaz kapanışta oynayan, kapanış AGF'sini ve oranını gören kişi gibi "
             "modellenir; canlıda erken alınan AGF daha az bilgi taşır (bkz. `reports/V10.md` Uyarı 1). Bahsin oranı "
             "etkilemediği varsayılır. Canlı sonuç bu rakamlardan daha kötü beklenmelidir.\n")
    L.append("> **Uyarı 2 (Seçim eşikleri):** Değerci ve Stratejik eşikleri (p ≥ %8, model/AGF ≥ 1,5) tanı aşamasında aynı "
             "veride görüldü; bahis başına getirinin %95 aralığı sıfırı kapsıyor. Bu bir ipucudur, kanıt değildir.\n")
    L.append("> **Uyarı 3 (Kesinti dönemleri):** TJK kesintisi aylara göre yaklaşık %26 ile %55 arasında oynuyor (aşağıdaki "
             "tablo, ganyan oranlarından çıkarım). Sonuçlar bu karışıma bağlıdır.\n")
    L.append("> **Uyarı 4 (Yol örneklemesi):** \"Kârda bitenler\" ve \"iflas\" yüzdeleri 5 yıllık günlerin rastgele "
             "karışımıdır; bahis başına getirinin belirsizliğini yansıtmaz, o belirsizlik %95 aralık sütununda.\n")
    L.append(f"Kasa {BANK0:,.0f} TL, bahis {BASE:.0f} TL, günlük oyun; gerçek nihai ganyan ödemeleri; "
             f"{len(dates)} yarış günü (2022-01 .. 2026-11), {len(race1):,} koşu.\n")
    L.append("## Kumarbaz kartları\n")
    L.append("| Kumarbaz | Tür | Nasıl oynar |\n|---|---|---|")
    for name, _, _, tur, kural in PERSONAS:
        L.append(f"| {name} | {tur} | {kural} |")
    L.append(f"\n## Sonuç: 300 günlük oyun, {NPATH} rastgele yol (gün örneklemesi)\n")
    L.append("| Kumarbaz | Bahis/gün | İsabet | Tutan atın oranı (ort / medyan) | Bahis başına getiri [%95 aralık] | "
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
            cells.append(f"iflas (gün {x['bust'] + 1})" if x["bust"] is not None else f"{x['final']:,.0f}")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    L.append("\n## Yıl bazında bahis başına getiri (bahis sayısı)\n")
    L.append("| Kumarbaz | " + " | ".join(str(y) for y in YEARS) + " |\n|---|" + "---:|" * len(YEARS))
    for name, *_ in PERSONAS:
        L.append(f"| {name} | " + " | ".join(
            f"{res[name]['by_year'][y][1]:+.1%} ({res[name]['by_year'][y][0]})" for y in YEARS) + " |")
    L.append(f"\n## Kesintiye göre bahis başına getiri (koşunun Σ(1/ganyan) değeri {LOW_TAKEOUT_S} altı = kesinti yaklaşık %26 ve altı)\n")
    L.append("| Kumarbaz | Kesinti düşük: getiri (bahis) | Kesinti yüksek: getiri (bahis) |\n|---|---:|---:|")
    for name, *_ in PERSONAS:
        lo_n, lo_r = res[name]["low"]
        hi_n, hi_r = res[name]["high"]
        L.append(f"| {name} | {lo_r:+.1%} ({lo_n}) | {hi_r:+.1%} ({hi_n}) |")
    L.append("\n## Kıyas çıtaları (1 TL'lik bahis, bütün koşular)\n")
    L.append("| Yöntem | İsabet | Bahis başına getiri |\n|---|---:|---:|")
    for ad, h, r_ in bench:
        L.append(f"| {ad} | {h:.1%} | {r_:+.1%} |")
    L.append("\n## Veride görünen kesinti dönemleri (aylık medyan Σ(1/ganyan)'dan: kesinti = 1 − 1/Σ)\n")
    L.append("| Dönem | Kesinti |\n|---|---:|")
    for a, b, v in rejim(d):
        L.append(f"| {a} .. {b} | %{v * 100:.0f} |")
    L.append("\n## Ek ölçümler\n")
    for name, *_ in PERSONAS:
        r = res[name]
        L.append(f"- {name}: para ağırlıklı getiri {r['roi_money']:+.1%}, medyan en kötü düşüş {r['mdd']:.0%}, "
                 f"gerçek yıllarda en büyük tek ödeme {max(x['big'] for x in r['real'].values()):,.0f} TL")
    out = "\n".join(L)
    OUT.write_text(out + "\n", encoding="utf-8")
    print(f"\nyazıldı: {OUT}  ({time.time() - t0:.0f} sn)")


if __name__ == "__main__":
    main()
