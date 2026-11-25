# Kumarbaz simülasyonu

> **Uyarı 1 (Kapanış oranı ve AGF):** Kumarbaz kapanışta oynayan, kapanış AGF'sini ve oranını gören kişi gibi modellenir; canlıda erken alınan AGF daha az bilgi taşır (bkz. `reports/V10.md` Uyarı 1). Bahsin oranı etkilemediği varsayılır. Canlı sonuç bu rakamlardan daha kötü beklenmelidir.

> **Uyarı 2 (Seçim eşikleri):** Değerci ve Stratejik eşikleri (p ≥ %8, model/AGF ≥ 1,5) tanı aşamasında aynı veride görüldü; bahis başına getirinin %95 aralığı sıfırı kapsıyor. Bu bir ipucudur, kanıt değildir.

> **Uyarı 3 (Kesinti dönemleri):** TJK kesintisi aylara göre yaklaşık %26 ile %55 arasında oynuyor (aşağıdaki tablo, ganyan oranlarından çıkarım). Sonuçlar bu karışıma bağlıdır.

> **Uyarı 4 (Yol örneklemesi):** "Kârda bitenler" ve "iflas" yüzdeleri 5 yıllık günlerin rastgele karışımıdır; bahis başına getirinin belirsizliğini yansıtmaz, o belirsizlik %95 aralık sütununda.

Kasa 10,000 TL, bahis 50 TL, günlük oyun; gerçek nihai ganyan ödemeleri; 1770 yarış günü (2022-01 .. 2026-11), 31,544 koşu.

## Kumarbaz kartları

| Kumarbaz | Tür | Nasıl oynar |
|---|---|---|
| Temkinli Tarık | Favori sever | Günün en güçlü 4 favorisine (kapanış oranı en kısa) 50 TL |
| Cesur Cemal | Sürpriz avcısı | En kalabalık 4 sahada oranı 10 ve üstü olan en kısa oranlı ata 50 TL |
| Bitik Bilal | Kaybı kovalayan | Günün ilk 6 koşusunda favori; kaybedince bahsi ikiye katlar, kazanınca 50 TL'ye döner, kasası yettiğince |
| Mantıklı Mehmet | Modeli izleyen | Modelin en emin olduğu 4 koşuda modelin 1. tercihine 50 TL |
| Değerci Deniz | Fark arayan | Modelin ihtimali AGF payının 1,5 katı ve %8 üstü olan atlar, günde en çok 6, 50 TL |
| Stratejik Selin | Hesaplı | Değerci'nin seçimi, ama bahis çeyrek Kelly (kasanın en çok %2'si, günlük en çok %8) |
| Rastgele Remzi | Kontrol (hiçbir şey bilmez) | Günde 4 rastgele koşuda rastgele at, 50 TL |

## Sonuç: 300 günlük oyun, 300 rastgele yol (gün örneklemesi)

| Kumarbaz | Bahis/gün | İsabet | Tutan atın oranı (ort / medyan) | Bahis başına getiri [%95 aralık] | Kasa sonu medyan (%10–%90) | Kârda bitenler | İflas | İflasta medyan gün |
|---|---:|---:|---:|---|---|---:|---:|---:|
| Temkinli Tarık | 4.0 | 49.5% | 1.4 / 1.4 | -30.5% [-32.2%, -28.9%] | 0 (0–5) | 0% | 100% | 163 |
| Cesur Cemal | 4.0 | 5.1% | 12.0 / 11.3 | -39.5% [-45.9%, -33.1%] | 0 (0–2) | 0% | 100% | 126 |
| Bitik Bilal | 6.0 | 36.3% | 1.9 / 1.8 | -30.6% [-32.5%, -28.8%] | 0 (0–0) | 0% | 100% | 10 |
| Mantıklı Mehmet | 4.0 | 50.9% | 1.5 / 1.4 | -23.3% [-25.1%, -21.5%] | 0 (0–4) | 0% | 100% | 216 |
| Değerci Deniz | 2.4 | 16.0% | 6.8 / 5.9 | +9.0% [-0.2%, +18.2%] | 13,319 (7,621–18,896) | 78% | 0% | 265 |
| Stratejik Selin | 2.4 | 16.0% | 6.8 / 5.9 | +9.0% [-0.2%, +18.2%] | 14,308 (6,959–33,684) | 72% | 0% | — |
| Rastgele Remzi | 4.0 | 11.7% | 5.0 / 3.1 | -42.0% [-47.2%, -36.0%] | 0 (0–2) | 0% | 100% | 113 |

## Gerçek takvim yılları (1 Ocak'ta 10.000 TL ile başlasaydı, kasa sonu; 2026 Kasım'a kadar)

