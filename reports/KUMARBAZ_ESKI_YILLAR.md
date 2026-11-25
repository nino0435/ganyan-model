# Kumarbaz simülasyonu: eski yıllarda sınama

> **Uyarı 1 (Pencere):** Ganyan oranlarından çıkan kesinti 2017–2018'de ≈%50 görünüyor (kazananın ortalama ödemesi 4,1); 2019'dan beri %26–36 (5,7 ve üstü). Karşılaştırma penceresi bu yüzden 2019'dan başlar, 2017–2018 yalnız bilgi içindir. Nedeni bilinmiyor (`bets` ile `runners.ganyan` tutarlı, en küçük ödeme her yıl 1,05).

> **Uyarı 2 (Ne sınanıyor):** Kurallar `scripts/run_kumarbaz_sim.py`'dekiyle aynı ve dondurulmuş, hiçbir eşik değişmedi. Değerci ve Dengeli Derya eşikleri 2022–2026 verisinde görülmüştü, 2017–2021'e bu kural için bakılmamıştı. V10 model tasarımı ise 2017–2021'de seçilmişti (`reports/V10.md` Uyarı 2): bu pencere modele hafif lehine; öte yandan model her yıl yalnız önceki yıllarla eğitildiğinden 2019–2021'de daha az veriyle çalışır, aleyhine.

> **Uyarı 3 (Varsayımlar):** Kapanış oranı ve AGF varsayımı ile ödeme birimleri ana raporla aynıdır (`reports/KUMARBAZ.md` uyarıları); canlı sonuç daha kötü beklenmelidir.

## Ganyan çıtaları (1 TL'lik bahis, bütün koşular)

| Pencere | Koşu | Rastgele at | Favori | Modelin 1. tercihi | Model − favori |
|---|---:|---:|---:|---:|---:|
| 2017–2018 (ganyan kesintisi ≈%50) | 11,056 | -57.8% | -44.2% | -37.2% | +7.0 puan |
| 2019–2021 (bağımsız pencere) | 16,665 | -39.0% | -31.6% | -23.6% | +8.0 puan |
| 2022–2026 (ilk simülasyon) | 31,544 | -38.9% | -31.4% | -23.7% | +7.7 puan |
| 2019–2026 (birleşik) | 48,209 | -39.0% | -31.5% | -23.7% | +7.8 puan |

## Dondurulmuş kurallarla sonuç

TL başına getiri; köşeli parantez %95 aralık (gün-kümeli örnekleme). İsabette parantez içi modelin beklentisidir.

| Pencere | Kumarbaz | Bahis | İsabet (beklenen) | TL başına getiri [%95 aralık] |
|---|---|---:|---|---|
| 2017–2018 | Mantıklı Mehmet | 2,908 | 47.2% (47.2%) | -30.8% [-33.7%, -27.8%] |
| 2017–2018 | Plase Pınar | 2,729 | 53.3% (56.6%) | -19.7% [-23.2%, -15.9%] |
| 2017–2018 | Değerci Deniz | 2,813 | 13.1% (15.2%) | -34.3% [-40.7%, -27.1%] |
| 2017–2018 | Dengeli Derya | 1,352 | 26.4% (28.9%) | -10.3% [-24.6%, +8.9%] |
| 2019–2021 | Mantıklı Mehmet | 4,052 | 47.3% (47.2%) | -23.3% [-26.0%, -20.6%] |
| 2019–2021 | Plase Pınar | 4,035 | 60.4% (64.4%) | -17.8% [-20.6%, -15.1%] |
| 2019–2021 | Değerci Deniz | 3,051 | 14.0% (14.2%) | +0.7% [-9.3%, +11.7%] |
| 2019–2021 | Dengeli Derya | 1,989 | 27.8% (28.3%) | +2.7% [-15.9%, +25.9%] |
| 2022–2026 | Mantıklı Mehmet | 7,080 | 50.9% (52.7%) | -23.3% [-25.1%, -21.5%] |
| 2022–2026 | Plase Pınar | 7,063 | 63.6% (69.5%) | -11.5% [-13.9%, -8.8%] |
| 2022–2026 | Değerci Deniz | 4,286 | 16.0% (14.9%) | +9.0% [-0.2%, +18.2%] |
| 2022–2026 | Dengeli Derya | 2,752 | 30.1% (29.8%) | +17.2% [+6.9%, +27.8%] |
| 2019–2026 | Mantıklı Mehmet | 11,132 | 49.6% (50.7%) | -23.3% [-24.9%, -21.8%] |
| 2019–2026 | Plase Pınar | 11,098 | 62.5% (67.6%) | -13.8% [-15.7%, -11.8%] |
| 2019–2026 | Değerci Deniz | 7,337 | 15.2% (14.6%) | +5.5% [-1.4%, +12.2%] |
| 2019–2026 | Dengeli Derya | 4,741 | 29.1% (29.2%) | +11.1% [+0.7%, +22.6%] |

