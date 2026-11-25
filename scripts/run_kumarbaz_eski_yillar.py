#!/usr/bin/env python3
"""Kumarbaz simülasyonu: eski yıllarda sınama -> reports/KUMARBAZ_ESKI_YILLAR.md.

Soru: Değerci ve Dengeli Derya ipucu (2022-2026'da +%9 ve +%17) başka yıllarda da çıkıyor mu?
Kurallar scripts/run_kumarbaz_sim.py'dekiyle AYNI ve dondurulmuş: hiçbir eşik değişmedi. Eşikler 2022-2026 verisinde görülmüştü,
2017-2021'e bu kural için bakılmamıştı. V10 model tasarımı ise 2017-2021'de seçilmişti (reports/V10.md Uyarı 2): bu pencere modele
hafif lehine; öte yandan model her yıl yalnız önceki yıllarla eğitildiğinden 2019-2021'de daha az veriyle çalışır, aleyhine.
Canlı hatta, modellere ve uygulamaya dokunmaz.

Girdi (ikisi de git dışı): data/ganyan.db (salt okunur) ve data/v10_cache/pred_V10_HLB_CAL_*_<yıl>.pkl (2017-2026).

Çalıştır:  venv/bin/python scripts/run_kumarbaz_eski_yillar.py
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_kumarbaz_sim as ks  # noqa: E402

OUT = ks.REPO / "reports" / "KUMARBAZ_ESKI_YILLAR.md"
FIRST, LAST = "2017-01-01", "2026-12-31"
YEARS_ALL = list(range(2017, 2027))
PENCERELER = [("2017–2018", "2017", "2018", "ganyan kesintisi ≈%50"),
              ("2019–2021", "2019", "2021", "bağımsız pencere"),
              ("2022–2026", "2022", "2026", "ilk simülasyon"),
              ("2019–2026", "2019", "2026", "birleşik")]
KUMARBAZLAR = [("Mantıklı Mehmet", ks.p_mantikli), ("Plase Pınar", ks.p_plase),
               ("Değerci Deniz", ks.p_degerci), ("Dengeli Derya", ks.p_dengeli)]
DEGER = ("Değerci Deniz", "Dengeli Derya")


def pencere(dates, plans, first, last):
    """Yılı [first, last] aralığında olan günler ve planları."""
    ii = [i for i, x in enumerate(dates) if first <= x[:4] <= last]
    return [dates[i] for i in ii], [plans[i] for i in ii]


def ozet(dates, plans, s_of):
    """Bir pencerede bir kumarbazın özeti: bahis, isabet, getiri ve aralığı, yıllar, kesinti, uç ödemeler."""
    bets = [b for day in plans for b in day]
    p = ks.pooled(plans)
    roi, lo, hi = ks.unit_roi_ci(plans, ks.boots(len(plans))[1])
    o = np.array([b.odds for b in bets])
    w = np.array([b.win for b in bets])
    ret = w * o
    hits = np.sort(o[w == 1])[::-1]
    by_year = {}
    for x, day in zip(dates, plans):
        by_year.setdefault(x[:4], []).extend(day)
    return dict(
        n=p["n"], hit=p["hit"], roi=roi, lo=lo, hi=hi,
        beklenen=float(np.nanmean([b.p for b in bets])),
        yil={y: ks.unit_roi_n(v) for y, v in sorted(by_year.items())},
        dusuk=ks.unit_roi_n([b for b in bets if s_of[b.rid] < ks.LOW_TAKEOUT_S]),
        yuksek=ks.unit_roi_n([b for b in bets if s_of[b.rid] >= ks.LOW_TAKEOUT_S]),
        ilk25_cikar=float((ret.sum() - hits[:25].sum()) / len(bets) - 1),     # en büyük 25 ödeme hiç gelmemiş olsaydı
        sinir10=float(np.minimum(ret, 10).mean() - 1))                        # ödeme katı en çok 10 sayılsaydı


def main():
    t0 = time.time()
    d = ks.load(FIRST, LAST, YEARS_ALL)
    con = ks.ro()
    ex = ks.load_bets(con, FIRST, LAST)
    con.close()
    days = ks.build_days(d, ex)
    dates = sorted(days)
    race1 = d.drop_duplicates("race_id")
    s_of = dict(zip(race1.race_id, race1.S))
    print(f"veri {time.time() - t0:.1f}s | gün {len(dates)} koşu {len(race1)}", flush=True)

    planlar = {ad: [fn(days[x]) for x in dates] for ad, fn in KUMARBAZLAR}
    print(f"planlar {time.time() - t0:.1f}s", flush=True)
    res, cit, nrace = {}, {}, {}
    for pad, a, b, _ in PENCERELER:
        dw = d[(d.year >= int(a)) & (d.year <= int(b))]
        cit[pad], nrace[pad] = ks.cita(dw), dw.race_id.nunique()
        for ad, _ in KUMARBAZLAR:
            res[pad, ad] = ozet(*pencere(dates, planlar[ad], a, b), s_of)
    tum = {ad: ozet(*pencere(dates, planlar[ad], "2017", "2026"), s_of) for ad, _ in KUMARBAZLAR}

    L = ["# Kumarbaz simülasyonu: eski yıllarda sınama\n"]
    L.append("> **Uyarı 1 (Pencere):** Ganyan oranlarından çıkan kesinti 2017–2018'de ≈%50 görünüyor (kazananın ortalama ödemesi 4,1); "
             "2019'dan beri %26–36 (5,7 ve üstü). Karşılaştırma penceresi bu yüzden 2019'dan başlar, 2017–2018 yalnız bilgi içindir. "
             "Nedeni bilinmiyor (`bets` ile `runners.ganyan` tutarlı, en küçük ödeme her yıl 1,05).\n")
    L.append("> **Uyarı 2 (Ne sınanıyor):** Kurallar `scripts/run_kumarbaz_sim.py`'dekiyle aynı ve dondurulmuş, hiçbir eşik değişmedi. "
             "Değerci ve Dengeli Derya eşikleri 2022–2026 verisinde görülmüştü, 2017–2021'e bu kural için bakılmamıştı. V10 model tasarımı ise "
             "2017–2021'de seçilmişti (`reports/V10.md` Uyarı 2): bu pencere modele hafif lehine; öte yandan model her yıl yalnız önceki "
             "yıllarla eğitildiğinden 2019–2021'de daha az veriyle çalışır, aleyhine.\n")
    L.append("> **Uyarı 3 (Varsayımlar):** Kapanış oranı ve AGF varsayımı ile ödeme birimleri ana raporla aynıdır (`reports/KUMARBAZ.md` "
             "uyarıları); canlı sonuç daha kötü beklenmelidir.\n")
    L.append("## Ganyan çıtaları (1 TL'lik bahis, bütün koşular)\n")
    L.append("| Pencere | Koşu | Rastgele at | Favori | Modelin 1. tercihi | Model − favori |\n|---|---:|---:|---:|---:|---:|")
    for pad, _, _, not_ in PENCERELER:
        (_, _, r_), (_, _, f_), (_, _, m_) = cit[pad]
        L.append(f"| {pad} ({not_}) | {nrace[pad]:,} | {r_:+.1%} | {f_:+.1%} | {m_:+.1%} | {(m_ - f_) * 100:+.1f} puan |")
    L.append("\n## Dondurulmuş kurallarla sonuç\n")
    L.append("TL başına getiri; köşeli parantez %95 aralık (gün-kümeli örnekleme). İsabette parantez içi modelin beklentisidir.\n")
    L.append("| Pencere | Kumarbaz | Bahis | İsabet (beklenen) | TL başına getiri [%95 aralık] |\n|---|---|---:|---|---|")
    for pad, _, _, _ in PENCERELER:
        for ad, _ in KUMARBAZLAR:
            o = res[pad, ad]
            L.append(f"| {pad} | {ad} | {o['n']:,} | {o['hit']:.1%} ({o['beklenen']:.1%}) | {o['roi']:+.1%} [{o['lo']:+.1%}, {o['hi']:+.1%}] |")
    L.append("\n## Yıllara göre TL başına getiri (bahis sayısı)\n")
    L.append("| Kumarbaz | " + " | ".join(str(y) for y in YEARS_ALL) + " |\n|---|" + "---:|" * len(YEARS_ALL))
    for ad, _ in KUMARBAZLAR:
        yil = tum[ad]["yil"]
        L.append(f"| {ad} | " + " | ".join(
            f"{yil[str(y)][1]:+.1%} ({yil[str(y)][0]})" if yil.get(str(y), (0,))[0] else "—" for y in YEARS_ALL) + " |")
    L.append("\n## Kesintiye göre getiri ve uç ödemeler (yalnız değer arayanlar)\n")
    L.append(f"Kesinti düşük: koşunun Σ(1/ganyan) değeri {ks.LOW_TAKEOUT_S} altı (ganyan kesintisi yaklaşık %26 ve altı). "
             "\"25 çıkarılırsa\": en büyük 25 ödeme hiç gelmemiş sayılırsa getiri; \"sınırlıysa\": ödeme katı en çok 10 sayılırsa getiri.\n")
    L.append("| Pencere | Kumarbaz | Kesinti düşük: getiri (bahis) | Kesinti yüksek: getiri (bahis) | 25 çıkarılırsa | Sınırlıysa |\n|---|---|---|---|---:|---:|")
    for pad, _, _, _ in PENCERELER:
        for ad in DEGER:
            o = res[pad, ad]
            L.append(f"| {pad} | {ad} | {o['dusuk'][1]:+.1%} ({o['dusuk'][0]}) | {o['yuksek'][1]:+.1%} ({o['yuksek'][0]}) | "
                     f"{o['ilk25_cikar']:+.1%} | {o['sinir10']:+.1%} |")
    L.append("\n## Veride görünen ganyan kesinti dönemleri, 2017–2021 (aylık medyan Σ(1/ganyan)'dan: kesinti = 1 − 1/Σ)\n")
    L.append("| Dönem | Kesinti |\n|---|---:|")
    for a, b, v in ks.rejim(d[d.year <= 2021]):
        L.append(f"| {a} .. {b} | %{v * 100:.0f} |")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\nyazıldı: {OUT}  ({time.time() - t0:.0f} sn)")


if __name__ == "__main__":
    main()
