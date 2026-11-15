# Model v5 — Kilitli Test Ön-Kaydı (15.11.2026)

Bu belge 2026 verisi **hiç değerlendirilmeden** yazıldı: `reports/V5_LOCKED.md` yok, 2026 satırları için hiçbir model
tahmini üretilmedi. Belge commit'lendikten SONRA kilitli test (`scripts/run_v5_backtest.py --locked`) TEK SEFER koşulur.
Belge sonradan değiştirilmez; gerekirse sonuna "Sonradan eklenen" başlığıyla not düşülür, mevcut metin silinmez.

## Veri ve kod
- Veritabanı anlık görüntüsü: `data/snapshots/ganyan_20261115_0843.db` (git dışı; 15.11.2026 08:43'te `sqlite3.backup`).
  Dev dönemi ≤ 2025-12-31 (2017–2025, 49.358 değerlendirilebilir koşu); kilitli dönem 2026-01-01 … anlık görüntüdeki son
  koşu (2026-11-12). Değerlendirme süzgeci dev ile aynı: tüm atlarda `agf_close` ve `ganyan` dolu, tek kazananlı, ≥ 4 atlı.
- Kod: `29e8342` (`LOCKED_VARIANTS = ["B0", "B1", "B1_SGR"]`); kilitli koşu bu belgenin commit'inden sonraki HEAD'de,
  `--start-year 2015 --first-test-year 2017 --locked` ile (dev ile aynı özellik tanımı: `build_features` ref_end=2017-01-01)
  yapılır. Eğitim: yıl Y için 2015-01-01 … (Y−1)-12-31 (2026 için 2015–2025).
- Aday: **B1_SGR** = canlıdaki `v1_agf` özellikleri (B1) + hız (S: yenibeygir hız + kendi hız puanımız) + galop (G:
  liderform) + Elo (R) blokları, `HistGradientBoosting`, koşu içi normalize.

## Dev dönemi kanıtı (aday seçimi bu verilerle yapıldı; ayrıntı `reports/V5.md`, `docs/V5_BULGULAR.md`)
- B1_SGR − B1: log-loss −0,0060 (%95 GA −0,0069…−0,0051), 1. tercih isabeti +%0,28 (+0,11…+0,46).
- Yıl yıl ΔLL (B1_SGR − B1): 2017 −0,0048, 2018 −0,0060, 2019 −0,0056, 2020 −0,0034, 2021 −0,0042, 2022 −0,0072,
  2023 −0,0079, 2024 −0,0046, 2025 −0,0090 (9 yılın 9'unda iyileşme).
- B1_SGR − AGF (B0): log-loss −0,0193 (−0,0209…−0,0176), isabet +%0,73 (+0,50…+0,96).

## Birincil hipotez (tek)
**H1:** 2026 kilitli kümede ΔLL = LL(B1_SGR) − LL(B1) < 0 ve koşu-eşli bootstrap %95 GA'nın **üst sınırı < 0**
(betikteki 2000 tekrarlı bootstrap, mevcut tohum). Beklenen etki −0,006…−0,009; ~5,4 bin koşuda standart hata ≈ 0,0013.

## İkincil (açıklayıcı; karar vermez)
ΔLL ve isabet farkı B1 − B0 ve B1_SGR − B0; yıllık tablo tek satır (2026).

## Kararlar
- **H1 sağlanırsa:** B1_SGR, ileri teste ikinci `model_version` olarak alınmaya *aday* olur (İP-8). Ön koşul: canlı hatta
  yenibeygir hız ve liderform galop verisinin koşu öncesi güvenilir üretilmesi (bu kaynaklar TR'de BTK engelli, liderform
  GitHub Actions IP'sinden de 403) — kanıtlanmadan alınmaz.
- **ΔLL noktası < 0 ama GA 0'ı içerirse:** kanıt yetersiz; ileri teste alınmaz, bulgu "kısmen doğrulandı" diye kaydedilir.
- **ΔLL ≥ 0:** dev bulgusu doğrulanmadı; B1 canlıda kalır; neden (veri kayması, 2026 kaynak kapsamı) araştırılır, aynı
  2026 verisine yeni aday denenmez.

## Değer bahsi (açıklayıcı; kâr iddiası için KULLANILMAZ)
1 TL sabit bahis; EV_hat = model olasılığı × `runners.ganyan` (nihai temettü) ≥ 1,2 ve ≥ 1,35; B1 ve B1_SGR için bahis
sayısı, kazanma %, ROI, gün-kümeli bootstrap %95 GA (1000 tekrar). 2026'da ~700–1.500 bahis beklenir → GA yarı genişliği
≈ ±%25–35: test yalnız çok büyük bir kusuru yakalar. Dev dönemi (B1_SGR): EV≥1,2 → ROI +%9,5 (GA +1,4…+18,1; 13.210
bahis); EV≥1,35 → +%10,3 (−1,4…+23,6; 6.152 bahis), ama bu eşikte en büyük 10 kazanç çıkınca +%0,9; ileri-yürüyen eşikle
(yalnız önceki yıllardan seçilen) +%4,1 (−4,0…+13,5); seçim gürültülü oranla yapılırsa (σ=0,2, EV≥1,2, 40 çekiliş
ortalaması) −%3,1. Gerçek getiri canlı ganyan oranının kapanışa yakın ölçülmesine bağlı; bu veri henüz yok.

## Yapılmayacaklar
- Kilitli sonuçtan sonra aday/eşik/özellik değiştirip aynı 2026 verisine tekrar bakmak.
- `--force` ile yeniden koşmak (yalnız betik çökmesi gibi teknik hatada, aynı aday ve kodla).
- 2026'yı eğitime katmak: ancak kilitli rapor yayınlandıktan sonra ve yeni bir kilit dönemi (2027) beklenerek.