## Yıllara göre TL başına getiri (bahis sayısı)

| Kumarbaz | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Mantıklı Mehmet | -30.4% (1452) | -31.1% (1456) | -24.5% (1456) | -22.5% (1136) | -22.9% (1460) | -23.3% (1460) | -25.2% (1404) | -19.5% (1452) | -23.3% (1460) | -25.5% (1304) |
| Plase Pınar | -18.8% (1354) | -20.7% (1375) | -21.3% (1448) | -16.8% (1131) | -15.1% (1456) | -13.8% (1456) | -15.0% (1398) | -7.3% (1451) | -14.4% (1459) | -6.6% (1299) |
| Değerci Deniz | -37.7% (1533) | -30.3% (1280) | -1.7% (1113) | +2.4% (956) | +1.7% (982) | +4.6% (1036) | -11.8% (842) | +26.4% (835) | +13.4% (851) | +14.3% (722) |
| Dengeli Derya | -2.2% (713) | -19.4% (639) | -0.2% (751) | +13.9% (599) | -4.4% (639) | +4.3% (689) | -7.8% (530) | +32.9% (507) | +41.7% (556) | +18.5% (470) |

## Kesintiye göre getiri ve uç ödemeler (yalnız değer arayanlar)

Kesinti düşük: koşunun Σ(1/ganyan) değeri 1.4 altı (ganyan kesintisi yaklaşık %26 ve altı). "25 çıkarılırsa": en büyük 25 ödeme hiç gelmemiş sayılırsa getiri; "sınırlıysa": ödeme katı en çok 10 sayılırsa getiri.

| Pencere | Kumarbaz | Kesinti düşük: getiri (bahis) | Kesinti yüksek: getiri (bahis) | 25 çıkarılırsa | Sınırlıysa |
|---|---|---|---|---:|---:|
| 2017–2018 | Değerci Deniz | -40.0% (56) | -34.2% (2757) | -43.5% | -35.0% |
| 2017–2018 | Dengeli Derya | -11.5% (20) | -10.3% (1332) | -36.9% | -20.5% |
| 2019–2021 | Değerci Deniz | +3.5% (774) | -0.3% (2277) | -13.1% | -8.6% |
| 2019–2021 | Dengeli Derya | -2.8% (482) | +4.5% (1507) | -31.3% | -19.2% |
| 2022–2026 | Değerci Deniz | +33.4% (1116) | +0.4% (3170) | -1.8% | -2.5% |
| 2022–2026 | Dengeli Derya | +36.1% (679) | +11.1% (2073) | -0.8% | +7.8% |
| 2019–2026 | Değerci Deniz | +21.1% (1890) | +0.1% (5447) | -1.1% | -5.0% |
| 2019–2026 | Dengeli Derya | +19.9% (1161) | +8.3% (3580) | -7.3% | -3.5% |

## Veride görünen ganyan kesinti dönemleri, 2017–2021 (aylık medyan Σ(1/ganyan)'dan: kesinti = 1 − 1/Σ)

| Dönem | Kesinti |
|---|---:|
| 2017-01 .. 2017-01 | %51 |
| 2017-02 .. 2017-03 | %50 |
| 2017-04 .. 2017-04 | %51 |
| 2017-05 .. 2017-06 | %50 |
| 2017-07 .. 2017-07 | %51 |
| 2017-08 .. 2018-06 | %50 |
| 2018-07 .. 2018-08 | %51 |
| 2018-09 .. 2018-12 | %50 |
| 2019-01 .. 2019-03 | %26 |
| 2019-04 .. 2019-11 | %36 |
| 2019-12 .. 2020-08 | %26 |
| 2020-09 .. 2020-11 | %36 |
| 2020-12 .. 2021-01 | %26 |
| 2021-02 .. 2021-02 | %30 |
| 2021-03 .. 2021-10 | %31 |
| 2021-11 .. 2021-11 | %26 |
| 2021-12 .. 2021-12 | %30 |
