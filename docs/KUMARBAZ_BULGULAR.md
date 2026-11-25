# Kumarbaz simülasyonu — Bulgular

**Tarih:** 25.11.2026 · **Durum:** Deney. Canlı hatta, modellere ve uygulamaya dokunmaz; karar vermek için değil, fikir toplamak için.

## Neden

İleride uygulamaya "oyun modları" (cesur, temkinli, bitik, mantıklı, stratejik …) konabilir. Önce her oyun tarzının geçmişte gerçek ödemelerle ne kazandırdığı ve neyi tutturduğu görülsün. Tür adlarını ve kuralları Claude belirledi (kullanıcı "isimlere takılma, sen belirle" dedi). Modlar ürün kararı değildir; burada yalnızca simülasyon karakterleri var.

## Ne yapıldı

15 sanal kumarbaz, 2022-01 … 2026-11 (1.770 yarış günü, 31.544 koşu), her gün oynar. Kasa 10.000 TL, bahis 50 TL, kasa 10 TL altına inerse iflas. 7'si yalnız ganyan oynar (ödeme `runners.ganyan`, nihai oran, 1 TL'ye brüt dönüş); 8'i plase, ikili, sıralı ikili, üçlü, çifte ve altılı oynar (ödeme `bets` ve `altili` tablolarındaki gerçek ödemeler). Model türleri V10 `HLB_CAL` yıllık dışarıdan tahminini kullanır (model o yılı hiç görmeden üretir; diğer modeller ayrıca ölçülmedi). Ayrıntılı kartlar ve tüm tablolar: `reports/KUMARBAZ.md`.

| Kumarbaz | Bahis | Kural |
|---|---|---|
| Temkinli Tarık | ganyan | Günün en güçlü 4 favorisine oynar |
| Cesur Cemal | ganyan | Kalabalık sahada oranı 10 ve üstü en kısa oranlı ata oynar |
| Bitik Bilal | ganyan | İlk 6 koşuda favori; kaybedince bahsi ikiye katlar |
| Mantıklı Mehmet | ganyan | Modelin en emin olduğu 4 koşuda modelin 1. tercihi |
| Değerci Deniz | ganyan | Modelin ihtimali AGF payının 1,5 katı ve %8 üstü olan atlar |
| Stratejik Selin | ganyan | Değerci'nin atları, çeyrek Kelly bahis, günlük sınır |
| Plase Pınar | plase | Mehmet gibi: modelin en emin olduğu 4 koşuda 1. tercih, ama plase |
| Dengeli Derya | plase | Değerci'nin atları, ama plase |
| İkili İlhan | ikili | Modelin en emin olduğu 4 koşuda modelin ilk 2 tercihi (sırası önemsiz) |
| Sıralı Sibel | sıralı ikili | Aynı koşularda modelin 1. ve 2. tercihi sırasıyla |
| Üçlü Ümit | üçlü | Modelin ilk 3 tercihinin 6 sırası, 50 TL bölünerek; yalnız Haz 2025'ten sonra |
| Çifte Çağla | çifte | Art arda iki koşunun en emin olunan 4 çiftesinde iki 1. tercih |
| Altılı Ayşe | altılı | Günün altılıları arasında modelin en çok tutturacağına 200 TL'lik kupon; yalnız 2026 |
| Kuponcu Kemal | altılı | Aynı kupon, ama AGF'ye (kalabalığın seçimine) göre; yalnız 2026 |
| Rastgele Remzi | ganyan | Rastgele koşu, rastgele at (kontrol) |

Yeni 8 kumarbazın kuralları ilk çalıştırmadan önce yazıldı, sonuca bakıp değiştirilmedi. Eski 7 kumarbazın sonuçları genişletmeden önce ve sonra birebir aynıdır.

## Bahisler ne?

| Bahis | Ne tutturulur | 1 TL'ye tipik ödeme (medyan; %10–%90) | Nerede oynanır |
|---|---|---|---|
| Ganyan | Birinci gelen at | 3,6 (1,6–12) | Her koşu |
| Plase | At ilk ikiye girsin (sırası önemsiz; iki at da öder, ayrı ayrı) | 2,1 (1,0–7,2) | 7 ve üstü atlı koşuların çoğu |
| İkili | İlk iki at, sırası önemsiz | 13,8 (3,8–66) | 7 ve üstü atlı koşular |
| Sıralı ikili | İlk iki at, sırasıyla | 22,8 (5,6–126) | Hemen her koşu |
| Üçlü bahis | İlk üç at, sırasıyla | ≈124 (25–827), birim 2 TL varsayımıyla | 7–13 atlı koşuların yarısı kadarı |
| Çifte | Art arda iki koşunun kazananı | 20,8 (5–113) | Her ardışık iki koşu |
| Altılı ganyan | Art arda 6 koşunun kazananı. Kuponda her ayağa birden çok at yazılır; maliyet = at sayılarının çarpımı × bilet fiyatı (2026: 1,25 TL) | Bilet başına 25.639 TL (1.895–635.000; en büyüğü 15,6 milyon) | Günde yaklaşık 4 altılı |

