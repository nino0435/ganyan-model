# Model v5 — Dev Dönemi Bulguları (2017–2025, 15.11.2026)

Ham tablolar: `reports/V5.md`. Kilitli 2026 testi bu belgeden SONRA, `docs/V5_KILITLI_ONKAYIT.md` kurallarıyla tek sefer.

## 1. Ölçüm düzeneği
- Anlık görüntü `data/snapshots/ganyan_20261115_0843.db`; 49.358 koşu (2017-01-01…2025-12-31), 484.365 at satırı.
- İleri-yürüyen: test yılı Y için eğitim 2015…Y−1 (yalnız `agf_close`'u dolu satırlar); AGF 2015'ten itibaren var.
- B0 = kapanış AGF'nin kendisi; B1 = canlıdaki `v1_agf` özellikleri; B1_S/G/R/SGR = B1 + hız (S), galop (G), Elo (R)
  blokları. Hız: yenibeygir hız puanları + kendi gün-düzeltmeli puanımız (`sfa_*`); galop: liderform; Elo: gün-dondurulmuş.
- Güven aralıkları koşu-eşli bootstrap (2000 tekrar); değer bahsinde gün-kümeli bootstrap (1000 tekrar).

## 2. Olasılık kalitesi (log-loss; düşük iyi)
| Model | Log-loss | 1. tercih | B1'e göre ΔLL (%95 GA) |
|---|---:|---:|---|
| B0 (AGF) | 1,8240 | %33,44 | +0,0133 |
| B1 | 1,8107 | %33,89 | — |
| B1_G | 1,8099 | %33,84 | −0,0008 (−0,0015…−0,0002) |
| B1_R | 1,8097 | %33,87 | −0,0010 (−0,0016…−0,0003) |
| B1_SFA (yalnız kendi hız puanı; TJK verisi) | 1,8083 | %34,01 | −0,0025 (−0,0031…−0,0018) |
| B1_SFA_R (kendi hız + Elo; yalnız TJK verisi) | 1,8073 | %34,06 | −0,0034 (−0,0042…−0,0026) |
| B1_YB (yalnız yenibeygir hız) | 1,8070 | %34,06 | −0,0037 (−0,0045…−0,0030) |
| B1_S (yenibeygir + kendi hız) | 1,8062 | %34,03 | −0,0045 (−0,0053…−0,0037) |
| B1_SFA_GR (yenibeygirsiz) | 1,8065 | %33,96 | −0,0042 (−0,0051…−0,0034) |
| **B1_SGR** | **1,8047** | **%34,17** | **−0,0060 (−0,0069…−0,0051)** |

- B1_SGR − AGF: ΔLL −0,0193 (−0,0209…−0,0176), isabet +%0,73 (+0,50…+0,96).
- B1_SGR − B1 yıl yıl: 2017 −0,0048, 2018 −0,0060, 2019 −0,0056, 2020 −0,0034, 2021 −0,0042, 2022 −0,0072,
  2023 −0,0079, 2024 −0,0046, 2025 −0,0090 → 9/9 yılda iyileşme; son yıllarda artıyor.
- Bloklar uzun geçmişte (eğitim 2015'ten) yaklaşık toplanıyor: S −0,0045, G −0,0008, R −0,0010, hepsi −0,0060.
  Aynı test yılları (2024–25) için eğitim 2022'den başlayınca SGR −0,0029 (S −0,0016, G 0,0000, R +0,0003), 2015'ten
  başlayınca ≈ −0,0068 (2024 −0,0046, 2025 −0,0090): bloklar çok yıllık eğitim ister.
- Tek başına en güçlü kaynak yenibeygir hızı (−0,0037); kendi hız puanımız (`sfa_*`) onun üstüne −0,0008 ekliyor
  (B1_S − B1_YB); yenibeygirsiz kurulum (sfa + G + R) kazancın ≈ %70'ini koruyor (−0,0042 / −0,0060).
- Canlı kurulum uyarısı: yenibeygir TR'de engelli ama GitHub Actions IP'sinden erişilebiliyor (14.11 yoklaması HTTP 200);
  liderform hem TR'de hem Actions'ta Cloudflare 403. Yani Actions'ta kurulabilecek varyantlar yenibeygir hız içerenler
  (B1_YB/B1_S, + Elo); B1_SGR'nin galop bloğu Mac + WARP gerektirir. Veri koşu öncesi günlük üretilebilmeli. Yalnız TJK verisiyle (kendi hız puanı + Elo; B1_SFA_R) kurulum uzun eğitimle −0,0034
  (−0,0042…−0,0026): B1_SGR kazancının ≈ %57'si ve harici kaynak gerektirmiyor (9 yılın 9'unda negatif, 6'sında tek
  başına anlamlı; 2023–25'te −0,0046…−0,0058). Kısa eğitimli (2022+) ablasyonda ≈ 0 çıkmıştı (−0,0005): uzun geçmiş
  şart; canlı hatta (Actions) kurmak için tam geçmiş veritabanı (2005→) durum olarak taşınmalı.

## 3. Değer bahsi (1 TL, EV_hat = p_model × nihai ganyan temettüsü)
Seçim NİHAİ temettüyle yapılır (kapanış çizgisi); bahis anında yalnız canlı oran bilinir (bkz. §4).

| B1_SGR | Bahis | ROI | %95 GA |
|---|---:|---:|---|
| EV ≥ 1,2 | 13.210 | +%9,5 | +1,4…+18,1 |
| EV ≥ 1,35 | 6.152 | +%10,3 | −1,4…+23,6 |
| EV ≥ 1,5 | 2.955 | +%25,1 | +6,6…+45,3 |

- Karşılaştırma (EV ≥ 1,2 / ≥ 1,35): saf AGF −%6,2 (−16,4…+5,1; 5.788 bahis) / +%19,1 (−3,1…+45,9; 2.120 bahis);
  B1 +%0,4 / +%6,8; B1_YB +%7,2 / +%19,2; B1_S +%1,8 / +%10,3; B1_SGR +%9,5 / +%10,3. EV ≥ 1,2'de ROI model
  kalitesiyle artıyor (−6,2 → +0,4 → +9,5), EV ≥ 1,35'te düzenli DEĞİL (saf AGF bile +%19): alt kümelerde güven
  aralıkları ±%20–25 genişliğinde, varyantlar arası ROI farkları gürültü düzeyinde.
- Yıl yıl (B1_SGR, EV ≥ 1,2): 2017 +49,7; 2018 −6,3; 2019 −4,8; 2020 +13,6; 2021 +0,7; 2022 +12,3; 2023 −8,2; 2024 +27,5;
  2025 +3,7 (%) → 9 yılın 6'sı artı.
- Kırılgan: EV ≥ 1,35'te en büyük 10 kazanç (39…102 TL) çıkınca +%0,9 (−9,6…+11,3); temettü tavanı 30 → +%3,8.
  Temettü aralığına göre (EV ≥ 1,2) sinyal 10–20 aralığında: +%20,1 (+9,4…+31,2; 5.206 bahis); 5–10: +%1,5; 20–50: +%4,2.
- İleri-yürüyen eşik (yalnız önceki yıllardan seçilen): +%4,1 (−4,0…+13,5; 10.716 bahis); 2019–2020'de uygun eşik yok.
- Oran gürültüsü (seçim gürültülü oranla, getiri nihai temettüyle; 40 çekiliş ortalaması):

| σ (log) | EV≥1,2 ROI | EV≥1,35 ROI |
|---:|---:|---:|
| 0 | +%9,5 | +%10,3 |
| 0,05 | +%7,6 | +%11,9 |
| 0,10 | +%4,7 | +%10,2 |
| 0,15 | +%0,6 | +%6,3 |
| 0,20 | −%3,1 | +%2,0 |
| 0,30 | −%10,6 | −%6,6 |

  Gürültü bağımsız varsayıldı; geç para modelin sevdiği atlara akıyorsa gerçek sonuç daha kötü olur.
- Temettü AGF'den tahmin edilirse (log-temettü ~ log(1/agf_pay), yalnız önceki yıllardan; kalıntı SD 0,39–0,46):
  EV_est ≥ 1,2 → 7 yılda yalnız 92 bahis (ROI −%3,8, GA −56…+60); ≥ 1,35 → 21 bahis. Canlı ganyan oranı olmadan
  strateji fiilen kurulamıyor.

## 4. Canlı ganyan oranı (15.11.2026 yoklaması)
- TJK program sayfası her at için canlı `Gny` içerir: `https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukYarisProgrami?`
  `SehirId=<id>&QueryParameter_Tarih=dd%2Fmm%2Fyyyy&SehirAdi=<ad>&Era=today` + `X-Requested-With: XMLHttpRequest`
  (SehirId gün sayfasından: `<a id="İstanbul" data-sehir-id="3" …>`). Hücre `<td class="gunluk-GunlukYarisProgrami-Gny">
  <span>999.99</span>`: 999.99 = henüz havuz yok.
- `scripts/snapshot_agf.py::parse_live_program_html` bu işaretlemede 0 satır döndürür (koşu başlığı `1. Koşu 14.00`,
  değer `<span>` içinde) ve çağrıldığı yedek yol zaten hiç çalışmıyor → `agf_snapshots.ganyan_live` hep NULL.
- İleri-test çalışma sıklığı seyrek (09–13 saatlik, 14:30/16:30/18:30/20:30): kapanışa yakın oran için yetmez.

## 5. İleri test uyarısı: tahmin anındaki AGF, kapanış AGF'si değil (15.11.2026)
- İleri test (`origin/actions-state:FORWARD.md`, 28.10–14.11, 264 sonuçlanmış koşu): model `v1_agf` canlı AGF favorisinin
  gerisinde — 1. tercih −%1,5, log-loss +0,0032 (GA −0,0148…+0,0219). Tahmin, AGF'nin ilk göründüğü anda (sabah saatlik
  çalışma) bir kez yazılıyor; kıyas da o andaki AGF ile.
- Altılı havuzu ilk ayağın start saatinde kapanır; AGF o ana dek oluşur. Ölçüm (`agf_snapshots`, 195 koşu, ≥ 2 koşu-öncesi
  snapshot): ilk koşu-öncesi snapshot'ın (ort. 344 dk kala) AGF log-loss'u 1,9444, son koşu-öncesi snapshot'ınki (medyan 60 dk
  kala) 1,8334 — fark +0,1111 (SE 0,0272). Backtest'te B1'in kapanış AGF'ye göre kazancı 0,013–0,023; yani AGF'nin
  yaşı model avantajından ~5–8 kat büyük.
- Sonuç: backtest kazancı (kapanış AGF) ile ileri test (erken AGF) aynı şeyi ölçmüyor; ileri testin "model ≈ AGF" sonucu
  kapanış-AGF kazancını çürütmez ve doğrulamaz. Canlıda kazanç ancak AGF kapanışa yakınken (ilk ayak start'ından sonra
  2–6. ayaklar için, 1. ayak için start'tan hemen önce) tahmin üretilirse beklenir.
- Öneri: ileri testte tahmini ilk ayak start'ından sonra da yaz/değerlendir (AGF yaşına göre ayrı satır); canlı oran
  toplayıcısı (`ganyan/live_odds.py`) AGF'yi de zaman serisi olarak saklar.

## 6. Sıradaki adımlar
1. Kilitli 2026 testi (ön-kayıt kurallarıyla, tek sefer).
2. Canlı ganyan oranı toplayıcı (ileri testten bağımsız) → kapanışa 10/5/2 dk kala oran ile nihai temettü sapması ölçülür;
   değer bahsi ancak bu ölçümle sınanabilir.
3. B1_SGR'nin canlı özellik eşdeğerliği (yenibeygir + liderform verisinin günlük üretimi) ve ikinci `model_version`.
