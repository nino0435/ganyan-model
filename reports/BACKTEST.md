# Ganyan — Aylık İleri-Yürüyen (Walk-Forward) ve Kupon Backtest Raporu

> **Uyarı (§3.2):** Tarihsel AGF değerleri kapanış değerleridir; canlıda koşudan önce alınan AGF daha az bilgi içerir → canlı performans biraz daha düşük beklenir. Bunu Faz 3 ileri testi ölçecek.

## 1. Aylık İleri-Yürüyen Model Performansı (2025-07 … 2026-10)

| Ay | Koşu | AGF Fav 1.Tercih | Ganyan Fav 1.Tercih | v1_noagf 1.Tercih | v1_agf 1.Tercih | AGF Log-Loss | v1_noagf Log-Loss | v1_agf Log-Loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025-07 | 591 | 33.0% | 35.4% | 29.8% | 34.2% | 1.7673 | 1.8956 | 1.7552 |
| 2025-08 | 603 | 31.7% | 30.3% | 24.4% | 30.0% | 1.8319 | 1.9559 | 1.8478 |
| 2025-09 | 568 | 33.3% | 33.1% | 27.1% | 30.8% | 1.8153 | 1.9465 | 1.8227 |
| 2025-10 | 589 | 32.6% | 33.4% | 27.0% | 33.6% | 1.8207 | 1.9440 | 1.8158 |
| 2025-11 | 531 | 33.9% | 32.4% | 26.9% | 34.1% | 1.8454 | 1.9596 | 1.8337 |
| 2025-12 | 474 | 35.2% | 34.0% | 28.7% | 36.5% | 1.7918 | 1.9640 | 1.7873 |
| 2026-01 | 457 | 33.3% | 32.8% | 32.4% | 36.8% | 1.7741 | 1.8791 | 1.7586 |
| 2026-02 | 420 | 39.3% | 37.9% | 34.8% | 39.5% | 1.6894 | 1.8155 | 1.6994 |
| 2026-03 | 464 | 36.6% | 38.1% | 30.2% | 37.5% | 1.7179 | 1.8455 | 1.7089 |
| 2026-04 | 502 | 35.9% | 34.9% | 32.5% | 35.3% | 1.7841 | 1.8862 | 1.7765 |
| 2026-05 | 555 | 33.0% | 32.4% | 27.2% | 32.6% | 1.8468 | 1.9754 | 1.8441 |
| 2026-06 | 529 | 33.6% | 32.5% | 28.2% | 34.2% | 1.8432 | 1.9670 | 1.8339 |
| 2026-07 | 550 | 32.5% | 32.2% | 29.3% | 32.7% | 1.8221 | 1.9325 | 1.8080 |
| 2026-08 | 561 | 34.0% | 32.1% | 24.8% | 32.8% | 1.8549 | 1.9951 | 1.8461 |
| 2026-09 | 508 | 33.3% | 32.7% | 27.0% | 33.9% | 1.8533 | 1.9939 | 1.8497 |
| 2026-10 | 459 | 31.2% | 33.8% | 26.4% | 31.2% | 1.8846 | 1.9461 | 1.8790 |

### Tüm Dönem Özet ve Koşu-Eşli Bootstrap (%95 GA, 2000 örnek)

- **Toplam Değerlendirilen Koşu:** 8361
- **AGF Favorisi:** 1. tercih `33.78%`, log-loss `1.8113`
- **Model (v1_noagf):** 1. tercih `28.35%`, log-loss `1.9342` | Fark vs AGF: `-5.43%` (%95 GA `-6.42%` … `-4.40%`)
- **Model + AGF (v1_agf):** 1. tercih `33.92%`, log-loss `1.8066` | Fark vs AGF: `+0.14%` (%95 GA `-0.45%` … `+0.74%`)
- **Ganyan Favorisi (son oran):** 1. tercih `33.50%`, log-loss `1.8338` | Fark vs AGF: `-0.28%` (%95 GA `-0.94%` … `+0.39%`)

## 2. Altılı İkramiye Tahmin Modeli (`y = a_şehir + b·x`)

- **Test Altılı Sayısı:** 1657
- **Eğim (`b`):** `-0.9652` (`b < 0` doğrulandı: sürpriz kazananlar ikramiyeyi büyütür)
- **Log-İkramiye Test $R^2$:** `0.9016`
- **Medyan Mutlak Yüzde Hata (MdAPE):** `%36.9`

## 3. Kupon Dağıtıcı Backtest Tablosu (§3.5)

> **Not (K8):** Para, maliyet ve ROI hesapları yalnızca birim fiyatı bilinen **2026** altılıları (`1,25 TL`) üzerinden yapılmıştır; 6/6 isabet ve ortalama ayak tüm test dönemini kapsar.