Tabela (ilk 4), sıralı 5'li ve plase ikili de var; neredeyse piyango oldukları için eklenmedi.

## Sonuç (300 günlük oyun)

| Kumarbaz | İsabet | TL başına getiri [%95 aralık] | Kasa sonu (medyan) | İflas |
|---|---:|---|---:|---|
| Temkinli Tarık | %49,5 | −%30,5 [−32,2; −28,9] | 0 | %100 (163. gün) |
| Cesur Cemal | %5,1 | −%39,5 [−45,9; −33,1] | 0 | %100 (126. gün) |
| Bitik Bilal | %36,3 | −%30,6 [−32,5; −28,8] | 0 | %100 (10. gün) |
| Mantıklı Mehmet | %50,9 | −%23,3 [−25,1; −21,5] | 0 | %100 (216. gün) |
| Değerci Deniz | %16,0 | **+%9,0 [−0,2; +18,2]** | 13.319 | %0 |
| Stratejik Selin | %16,0 | +%9,0 [−0,2; +18,2] (para ağırlıklı +%11,6) | 14.308 | %0 |
| Plase Pınar | %63,6 | −%11,5 [−13,9; −8,8] | 2.918 | %3 |
| Dengeli Derya | %30,1 | **+%17,2 [+6,9; +27,8]** | 13.595 | %0 |
| İkili İlhan | %27,2 | −%19,8 [−23,0; −16,7] | 0 | %83 (236. gün) |
| Sıralı Sibel | %20,1 | −%24,2 [−27,7; −20,3] | 0 | %95 (192. gün) |
| Üçlü Ümit | %18,2 | −%23,6 [−32,9; −13,6] | 0 | %89 (184. gün) |
| Çifte Çağla | %19,9 | −%27,3 [−30,9; −23,3] | 0 | %99 (183. gün) |
| Altılı Ayşe | %10,7 (6/6 tutan gün) | −%33,7 [−57,7; −4,6] | 0 | %91 (140. gün) |
| Kuponcu Kemal | %9,8 (6/6 tutan gün) | −%46,6 [−66,3; −23,6] | 0 | %100 (112. gün) |
| Rastgele Remzi | %11,7 | −%42,0 [−47,2; −36,0] | 0 | %100 (113. gün) |