| Kumarbaz | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|
| Temkinli Tarık | iflas (gün 169) | iflas (gün 156) | iflas (gün 207) | iflas (gün 175) | iflas (gün 138) |
| Cesur Cemal | iflas (gün 94) | iflas (gün 129) | iflas (gün 163) | iflas (gün 105) | iflas (gün 124) |
| Bitik Bilal | iflas (gün 7) | iflas (gün 8) | iflas (gün 22) | iflas (gün 13) | iflas (gün 20) |
| Mantıklı Mehmet | iflas (gün 243) | iflas (gün 203) | iflas (gün 262) | iflas (gün 213) | iflas (gün 197) |
| Değerci Deniz | 12,380 | 5,028 | 21,042 | 15,715 | 15,152 |
| Stratejik Selin | 22,204 | 4,233 | 21,232 | 18,662 | 22,005 |
| Rastgele Remzi | iflas (gün 85) | iflas (gün 94) | iflas (gün 105) | iflas (gün 113) | iflas (gün 148) |

## Yıl bazında bahis başına getiri (bahis sayısı)

| Kumarbaz | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|
| Temkinli Tarık | -31.4% (1460) | -35.4% (1404) | -24.7% (1452) | -29.1% (1460) | -32.6% (1304) |
| Cesur Cemal | -49.4% (1460) | -45.7% (1404) | -28.2% (1452) | -42.1% (1460) | -31.4% (1304) |
| Bitik Bilal | -29.5% (2190) | -34.7% (2106) | -28.8% (2178) | -29.0% (2190) | -31.4% (1956) |
| Mantıklı Mehmet | -23.3% (1460) | -25.2% (1404) | -19.5% (1452) | -23.3% (1460) | -25.5% (1304) |
| Değerci Deniz | +4.6% (1036) | -11.8% (842) | +26.4% (835) | +13.4% (851) | +14.3% (722) |
| Stratejik Selin | +4.6% (1036) | -11.8% (842) | +26.4% (835) | +13.4% (851) | +14.3% (722) |
| Rastgele Remzi | -45.2% (1460) | -46.0% (1404) | -37.1% (1452) | -44.4% (1460) | -36.8% (1304) |

## Kesintiye göre bahis başına getiri (koşunun Σ(1/ganyan) değeri 1.4 altı = kesinti yaklaşık %26 ve altı)

| Kumarbaz | Kesinti düşük: getiri (bahis) | Kesinti yüksek: getiri (bahis) |
|---|---:|---:|
| Temkinli Tarık | -24.0% (2325) | -33.8% (4755) |
| Cesur Cemal | -33.3% (1936) | -41.8% (5144) |
| Bitik Bilal | -26.7% (3480) | -32.6% (7140) |
| Mantıklı Mehmet | -21.0% (2378) | -24.5% (4702) |
| Değerci Deniz | +33.4% (1116) | +0.4% (3170) |
| Stratejik Selin | +33.4% (1116) | +0.4% (3170) |
| Rastgele Remzi | -41.2% (2213) | -42.3% (4867) |

## Kıyas çıtaları (1 TL'lik bahis, bütün koşular)

| Yöntem | İsabet | Bahis başına getiri |
|---|---:|---:|
| Her koşuda rastgele at | 10.5% | -38.9% |
| Her koşuda favori (kapanış oranı) | 34.3% | -31.4% |
| Her koşuda modelin 1. tercihi | 35.2% | -23.7% |

## Veride görünen kesinti dönemleri (aylık medyan Σ(1/ganyan)'dan: kesinti = 1 − 1/Σ)

| Dönem | Kesinti |
|---|---:|
| 2022-01 .. 2022-06 | %31 |
| 2022-07 .. 2022-07 | %35 |
| 2022-08 .. 2022-10 | %36 |
| 2022-11 .. 2023-03 | %31 |
| 2023-04 .. 2023-04 | %36 |
| 2023-05 .. 2023-05 | %35 |
| 2023-06 .. 2023-06 | %31 |
| 2023-07 .. 2023-08 | %55 |
| 2023-09 .. 2023-09 | %54 |
| 2023-10 .. 2023-11 | %31 |
| 2023-12 .. 2024-09 | %26 |
| 2024-10 .. 2024-10 | %25 |
| 2024-11 .. 2024-11 | %16 |
| 2024-12 .. 2024-12 | %40 |
| 2025-01 .. 2025-01 | %41 |
| 2025-02 .. 2025-02 | %40 |
| 2025-03 .. 2025-10 | %26 |
| 2025-11 .. 2025-12 | %31 |
| 2026-01 .. 2026-01 | %37 |
| 2026-02 .. 2026-06 | %33 |
| 2026-07 .. 2026-08 | %26 |
| 2026-09 .. 2026-11 | %31 |

## Ek ölçümler

- Temkinli Tarık: para ağırlıklı getiri -30.6%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 120 TL
- Cesur Cemal: para ağırlıklı getiri -38.3%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 940 TL
- Bitik Bilal: para ağırlıklı getiri -33.5%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 7,200 TL
- Mantıklı Mehmet: para ağırlıklı getiri -23.0%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 248 TL
- Değerci Deniz: para ağırlıklı getiri +9.3%, medyan en kötü düşüş 25%, gerçek yıllarda en büyük tek ödeme 1,390 TL
- Stratejik Selin: para ağırlıklı getiri +11.6%, medyan en kötü düşüş 38%, gerçek yıllarda en büyük tek ödeme 3,539 TL
- Rastgele Remzi: para ağırlıklı getiri -41.7%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 1,712 TL
