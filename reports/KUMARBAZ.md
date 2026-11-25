# Kumarbaz simülasyonu

> **Uyarı 1 (Kapanış oranı ve AGF):** Kumarbaz kapanışta oynayan, kapanış AGF'sini ve oranını gören kişi gibi modellenir; canlıda erken alınan AGF daha az bilgi taşır (bkz. `reports/V10.md` Uyarı 1). Bahsin oranı etkilemediği varsayılır. Canlı sonuç bu rakamlardan daha kötü beklenmelidir.

> **Uyarı 2 (Seçim eşikleri):** Değerci ve Stratejik eşikleri (p ≥ %8, model/AGF ≥ 1,5) tanı aşamasında aynı veride görüldü; bahis başına getirinin %95 aralığı sıfırı kapsıyor. Bu bir ipucudur, kanıt değildir. Dengeli Derya aynı eşikleri kullanır.

> **Uyarı 3 (Kesinti dönemleri):** TJK kesintisi aylara göre yaklaşık %26 ile %55 arasında oynuyor (aşağıdaki tablo, ganyan oranlarından çıkarım). Sonuçlar bu karışıma bağlıdır.

> **Uyarı 4 (Yol örneklemesi):** "Kârda bitenler" ve "iflas" yüzdeleri günlerin rastgele karışımıdır; bahis başına getirinin belirsizliğini yansıtmaz, o belirsizlik %95 aralık sütununda. Üçlü Ümit ve altılı kumarbazlarının yolları yalnız oynayabildikleri günlerden örneklenir.

> **Uyarı 5 (Ödeme birimleri):** Üçlüde ve altılıda ödeme "birim bilet" başınadır ve birim zamanla değişti. Üçlü: ödemenin aynı koşudaki sıralı ikili ödemesine oranı Haziran 2025'te iki katına çıkıyor; birim 2 TL alındı ve rastgele oynayanın kaybının kesintiyle uyumlu çıkması bunu doğruluyor (aşağıda "Rastgele" satırı), ama birim çıkarımdır, resmi değildir; üçlü yalnız 2025-06-01'den sonra. Altılı: birim 1.25 TL yalnız 2026 için (`ganyan/backtest.py` varsayımı), altılı paraları yalnız 2026. Plase, ikili, sıralı ikili ve çifte 1 TL'ye göredir (oranları yıllarca sabit).

Kasa 10,000 TL, bahis 50 TL (altılıda kupon bedeli, en çok 200 TL), günlük oyun; gerçek ödemeler; 1770 yarış günü (2022-01 .. 2026-11), 31,544 koşu.

## Kumarbaz kartları

| Kumarbaz | Tür | Nasıl oynar |
|---|---|---|
| Temkinli Tarık | Favori sever | Günün en güçlü 4 favorisine (kapanış oranı en kısa) 50 TL |
| Cesur Cemal | Sürpriz avcısı | En kalabalık 4 sahada oranı 10 ve üstü olan en kısa oranlı ata 50 TL |
| Bitik Bilal | Kaybı kovalayan | Günün ilk 6 koşusunda favori; kaybedince bahsi ikiye katlar, kazanınca 50 TL'ye döner, kasası yettiğince |
| Mantıklı Mehmet | Modeli izleyen | Modelin en emin olduğu 4 koşuda modelin 1. tercihine 50 TL |
| Değerci Deniz | Fark arayan | Modelin ihtimali AGF payının 1,5 katı ve %8 üstü olan atlar, günde en çok 6, 50 TL |
| Stratejik Selin | Hesaplı | Değerci'nin seçimi, ama bahis çeyrek Kelly (kasanın en çok %2'si, günlük en çok %8) |
| Plase Pınar | Güvenli oyuncu | Plase oynanan koşularda modelin en emin olduğu 4 koşuda modelin 1. tercihine plase (ilk ikiye girmesi yeter) 50 TL |
| Dengeli Derya | Değeri güvenli oynayan | Değerci'nin atları (model ihtimali AGF payının 1,5 katı ve %8 üstü), plase oynanan koşularda, günde en çok 6, plase 50 TL |
| İkili İlhan | Eşleştirmeci | İkili oynanan koşularda modelin en emin olduğu 4 koşuda modelin ilk 2 tercihi (sırası önemsiz) 50 TL |
| Sıralı Sibel | Sıra bilen | Sıralı ikili oynanan koşularda modelin en emin olduğu 4 koşuda modelin 1. ve 2. tercihi sırasıyla 50 TL |
| Üçlü Ümit | Büyük vurgun avcısı | Üçlü oynanan koşularda modelin en emin olduğu 4 koşuda modelin ilk 3 tercihinin 6 sırası, 50 TL bölünerek; yalnız Haz 2025'ten sonra |
| Çifte Çağla | İkiye katlayan | Art arda iki koşunun (çifte) en emin olunan 4 çiftesinde iki koşunun da modelin 1. tercihi, 50 TL |
| Altılı Ayşe | Kuponcu (model) | Günün altılıları arasında modelin en çok tutturacağı olana 200 TL'lik kupon (en çok 160 kombinasyon, repodaki dağıtıcı, model olasılıkları); yalnız 2026 |
| Kuponcu Kemal | Kuponcu (kalabalığı izler) | Aynı kupon, ama AGF'ye (kalabalığın seçimine) göre doldurulur; yalnız 2026 |
| Rastgele Remzi | Kontrol (hiçbir şey bilmez) | Günde 4 rastgele koşuda rastgele at, 50 TL |