Çıta (1 TL'lik ganyan bahsi, bütün koşular): rastgele at −%38,9, favori −%31,4, modelin 1. tercihi −%23,7.

## Model bu bahislerde ne durumda

Aynı koşularda üç oyun: model (V10'un ilk tercihleri), favori (kapanış ganyan oranı en kısa atlar), rastgele (bütün kombinasyonların ortalaması, kesin hesap). 1 birimlik bahis, bu bahsin oynandığı bütün koşular. Parantez içi, modelin kendi ihtimallerinden hesaplanan beklenen isabet.

| Bahis | Koşu | Model isabet (beklenen) | Model getiri | Favori getiri | Rastgele getiri | Model − favori [%95] |
|---|---:|---|---|---|---:|---|
| Ganyan (kıyas) | 31.544 | %35,2 | −%23,7 | −%31,4 | −%38,9 | +7,7 puan |
| Plase | 16.912 | %52,1 (%56,9) | −%12,6 | −%14,6 | −%29,6 | +1,9 [+0,3; +3,5] |
| İkili | 25.701 | %16,6 (%19,4) | −%21,9 | −%27,8 | −%40,3 | +5,9 [+2,9; +8,8] |
| Sıralı ikili | 29.460 | %10,8 (%12,5) | −%24,6 | −%30,6 | −%38,2 | +6,1 [+2,3; +9,8] |
| Üçlü (Haz 2025 sonrası) | 4.630 | %12,5 (%20,4) | −%31,8 | −%35,5 | −%39,2 | +3,7 [−5,4; +12,4] |
| Çifte | 25.290 | %13,1 (%12,5) | −%22,5 | −%26,2 | −%44,1 | +3,7 [+0,2; +7,0] |

Altılı (5.112 altılı, 2022–2026): model kuponu 6/6'yı %6,9, kalabalık (AGF) kuponu %6,2 tutturuyor; fark +0,68 puan [+0,10; +1,31]. Yıllara göre model: %7,0 / %7,1 / %7,1 / %6,7 / %6,7, AGF: %5,7 / %6,4 / %7,1 / %5,5 / %6,4. Para (yalnız 2026, 1.063 altılı, 1,25 TL birim varsayımı): model −%47,0 [−62,7; −29,9], AGF −%57,8 [−69,9; −44,5]. Aynı yönde eski sonuç: `reports/BACKTEST.md` (V1 modeli, +0,68 puan).

## Eski yıllarda sınama (2019–2021)

Soru: Değerci ve Dengeli Derya ipucu başka yıllarda da çıkıyor mu? Kurallar dondurulmuş haliyle (hiçbir eşik değişmedi) 2017–2021'de denendi. Eşikler 2022–2026'da görülmüştü, bu yıllara bakılmamıştı. V10 model tasarımı ise 2017–2021'de seçilmişti (pencere modele hafif lehine), öte yandan model 2019–2021'de daha az eğitim verisiyle çalışıyor (aleyhine). 2017–2018'de ganyan oranlarından çıkan kesinti ≈%50 (kazananın ortalama ödemesi 4,1; 2019'dan beri 5,7 ve üstü), bu yüzden karşılaştırma 2019'dan başlıyor; 2017–2018'de her şey kaybediyor (Değerci −%34,3). Ayrıntı ve yıllara göre tablo: `reports/KUMARBAZ_ESKI_YILLAR.md`.

| Pencere | Favori | Modelin 1. tercihi | Mantıklı Mehmet | Plase Pınar | Değerci Deniz | Dengeli Derya |
|---|---:|---:|---:|---:|---|---|
| 2019–2021 | −%31,6 | −%23,6 | −%23,3 | −%17,8 | +%0,7 [−9,3; +11,7] | +%2,7 [−15,9; +25,9] |
| 2022–2026 | −%31,4 | −%23,7 | −%23,3 | −%11,5 | +%9,0 [−0,2; +18,2] | +%17,2 [+6,9; +27,8] |
| 2019–2026 | −%31,5 | −%23,7 | −%23,3 | −%13,8 | +%5,5 [−1,4; +12,2] | +%11,1 [+0,7; +22,6] |

Okuma: (a) Modelin favoriye üstünlüğü kalıcı: 2017–18'de +7,0, 2019–21'de +8,0, 2022–26'da +7,7 puan. Modeli izleyen Mantıklı Mehmet 2017'den 2026'ya hiçbir yıl kâr etmedi (2019'dan beri her yıl −%19,5 ile −%25,5 arası). (b) Değerci ipucu tekrarlanmadı: 2019–21'de sıfıra yakın, birleşik tahmin +%5,5 ve aralığı sıfırı kapsıyor. Kâr 2024–26'ya yığılmış (Değerci +%26,4 / +%13,4 / +%14,3; öncesinde −%11,8 ile +%4,6 arası). (c) "Düşük kesintide kazandırır" alt grubu da kararsız: Değerci düşük kesintide 2019–21'de +%3,5 (774 bahis), 2022–26'da +%33,4 (1.116 bahis).

## Ne anlıyoruz