| Bütçe (TL) | Yöntem | Altılı (Toplam / 2026) | 6/6 Tutan | 6/6 Oranı | Ort. Ayak | Sabit-k Fark (%95 GA) | AGF-Amaç A Fark (%95 GA) | 2026 Maliyet (TL) | 2026 Dönüş (TL) | 2026 ROI | Aylık ROI Std |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 250 | (i) Sabit-k (AGF) | 1628 / 972 | 38 | 2.33% | 3.31 | — | -4.18% (-5.41%…-2.89%) | 77,760 | 44,284 | -43.1% | 0.72 |
| 250 | (ii) AGF — Amaç A | 1628 / 972 | 106 | 6.51% | 3.92 | +4.18% (+2.95%…+5.41%) | — | 229,085 | 95,622 | -58.3% | 0.21 |
| 250 | (iii) Model (v1_agf) — Amaç A | 1628 / 972 | 117 | 7.19% | 3.93 | +4.85% (+3.62%…+6.14%) | +0.68% (-0.37%…+1.66%) | 228,996 | 137,564 | -39.9% | 0.40 |
| 250 | (iv) Model (v1_agf) — Amaç B | 1628 / 972 | 2 | 0.12% | 2.01 | -2.21% (-3.01%…-1.47%) | -6.39% (-7.68%…-5.22%) | 230,869 | 1,119,140 | +384.8% *(tek ikramiye kaynaklı, güvenilmez)* | 13.47 |
| 500 | (i) Sabit-k (AGF) | 1628 / 972 | 38 | 2.33% | 3.31 | — | -7.00% (-8.42%…-5.65%) | 77,760 | 44,284 | -43.1% | 0.72 |
| 500 | (ii) AGF — Amaç A | 1628 / 972 | 152 | 9.34% | 4.17 | +7.00% (+5.71%…+8.42%) | — | 456,754 | 191,426 | -58.1% | 0.19 |
| 500 | (iii) Model (v1_agf) — Amaç A | 1628 / 972 | 183 | 11.24% | 4.18 | +8.91% (+7.43%…+10.44%) | +1.90% (+0.68%…+3.07%) | 455,579 | 270,033 | -40.7% | 0.29 |
| 500 | (iv) Model (v1_agf) — Amaç B | 1628 / 972 | 3 | 0.18% | 2.28 | -2.15% (-2.95%…-1.41%) | -9.15% (-10.63%…-7.74%) | 461,205 | 1,119,140 | +142.7% *(tek ikramiye kaynaklı, güvenilmez)* | 6.68 |
| 1000 | (i) Sabit-k (AGF) | 1628 / 972 | 152 | 9.34% | 4.12 | — | -4.91% (-6.63%…-3.13%) | 885,735 | 382,159 | -56.9% | 0.25 |
| 1000 | (ii) AGF — Amaç A | 1628 / 972 | 232 | 14.25% | 4.39 | +4.91% (+3.13%…+6.76%) | — | 913,228 | 344,536 | -62.3% | 0.10 |
| 1000 | (iii) Model (v1_agf) — Amaç A | 1628 / 972 | 256 | 15.72% | 4.42 | +6.39% (+4.67%…+8.17%) | +1.47% (+0.18%…+2.76%) | 911,141 | 456,245 | -49.9% | 0.17 |
| 1000 | (iv) Model (v1_agf) — Amaç B | 1628 / 972 | 4 | 0.25% | 2.55 | -9.09% (-10.63%…-7.62%) | -14.00% (-15.72%…-12.35%) | 920,312 | 1,119,140 | +21.6% *(tek ikramiye kaynaklı, güvenilmez)* | 3.34 |
| 2500 | (i) Sabit-k (AGF) | 1628 / 972 | 152 | 9.34% | 4.12 | — | -12.47% (-14.50%…-10.32%) | 885,735 | 382,159 | -56.9% | 0.25 |
| 2500 | (ii) AGF — Amaç A | 1628 / 972 | 355 | 21.81% | 4.70 | +12.47% (+10.32%…+14.56%) | — | 2,289,781 | 868,707 | -62.1% | 0.18 |
| 2500 | (iii) Model (v1_agf) — Amaç A | 1628 / 972 | 364 | 22.36% | 4.71 | +13.02% (+11.06%…+14.99%) | +0.55% (-0.92%…+2.03%) | 2,281,154 | 1,164,033 | -49.0% | 0.21 |
| 2500 | (iv) Model (v1_agf) — Amaç B | 1628 / 972 | 6 | 0.37% | 2.94 | -8.97% (-10.38%…-7.56%) | -21.44% (-23.46%…-19.53%) | 2,300,978 | 1,127,002 | -51.0% *(tek ikramiye kaynaklı, güvenilmez)* | 1.36 |
| 5000 | (i) Sabit-k (AGF) | 1628 / 972 | 152 | 9.34% | 4.12 | — | -19.41% (-21.62%…-17.07%) | 885,735 | 382,159 | -56.9% | 0.25 |
| 5000 | (ii) AGF — Amaç A | 1628 / 972 | 468 | 28.75% | 4.91 | +19.41% (+17.14%…+21.56%) | — | 4,591,946 | 1,976,856 | -56.9% | 0.12 |
| 5000 | (iii) Model (v1_agf) — Amaç A | 1628 / 972 | 484 | 29.73% | 4.94 | +20.39% (+18.24%…+22.54%) | +0.98% (-0.55%…+2.58%) | 4,590,485 | 2,375,208 | -48.3% | 0.19 |
| 5000 | (iv) Model (v1_agf) — Amaç B | 1628 / 972 | 16 | 0.98% | 3.26 | -8.35% (-9.89%…-6.88%) | -27.76% (-30.10%…-25.37%) | 4,619,222 | 1,185,314 | -74.3% *(tek ikramiye kaynaklı, güvenilmez)* | 0.68 |