## Sonuç: 300 günlük oyun, 300 rastgele yol (gün örneklemesi)

| Kumarbaz | Bahis/gün | İsabet | Tutan bahsin ödeme katı (ort / medyan) | TL başına getiri [%95 aralık] | Kasa sonu medyan (%10–%90) | Kârda bitenler | İflas | İflasta medyan gün |
|---|---:|---:|---:|---|---|---:|---:|---:|
| Temkinli Tarık | 4.0 | 49.5% | 1.4 / 1.4 | -30.5% [-32.2%, -28.9%] | 0 (0–5) | 0% | 100% | 163 |
| Cesur Cemal | 4.0 | 5.1% | 12.0 / 11.3 | -39.5% [-45.9%, -33.1%] | 0 (0–2) | 0% | 100% | 126 |
| Bitik Bilal | 6.0 | 36.3% | 1.9 / 1.8 | -30.6% [-32.5%, -28.8%] | 0 (0–0) | 0% | 100% | 10 |
| Mantıklı Mehmet | 4.0 | 50.9% | 1.5 / 1.4 | -23.3% [-25.1%, -21.5%] | 0 (0–4) | 0% | 100% | 216 |
| Değerci Deniz | 2.4 | 16.0% | 6.8 / 5.9 | +9.0% [-0.2%, +18.2%] | 13,319 (7,621–18,896) | 78% | 0% | 265 |
| Stratejik Selin | 2.4 | 16.0% | 6.8 / 5.9 | +9.0% [-0.2%, +18.2%] | 14,308 (6,959–33,684) | 72% | 0% | — |
| Plase Pınar | 4.0 | 63.6% | 1.4 / 1.1 | -11.5% [-13.9%, -8.8%] | 2,918 (703–5,825) | 0% | 3% | 293 |
| Dengeli Derya | 1.6 | 30.1% | 3.9 / 2.8 | +17.2% [+6.9%, +27.8%] | 13,595 (9,929–17,418) | 90% | 0% | — |
| İkili İlhan | 4.0 | 27.2% | 2.9 / 2.8 | -19.8% [-23.0%, -16.7%] | 0 (0–1,015) | 0% | 83% | 236 |
| Sıralı Sibel | 4.0 | 20.1% | 3.8 / 3.6 | -24.2% [-27.7%, -20.3%] | 0 (0–5) | 0% | 95% | 192 |
| Üçlü Ümit | 4.0 | 18.2% | 4.2 / 3.3 | -23.6% [-32.9%, -13.6%] | 0 (0–716) | 0% | 89% | 184 |
| Çifte Çağla | 4.0 | 19.9% | 3.7 / 3.3 | -27.3% [-30.9%, -23.3%] | 0 (0–5) | 0% | 99% | 183 |
| Altılı Ayşe | 0.9 | 10.7% | 6.2 / 5.5 | -33.7% [-57.7%, -4.6%] | 0 (0–9) | 1% | 91% | 140 |
| Kuponcu Kemal | 0.9 | 9.8% | 5.5 / 5.5 | -46.6% [-66.3%, -23.6%] | 0 (0–0) | 0% | 100% | 112 |
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
| Plase Pınar | iflas (gün 365) | iflas (gün 343) | 4,678 | iflas (gün 342) | 5,698 |
| Dengeli Derya | 11,468 | 7,945 | 18,350 | 21,592 | 14,352 |
| İkili İlhan | iflas (gün 220) | iflas (gün 189) | iflas (gün 332) | iflas (gün 245) | 1,725 |
| Sıralı Sibel | iflas (gün 177) | iflas (gün 166) | iflas (gün 209) | iflas (gün 144) | iflas (gün 281) |
| Üçlü Ümit | — | — | — | iflas (gün 343) | iflas (gün 237) |
| Çifte Çağla | iflas (gün 234) | iflas (gün 139) | iflas (gün 212) | iflas (gün 153) | iflas (gün 153) |
| Altılı Ayşe | — | — | — | — | iflas (gün 147) |
| Kuponcu Kemal | — | — | — | — | iflas (gün 120) |
| Rastgele Remzi | iflas (gün 85) | iflas (gün 94) | iflas (gün 105) | iflas (gün 113) | iflas (gün 148) |