1. Klasik türlerin hiçbiri (favori, uzun oran, kayıp kovalama, modelin 1. tercihi) komisyonu yenemiyor: 4–9 ayda iflas, Bitik 10 günde.
2. Model tek başına işe yarıyor ama yetmiyor: modelin 1. tercihi favoriden 7,7 puan, rastgeleden 15,2 puan iyi, yine de −%23,7. Bu üstünlük eski yıllarda da aynı (2019–21'de +8,0 puan), yani kalıcı.
3. Aynı şey diğer bahislerde de geçerli: model her bahiste kalabalıktan (favoriden) iyi, +2 ile +6 puan; plase, ikili, sıralı ikili, çifte ve altılıda aralık sıfırın üstünde, üçlüde örnek az (5,5 ay) ve aralık sıfırı kapsıyor. Ama hiçbir "modeli izle" kumarbazı kesintiyi yenemiyor: Pınar, İlhan, Sibel, Ümit, Çağla ve Ayşe ya iflas ediyor ya eriyor (kalabalığı izleyen Kemal de). En yavaş eriyen Plase Pınar: 300 günde 10.000 TL → medyan 2.918 TL, iflas %3.
4. Kesinti bahis türüne göre farklı. Rastgele kombinasyon oynayanın kaybı: plase −%29,6, sıralı ikili −%38,2, ganyan −%38,9, üçlü −%39,2, ikili −%40,3, çifte −%44,1. Plase en ucuz havuz; havuzu 2024–25'te özellikle cömertti (rastgele oynayanın kaybı −%39'dan −%17'ye indi, 2026'da −%30).
5. Tek gerçek ipucu yine "model ile kalabalığın ayrıldığı atlar": Değerci Deniz (ganyan) +%9,0, aynı atlara plase oynayan Dengeli Derya +%17,2 [+6,9; +27,8], yollarının %90'ı kârda, hiçbirinde iflas yok, yıllara göre +%4,3 / −%7,8 / +%32,9 / +%41,7 / +%18,5. **Bu kanıt değil, ipucu:** (a) eşikler tanı aşamasında aynı veride görüldü ve atlar Değerci'ninkilerle aynı (aynı atlara ganyan +%9,8), yani plase bağımsız bir doğrulama değil; (b) kâr ağır kuyruklu: 2.752 bahsin en büyük 25 ödemesi çıkarılınca getiri −%0,8, ödeme katı 10 ile sınırlanınca +%7,8, 5 ile sınırlanınca −%8,6; (c) 2024–25'teki cömert plase havuzu rakamları şişiriyor; (d) eski yıllarda tekrarlanmadı: 2019–2021'de Değerci +%0,7, Derya +%2,7; 2019–2026 birleşik Değerci +%5,5 [−1,4; +12,2], Derya +%11,1 [+0,7; +22,6] (bir önceki bölüm).
6. Altılıda model kuponu kalabalık kuponundan biraz daha sık 6/6 tutturuyor ve 2026'da daha az kaybediyor, ama ikisi de ağır kayıp: 200 TL'lik kuponla 300 günde Ayşe %91, Kemal %100 iflas ediyor. Altılı, parası büyük ama tutması çok zor bir bahis; "akıllı kupon" iddiası (`reports/BACKTEST.md` NO-GO kararı) bu sonuçla da desteklenmiyor.
7. Modelin kazanma ihtimalleri üst sırada iyi kalibre: çifte için beklenen %12,5, gerçek %13,1. İlk ikiye/üçe girme ihtimalleri ise Harville sıralama formülüyle hesaplandığı için fazla iyimser (üçlüde %20,4 beklenir, %12,5 olur); bu, modelin değil formülün zayıflığı olabilir. 2. ve 3. sıraları iyi tahmin eden ayrı bir sıralama modeli ileride denenebilir.
8. Kesinti belirleyici. Koşunun Σ(1/ganyan) değeri 1,40 altındayken (ganyan kesintisi yaklaşık %26 ve altı) Değerci +%33,4 (1.116 bahis), üstündeyken +%0,4 (3.170 bahis); Dengeli Derya +%36,1 ve +%11,1. Alt grup ayrımı sonradan yapıldı, bu da bir ipucu.
9. Tutturdukları: Değerci favori değil, medyan 5,9 kat oranlı atları tutturuyor (100 bahsin 16'sı). Temkinli neredeyse her ikinci bahsi tutturuyor ama 1,4 kat ödeme alıyor.

## Uyarılar

- **Kapanış oranı ve AGF:** Kumarbaz kapanışta oynayan, kapanış AGF'sini ve oranını gören kişi gibi modellenir. Canlıda erken alınan AGF daha az bilgi taşır (`reports/V10.md` Uyarı 1); bahsin oranı etkilemediği de varsayıldı. Canlı sonuç daha kötü beklenmeli.
- **Seçimde nihai oran sızıntısı:** Seçimi p × nihai oran ≥ 1,10 ile yapınca bahis başına getiri +%19 çıkıyor. Bu, bahis anında bilinmeyen bilgiyi kullanmak, yani yapay. Model türleri bu yüzden seçimde oranı değil AGF'yi kullanır; ödeme nihai orandan.
- **Kesinti dönemleri veriden çıkarım:** Aylık medyan Σ(1/ganyan)'dan kesinti yaklaşık %26 ile %55 arasında oynuyor (tablo `reports/KUMARBAZ.md` içinde). 2023 Temmuz–Eylül'deki %55 bütün hipodromlarda aynı anda görünüyor, nedeni bilinmiyor. 2024 Kasım tutarsız (eş oranlı atlar Σ'yı şişirir).
- **2017–2018 farklı bir dünya:** Ganyan oranlarından çıkan kesinti ≈%50, kazananın ortalama ödemesi 4,1 (2019'dan beri 5,7 ve üstü). `bets` ve `runners.ganyan` tutarlı, en küçük ödeme her yıl 1,05; nedeni bilinmiyor. Para karşılaştırmaları için pencere 2019'dan başlamalı.
- **Yol örneklemesi:** "Kârda bitenler" ve "iflas" yüzdeleri günlerin rastgele karışımıdır; bahis başına getirinin belirsizliğini yansıtmaz, o %95 aralık sütununda.
- **Ödeme birimleri:** Plase, ikili, sıralı ikili ve çifte ödemeleri 1 TL'ye göredir: aralarındaki oranlar (ör. ikili/sıralı ikili ≈ 0,54, sıralı ikili/ganyan ≈ 5–6) yıllarca sabit. **Üçlüde ve altılıda ödeme "birim bilet" başınadır ve birim büyüdü.** Üçlü: aynı koşudaki sıralı ikili ödemesine oranı 2022'de ≈ 0,9, 2025 Mayıs'ta ≈ 5, Haziran 2025'te ≈ 10 (iki kat sıçrama); birim 2 TL alındı ve rastgele oynayanın kaybı −%39 çıktı (öbür bahislerle uyumlu; birim 1 TL olsaydı rastgele oynayan kâr ederdi, mümkün değil). Birim resmi değil, çıkarım; üçlü yalnız Haziran 2025'ten sonra oynatıldı. Altılı: birim 1,25 TL yalnız 2026 için ve tek haber kaynağına dayanıyor (`ganyan/backtest.py` varsayımı); medyan ikramiye 2022'de 2.011 TL, 2026'da 25.639 TL (13 kat), birim büyüdüğü için yıllar karşılaştırılamıyor; bu yüzden altılı parası yalnız 2026, önceki yıllar için yalnız 6/6 isabeti verilebildi.
- **Plase kuralı veriden:** Bu veride plase hemen her zaman ilk iki at (ikisi de öder, %99,5). `bets` tablosunda "PLASE" adıyla çok ayaklı 7'li plase satırları da var; elendi. İkili kombinasyonları küçükten büyüğe, sıralı ikili ve üçlü bitiş sırasıyla kayıtlı (%98,8 / %98,6 / %98,3 doğrulandı).
- **"Oynanan koşu" = ödeme satırı var:** Plase, ikili, üçlü ve çifte için bahsin o koşuda oynanıp oynanmadığı ödeme satırının varlığından çıkarıldı (program bilgisi veri tabanında yok). Program numarası eksik olan koşular (2022'de %4, Kasım 2024'ten beri hiç) diğer bahislerde atlandı.
- **Harville:** Beklenen isabetler (parantez içleri) ve "en emin olunan koşu" sıralaması Harville formülüyle hesaplandı; yukarıda yazıldığı gibi ikinci/üçüncü sıra ihtimallerini fazla iyimser veriyor.

## Yeniden üret

```bash
venv/bin/python scripts/run_kumarbaz_sim.py
venv/bin/python scripts/run_kumarbaz_eski_yillar.py
```

Birincisi yaklaşık 30 sn sürer ve `reports/KUMARBAZ.md` dosyasını yazar; ikincisi yaklaşık 15 sn sürer ve `reports/KUMARBAZ_ESKI_YILLAR.md` dosyasını yazar. Girdi git dışıdır: `data/ganyan.db` ve her yıl için tam bir `data/v10_cache/pred_V10_HLB_CAL_*_<yıl>.pkl` (ikincisi 2017–2026'nın hepsini ister). Testler: `tests/test_kumarbaz_sim.py` ve `tests/test_kumarbaz_eski_yillar.py` (sentetik veri, DB gerekmez).

## Kapsam dışı ve sonra

- **Tabela, sıralı 5'li, plase ikili, 5'li ganyan yok.** Ödemeleri `bets` ve `pools` tablolarında var; çok nadir tuttuklarından eklenmedi.
- **Altılıda 2022–2025 parası yok** (birim bilinmiyor). Birimi öğrenmenin yolu TJK/United Racing'in resmi bilet fiyatı geçmişi.
- **Değerci ve Dengeli Derya için gerçek kanıt** önceden yazılmış bir protokol ve canlı, erken AGF ile ileri test ister; bu simülasyon ve eski yıllarda sınama onun yerine geçmez. Süre uzun: ganyan Değerci yılda ≈900 bahis çıkarıyor (bahis başına getirinin standart sapması ≈3 kat); gerçek etki +%9 ise %95 güvenle ayırt etmek için ≈4.200 bahis (≈5 yıl), +%5 ise ≈13.600 bahis (≈15 yıl) gerekir.
- **Daha iyi sıralama modeli:** ikili, üçlü ve plase için 2. ve 3. sıra ihtimallerini ayrı öğrenen bir model, Harville'in iyimserliğini giderirdi.
