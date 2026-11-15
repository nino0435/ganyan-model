# Model v5 — Kilitli Test Sonucu (2026, 15.11.2026)

Ön-kayıt: `docs/V5_KILITLI_ONKAYIT.md` (commit `2115a1e`, GitHub'a push'landı). Kilitli koşu bu commit'ten SONRA tek sefer:
`scripts/run_v5_backtest.py --db data/snapshots/ganyan_20261115_0843.db --start-year 2015 --first-test-year 2017 --locked`
(eğitim 2015–2025). Ham rapor: `reports/V5_LOCKED.md`. Koşu yeniden yapılmadı, aday/kod değişmedi.

## Birincil hipotez H1: SAĞLANDI
- Değerlendirme kümesi 5.289 koşu (2026-01-01 … 2026-11-10). Anlık görüntüdeki 11-11/11-12 günlerinde AGF/ganyan tam
  olmadığı için süzgeç dışı kaldı (ön-kayıttaki "≈5,4 bin koşu" öngörüsüyle uyumlu; kural değişikliği değil).
- **ΔLL (B1_SGR − B1) = −0,0072 (%95 GA −0,0099…−0,0047); üst sınır < 0.** Beklenen −0,006…−0,009 aralığında.

| Model | Log-loss | 1. tercih | B1'e göre ΔLL | AGF'ye göre ΔLL |
|---|---:|---:|---|---|
| B0 (AGF) | 1,8127 | %34,05 | +0,0154 (+0,0109…+0,0199) | — |
| B1 (canlıdaki) | 1,7973 | %34,75 | — | −0,0154 (−0,0199…−0,0109) |
| B1_SGR | 1,7901 | %34,39 | **−0,0072 (−0,0099…−0,0047)** | −0,0226 (−0,0272…−0,0179) |

- İkincil: canlıdaki B1 de 2026'da AGF'yi geçiyor (ΔLL −0,0154, GA sıfırdan uzak).
- 1. tercih isabeti (açıklayıcı): B1_SGR − B1 = −%0,36 (−0,85…+0,15), B1_SGR − AGF = +%0,34 (−0,32…+1,04): anlamlı değil,
  nokta tahmini dev döneminin (+%0,28) tersi. Kazanan ilk-k içinde (açıklayıcı, ön-kayıt dışı; AGF / B1 / B1_SGR):
  2026 ilk-2 %54,9 / %55,6 / %56,0, ilk-3 %68,0 / %69,2 / %69,6; dev 2017–25 ilk-2 %53,6 / %54,2 / %54,6, ilk-3
  %67,7 / %68,3 / %68,5. Yani kazanç 1. tercihten çok olasılık kalitesinde ve ilk-2/3 kapsamında (B1'e göre ~+%0,2–0,5,
  AGF'ye göre ~+%0,8–1,6); altılı kupon için ilgili olan bu, ama para etkisi ayrıca ölçülmedi.

## Karar (ön-kayıt kuralı)
H1 sağlandı → **B1_SGR, ileri teste ikinci `model_version` olarak alınmaya ADAY.** Ön koşul (kanıtlanmadan alınmaz):
canlı özellik eşdeğerliği. Yollar: (a) yenibeygir hız (Actions'tan erişilebilir, HTTP 200) + liderform galop (Actions'ta Cloudflare 403 → Mac + WARP
gerekir) günlük üretimi, (b) yalnız TJK verisiyle B1_SFA_R (kendi hız puanı + Elo; dev ΔLL −0,0034, 9/9 yıl negatif) — harici
kaynak gerekmez ama tam geçmiş veritabanı canlı hatta taşınmalı. Bu belgeyle ileri teste alınmadı.

## Değer bahsi (açıklayıcı; ön-kayıt gereği kâr iddiası YOK)
1 TL sabit bahis, EV_hat = p_model × nihai ganyan temettüsü; gün-kümeli bootstrap %95 GA.

| Model | EV ≥ 1,2: bahis, ROI (GA) | EV ≥ 1,35: bahis, ROI (GA) |
|---|---|---|
| AGF (B0) | 492, +%10,5 (−23,5…+47,6) | 199, +%32,4 (−13,0…+80,4) |
| B1 | 1.120, +%5,2 (−16,9…+28,9) | 479, +%14,8 (−21,1…+55,6) |
| B1_SGR | 1.305, +%10,4 (−9,3…+33,5) | 572, +%19,7 (−15,2…+56,7) |

Oran gürültüsü (seçim gürültülü oranla, getiri nihai temettüyle; B1_SGR, 40 çekiliş ortalaması; EV ≥ 1,2 / ≥ 1,35):
σ=0,1 → +%12,1 / +%13,0; σ=0,2 → +%4,2 / +%7,3; σ=0,3 → −%4,3 / −%0,8 (çekilişler arası SD ≈ %4–9).

Yorum: işaret ve büyüklük dev dönemiyle (EV ≥ 1,2: +%9,5) tutarlı, ama GA'lar ±%25–35 genişliğinde ve saf AGF'nin
kendisi de artı görünüyor → 2026 yalnız çok büyük bir kusuru elerdi, bir kârı doğrulamaz. Bu rakamlar kapanış (nihai)
temettüye dayanır; bahis anında bilinen canlı oranla gerçekleşecek getiri bu veriyle bilinemez.

## Bundan sonra
- Aynı 2026 verisine yeni aday/eşik/özellik denenmez. 2026 artık sonraki modellerin eğitiminde kullanılabilir; sonraki
  kilit dönemi 2027.
- Sırada: canlı ganyan oranı toplayıcı (kapanışa yakın oran ↔ nihai temettü sapması), canlı özellik eşdeğerliği.