Üçlü Ümit 2025'te 1 Haziran'dan başlar (o yıl 10.000 TL ile Haziran'da), altılı kumarbazları yalnız 2026 oynar; "—" oynamadı demektir.

## Yıl bazında TL başına getiri (bahis sayısı)

| Kumarbaz | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|
| Temkinli Tarık | -31.4% (1460) | -35.4% (1404) | -24.7% (1452) | -29.1% (1460) | -32.6% (1304) |
| Cesur Cemal | -49.4% (1460) | -45.7% (1404) | -28.2% (1452) | -42.1% (1460) | -31.4% (1304) |
| Bitik Bilal | -29.5% (2190) | -34.7% (2106) | -28.8% (2178) | -29.0% (2190) | -31.4% (1956) |
| Mantıklı Mehmet | -23.3% (1460) | -25.2% (1404) | -19.5% (1452) | -23.3% (1460) | -25.5% (1304) |
| Değerci Deniz | +4.6% (1036) | -11.8% (842) | +26.4% (835) | +13.4% (851) | +14.3% (722) |
| Stratejik Selin | +4.6% (1036) | -11.8% (842) | +26.4% (835) | +13.4% (851) | +14.3% (722) |
| Plase Pınar | -13.8% (1456) | -15.0% (1398) | -7.3% (1451) | -14.4% (1459) | -6.6% (1299) |
| Dengeli Derya | +4.3% (689) | -7.8% (530) | +32.9% (507) | +41.7% (556) | +18.5% (470) |
| İkili İlhan | -26.4% (1460) | -27.9% (1404) | -13.7% (1452) | -17.7% (1460) | -12.7% (1303) |
| Sıralı Sibel | -31.0% (1460) | -34.0% (1404) | -19.0% (1452) | -18.5% (1460) | -18.1% (1304) |
| Üçlü Ümit | — | — | — | -24.9% (854) | -22.7% (1286) |
| Çifte Çağla | -26.9% (1460) | -26.8% (1404) | -20.5% (1452) | -29.4% (1460) | -33.3% (1304) |
| Altılı Ayşe | — | — | — | — | -33.7% (307) |
| Kuponcu Kemal | — | — | — | — | -46.6% (307) |
| Rastgele Remzi | -45.2% (1460) | -46.0% (1404) | -37.1% (1452) | -44.4% (1460) | -36.8% (1304) |

## Kesintiye göre TL başına getiri (koşunun Σ(1/ganyan) değeri 1.4 altı = ganyan kesintisi yaklaşık %26 ve altı)

| Kumarbaz | Kesinti düşük: getiri (bahis) | Kesinti yüksek: getiri (bahis) |
|---|---:|---:|
| Temkinli Tarık | -24.0% (2325) | -33.8% (4755) |
| Cesur Cemal | -33.3% (1936) | -41.8% (5144) |
| Bitik Bilal | -26.7% (3480) | -32.6% (7140) |
| Mantıklı Mehmet | -21.0% (2378) | -24.5% (4702) |
| Değerci Deniz | +33.4% (1116) | +0.4% (3170) |
| Stratejik Selin | +33.4% (1116) | +0.4% (3170) |
| Plase Pınar | -10.3% (2178) | -12.0% (4885) |
| Dengeli Derya | +36.1% (679) | +11.1% (2073) |
| İkili İlhan | -15.8% (2327) | -21.8% (4752) |
| Sıralı Sibel | -19.0% (2424) | -26.9% (4656) |
| Üçlü Ümit | -16.1% (774) | -27.8% (1366) |
| Çifte Çağla | -26.4% (2358) | -27.7% (4722) |
| Altılı Ayşe | -38.4% (58) | -32.6% (249) |
| Kuponcu Kemal | -33.3% (57) | -49.7% (250) |
| Rastgele Remzi | -41.2% (2213) | -42.3% (4867) |

## Kıyas çıtaları: ganyan (1 TL'lik bahis, bütün koşular)

| Yöntem | İsabet | Bahis başına getiri |
|---|---:|---:|
| Her koşuda rastgele at | 10.5% | -38.9% |
| Her koşuda favori (kapanış oranı) | 34.3% | -31.4% |
| Her koşuda modelin 1. tercihi | 35.2% | -23.7% |

## Bahis türüne göre modelin başarısı (1 birimlik bahis, bu bahsin oynandığı bütün koşular)

Üç oyun aynı koşularda oynanır: **model** (V10'un ilk tercihleri), **favori** (kapanış ganyan oranı en kısa atlar), **rastgele** (bütün kombinasyonların ortalaması, kesin hesap). Getiri = geri dönüş / yatırılan − 1. Parantez içi, modelin kendi ihtimallerinden (Harville) hesaplanan beklenen isabettir; gerçekle yakınsa model dengelidir. Ganyan karşılığı için yukarıdaki kıyas çıtalarına bakın.

| Bahis | Ne tutturulur | Koşu | Model isabet (beklenen) | Model getiri [%95] | Favori isabet | Favori getiri [%95] | Rastgele isabet | Rastgele getiri | Model − favori getiri [%95] |
|---|---|---:|---|---|---:|---|---:|---:|---|
| Plase | At ilk ikiye girer | 16,912 | 52.1% (56.9%) | -12.6% [-14.4%, -10.8%] | 50.9% | -14.6% [-16.4%, -12.8%] | 19.40% | -29.6% | +1.9 puan [+0.3, +3.5] |
| İkili | İlk iki at, sırası önemsiz | 25,701 | 16.6% (19.4%) | -21.9% [-24.4%, -19.4%] | 15.5% | -27.8% [-30.2%, -25.2%] | 2.64% | -40.3% | +5.9 puan [+2.9, +8.8] |
| Sıralı ikili | İlk iki at, sırasıyla | 29,460 | 10.8% (12.5%) | -24.6% [-27.7%, -21.4%] | 10.1% | -30.6% [-33.7%, -27.3%] | 1.70% | -38.2% | +6.1 puan [+2.3, +9.8] |
| Üçlü | İlk üç at, sırasıyla (3 atın 6 sırası oynanır; yalnız 2025-06-01'den sonra) | 4,630 | 12.5% (20.4%) | -31.8% [-38.7%, -24.5%] | 11.1% | -35.5% [-43.0%, -27.7%] | 1.56% | -39.2% | +3.7 puan [-5.4, +12.4] |
| Çifte | Art arda iki koşunun kazananı | 25,290 | 13.1% (12.5%) | -22.5% [-25.8%, -19.1%] | 12.9% | -26.2% [-29.3%, -23.0%] | 1.41% | -44.1% | +3.7 puan [+0.2, +7.0] |

### Altılı: model kuponu ve kalabalık (AGF) kuponu, aynı bütçe (200 TL, en çok 160 kombinasyon)

Altılı, art arda 6 koşunun kazananını bilmektir; kuponda her ayağa birden fazla at yazılır. İki kupon da repodaki dağıtıcıyla (Amaç A: tutma ihtimalini en çoğa çıkar) doldurulur; fark yalnız hangi olasılığı kullandıkları: modelin mi, AGF'nin mi.

| Yıl | Altılı | Model kuponu 6/6 | AGF kuponu 6/6 |
|---|---:|---:|---:|
| 2022 | 917 | 7.0% | 5.7% |
| 2023 | 968 | 7.1% | 6.4% |
| 2024 | 1,054 | 7.1% | 7.1% |
| 2025 | 1,110 | 6.7% | 5.5% |
| 2026 | 1,063 | 6.7% | 6.4% |
| Hepsi | 5,112 | 6.9% | 6.2% |

Fark (model − AGF): +0.68 puan [%95: +0.10, +1.31] (gün-kümeli örnekleme).

2026'da para (1.25 TL birimi varsayımıyla, günün bütün altılıları, her biri için kupon):

| Kupon | Altılı | Maliyet (TL) | Dönüş (TL) | Getiri [%95 aralık] |
|---|---:|---:|---:|---|
| Model | 1,063 | 198,624 | 105,287 | -47.0% [-62.7%, -29.9%] |
| AGF | 1,063 | 198,640 | 83,874 | -57.8% [-69.9%, -44.5%] |

## Veride görünen ganyan kesinti dönemleri (aylık medyan Σ(1/ganyan)'dan: kesinti = 1 − 1/Σ)

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

- Temkinli Tarık: para ağırlıklı getiri -30.6%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 120 TL, modelin beklediği isabet 50.4% (gerçek 49.5%)
- Cesur Cemal: para ağırlıklı getiri -38.3%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 940 TL, modelin beklediği isabet 6.0% (gerçek 5.1%)
- Bitik Bilal: para ağırlıklı getiri -33.5%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 7,200 TL, modelin beklediği isabet 34.6% (gerçek 36.3%)
- Mantıklı Mehmet: para ağırlıklı getiri -23.0%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 248 TL, modelin beklediği isabet 52.7% (gerçek 50.9%)
- Değerci Deniz: para ağırlıklı getiri +9.3%, medyan en kötü düşüş 25%, gerçek yıllarda en büyük tek ödeme 1,390 TL, modelin beklediği isabet 14.9% (gerçek 16.0%)
- Stratejik Selin: para ağırlıklı getiri +11.6%, medyan en kötü düşüş 38%, gerçek yıllarda en büyük tek ödeme 3,539 TL, modelin beklediği isabet 14.9% (gerçek 16.0%)
- Plase Pınar: para ağırlıklı getiri -11.4%, medyan en kötü düşüş 73%, gerçek yıllarda en büyük tek ödeme 2,462 TL, modelin beklediği isabet 69.5% (gerçek 63.6%)
- Dengeli Derya: para ağırlıklı getiri +15.9%, medyan en kötü düşüş 13%, gerçek yıllarda en büyük tek ödeme 2,198 TL, modelin beklediği isabet 29.8% (gerçek 30.1%)
- İkili İlhan: para ağırlıklı getiri -19.9%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 558 TL, modelin beklediği isabet 31.9% (gerçek 27.2%)
- Sıralı Sibel: para ağırlıklı getiri -24.7%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 578 TL, modelin beklediği isabet 23.7% (gerçek 20.1%)
- Üçlü Ümit: para ağırlıklı getiri -24.7%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 2,122 TL, modelin beklediği isabet 28.9% (gerçek 18.2%)
- Çifte Çağla: para ağırlıklı getiri -26.8%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 560 TL, modelin beklediği isabet 19.8% (gerçek 19.9%)
- Altılı Ayşe: para ağırlıklı getiri -33.3%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 2,535 TL, modelin beklediği isabet 9.7% (gerçek 10.7%)
- Kuponcu Kemal: para ağırlıklı getiri -46.0%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 1,673 TL, modelin beklediği isabet 8.4% (gerçek 9.8%)
- Rastgele Remzi: para ağırlıklı getiri -41.7%, medyan en kötü düşüş 100%, gerçek yıllarda en büyük tek ödeme 1,712 TL, modelin beklediği isabet 11.6% (gerçek 11.7%)