## 4. Karar Kapısı — Go / No-Go (§3.6)

- **Birincil Karşılaştırma — `(iii) Model — Amaç A` vs `(ii) AGF — Amaç A` (Eşit Harcama):** Model Amaç A, 5 bütçenin tamamında AGF Amaç A'dan daha yüksek 6/6 oranına sahiptir (`+0.55%` ile `+1.90%` arası); ancak %95 GA alt sınırı > 0 olan bütçe sayısı **`2 / 5`** (`500 TL` ve `1000 TL` bütçeleri). Eşik `3 / 5` olduğu için **"akıllı kupon" kapısı geçmedi**.
- **Harcama Etkisi Notu (`(iii)` ve `(ii)`'nin `(i) Sabit-k`'ya Üstünlüğü):** `(i) Sabit-k` bütçeyi dolduramamaktadır (ör. `250 TL` bütçede `77.760 TL` vs `228.996 TL`; `5000 TL` bütçede `885.735 TL` vs `4.590.485 TL` harcamaktadır). Bu nedenle `(iii)`'ün `(i) Sabit-k`'ya karşı `5 / 5` bütçedeki yüksek farkı modelin tahmin gücünden değil, açgözlü dağıtıcının bütçeyi tam kullanmasından (**harcama etkisinden**) kaynaklanmaktadır ve aynı kazanım `(ii) AGF — Amaç A` ile de elde edilmektedir.
- **Karar:** **GEÇEMEDİ (NO-GO — "Akıllı Kupon" iddiası kullanılmayacak; özellik "Maliyet + Olasılık Hesaplayıcı" olarak konumlandırılacak)**
- **Kâr (ROI) İddiası:** Şartname §3.6 gereği hiçbir koşulda kâr iddiası verilmez. `(iv) Amaç B` ROI satırları tek bir büyük ikramiyeden (`1.119.140 TL`) kaynaklanmaktadır ve güvenilmezdir.

## 5. Doğrulamalar (§10 — Ölçülerek Çözülen Maddeler)

1. **`Son 6 Yarış` içindeki `0` derecenin anlamı:** Veritabanındaki `16.431` eşleşen örnekte, bir önceki koşudaki gerçek bitiriş derecesi (`prev_finish`) incelendi. Oranın **%99,31**'inde atın gerçek derecesi **`>= 10`** (10., 11., 12. vb.; ilk 20 örneğin tamamında 10–18 arası) çıktı. Yani `0` tek haneli gösterimde **10. veya daha geride bitirişi (ilk 9 dışı)** ifade etmektedir.
2. **`KGS` ve `s20` anlamı:** `113.110` koşucu kaydında `KGS` değeri ile `date − önceki_yarış_tarihi` (gün farkı) karşılaştırıldı; **%99,75** oranında birebir eşit olduğu doğrulandı (`KGS` = Koşmaz Gün Sayısı / son koşudan beri geçen gün). `s20` ise `0..20` tam sayı aralığında (medyan `17`) TJK'nin 20 üzerinden son 20 günlük/idman form puanıdır.
3. **Geçmiş program CSV'lerindeki AGF ile kapanış AGF'si:** Rastgele seçilen 100 geçmiş program CSV dosyasındaki `7.400` koşucunun tamamında (**%100,00**) program CSV'sindeki `agf_pct` ve `agf_rank` değerlerinin sonuç CSV'sindeki kapanış AGF değerleriyle birebir aynı olduğu doğrulandı (TJK yarış bittikten sonra program CSV'sini son AGF ile arşivliyor).
4. **Canlı AGF güncellenme sıklığı ve CDN önbelleği:** Yarış günü program CSV'si gün içinde AGF oranlarıyla güncellenmektedir; `?t=<unix>` sorgu parametresi ile CDN önbelleği atlatılarak veya `X-Requested-With: XMLHttpRequest` başlıklı canlı HTML tablosundan (`-AGFORAN` ve `-Gny`) anlık olarak okunabilmektedir.
5. **Altılı birim fiyatı (1,25 TL) ve ikramiyenin 1 birim başına yazıldığı:** TJK CSV'lerinde `6'LI GANYAN(...) :X TL` tutarının 1 birimlik kupon başına düşen ikramiye olduğu ve 2026 birim fiyatının `1,25 TL` olduğu **varsayım** olarak korunmuştur (resmi TJK statik sayfalarında birim fiyat tablosu yer almamaktadır).
