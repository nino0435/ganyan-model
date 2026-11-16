# Model v6 — Deney Bulguları, Doğrulama Kapısı ve Değer Bahsi Analizi (16.11.2026)

Ham rapor: `reports/V6.md`. Koşu günlüğü: `data/v6_run.log`. Sabitlenen yapılandırma: `ganyan/model_v6.py` (`V6_CONFIG`).

## 1. Sonuç Özeti

**Evet, sabit doğrulama kapısını geçen bir V6 adayı bulundu (`E5_best_temp`, `ganyan/model_v6.py` içinde `V6_CONFIG` olarak sabitlendi); ancak kazanç mütevazıdır ve yeni bir veri ya da özellik kaynağından değil, mevcut 68 özellikli `B1_SGR` kümesi üzerinde daha ağır HGB yaprak düzenlileştirmesi (`E2_07`), 5 tohum ortalaması (`E3`) ve ileri-yürüyen sıcaklık kalibrasyonundan (`E5_best_temp`) gelmektedir.** Salt-okunur `data/snapshots/ganyan_20261116.db` (`2005-01-01`…`2026-11-14`, `111.000` sonuçlanmış koşu, `1.137.508` koşucu; `data/v6_run.log` çalışma aralığı `16:23:55–16:47:01`, `142` `(varyant, yıl)` değerlendirmesi) üzerinde `E0 (B1_SGR)` tabanına karşı sınanan **23 V6 aday yapılandırması** içinden Aşama A seçim kümesinde (`2017–2021`, `24.843` koşu) ilk iki sırayı `E3` (`LL = 1,8364`, `ΔLL = −0,0044`, `%95 GA −0,0057…−0,0031`, `5/5` negatif yıl) ve `E5_best_temp` (`LL = 1,8364`, `ΔLL = −0,0043`, `%95 GA −0,0057…−0,0030`, `5/5` negatif yıl) almış; Aşama B doğrulama kümesinde (`2022–2025`, `24.515` koşu) `E5_best_temp`, `LL = 1,7644` ile `E0` tabanını (`LL = 1,7672`) **`ΔLL = −0,0027` (`%95 GA −0,0037…−0,0018`, `4/4` negatif yıl)** ve saf kapanış AGF'sini (`B0`, `LL = 1,7898`) **`ΔLL = −0,0254` (`%95 GA −0,0277…−0,0232`)** geçerek sabit kapıyı aşmıştır (`E3` tek başına `LL = 1,7649`, `ΔLL = −0,0023`, `%95 GA −0,0032…−0,0014`, `4/4` yıl); kilidi v5'te tüketilmiş bilgi amaçlı `2026` kümesinde de (`5.362` koşu, temiz test değil) aynı fark korunmuştur (`E5_best_temp` `LL = 1,7856` vs `E0` `1,7883`, `ΔLL = −0,0027`, `%95 GA −0,0045…−0,0008`; `E3` `LL = 1,7852`, `ΔLL = −0,0031`, `%95 GA −0,0047…−0,0014`).

---

## 2. Tablolar (Veri Kapsamı, Seçim, Doğrulama ve 2026-Bilgi)

### 2.1 Veri Özeti ve Yıllık Kaynak Doluluk Oranları (`2005–2026`)

- **Veritabanı:** `data/snapshots/ganyan_20261116.db` (`2005-01-01` … `2026-11-14`, `111.000` sonuçlanmış koşu, `1.137.508` koşucu).
- **Değerlendirme kümeleri (tüm atlarda `agf_close` ve `ganyan` dolu, tek kazananlı, ≥4 atlı):** Aşama A (`2017–2021`) `24.843` koşu | Aşama B (`2022–2025`) `24.515` koşu | Aşama C (`2026` bilgi) `5.362` koşu.
- **Çalışma süresi (`data/v6_run.log`):** `16:23:55` – `16:47:01` (~23 dk 6 sn), toplam `142` `(varyant, yıl)` birimi (`E0` `2016–2026`: `0,9–11,6 sn`/yıl; `E2` ızgarası: `2,5–19,1 sn`/yıl; `E4` blokları: `1,3–6,3 sn`/yıl; `E1b` uzun eğitim: `15,8–23,4 sn`/yıl; 5-tohumlu `E3`: `2017`'de `16,7 sn` → `2026`'da `78,9 sn`/yıl; `E5` kalibrasyonları: `0,0–0,2 sn`/yıl).
- **AGF'siz yıllar (`2005–2014`) ve galop başlangıcı:** `agf_close` `2005–2014` döneminde `%0,0` doludur; bu yıllar eğitime eklendiğinde (`E1b`) B1 tipi AGF özellikleri (`agf_share`, `log_agf`) `NaN` kalır ve HGB tarafından doğal `NaN` dallanmasıyla işlenir. `liderform` galop verisi `2015-10`'da anlamlı hacme ulaştığından `2005–2014`'te galop sayacı özellikleri (`g_n14`, `g_n30`) `0`, süre özellikleri (`g_days_last`, `g_last_d400` vb.) `NaN` olur.

| Yıl | Koşu | Koşucu | AGF % | `time_s` % | Kendi Hız (`sfa`) % | YB Hız Kaynak / Öz. % | Galop Kayıt (Öz. %) | Elo≠0 % | `fark` % | `gec_cikis` % | `son800` % | `prize_1` % | `pools` Gün | `steward` Satır |
|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2005 | 3.165 | 35.287 | 0,0% | 98,9% | 87,7% | 0,0% / 0,0% | 25 (0,0%) | 88,5% | 17,0% | 0,0% | 44,1% | 100,0% | 0 | 0 |
| 2006 | 3.237 | 36.706 | 0,0% | 99,1% | 94,2% | 0,0% / 0,0% | 27 (0,0%) | 95,2% | 26,3% | 0,0% | 99,5% | 100,0% | 0 | 0 |
| 2007 | 3.526 | 37.773 | 0,0% | 99,0% | 92,7% | 0,0% / 0,0% | 37 (0,0%) | 94,7% | 28,0% | 0,2% | 99,7% | 100,0% | 0 | 0 |
| 2008 | 4.145 | 41.821 | 0,0% | 99,0% | 92,4% | 0,0% / 0,0% | 34 (0,0%) | 95,1% | 29,8% | 2,3% | 98,2% | 100,0% | 0 | 0 |
| 2009 | 4.142 | 43.965 | 0,0% | 99,0% | 87,5% | 0,0% / 0,0% | 40 (0,0%) | 95,6% | 28,1% | 3,0% | 99,3% | 100,0% | 0 | 0 |
| 2010 | 3.919 | 42.254 | 0,0% | 99,0% | 93,4% | 98,4% / 87,8% | 41 (0,0%) | 95,5% | 27,9% | 3,7% | 99,1% | 100,0% | 0 | 0 |
| 2011 | 4.272 | 44.113 | 0,0% | 99,0% | 94,3% | 98,0% / 93,6% | 27 (0,0%) | 95,2% | 29,1% | 2,6% | 99,1% | 100,0% | 0 | 0 |
| 2012 | 4.390 | 45.658 | 0,0% | 98,8% | 91,8% | 97,6% / 93,3% | 29 (0,0%) | 95,2% | 28,9% | 2,1% | 98,8% | 100,0% | 0 | 0 |
| 2013 | 4.718 | 48.947 | 0,0% | 98,8% | 94,3% | 97,7% / 93,5% | 79 (0,0%) | 95,4% | 28,9% | 7,8% | 99,3% | 100,0% | 0 | 0 |
| 2014 | 5.483 | 53.208 | 0,0% | 98,7% | 94,5% | 97,3% / 93,2% | 648 (0,8%) | 95,4% | 30,9% | 8,8% | 99,7% | 100,0% | 0 | 0 |
| 2015 | 5.426 | 55.121 | 81,3% | 98,8% | 94,3% | 97,4% / 93,1% | 56.697 (45,9%) | 95,2% | 29,5% | 8,2% | 99,5% | 100,0% | 0 | 0 |
| 2016 | 5.386 | 53.709 | 91,8% | 98,7% | 94,3% | 97,4% / 93,1% | 126.427 (96,9%) | 95,3% | 30,1% | 9,6% | 99,7% | 100,0% | 242 | 0 |
| 2017 | 5.463 | 53.513 | 91,3% | 98,7% | 94,1% | 97,6% / 93,0% | 129.098 (96,8%) | 95,0% | 30,7% | 9,2% | 99,1% | 100,0% | 363 | 0 |
| 2018 | 5.613 | 55.173 | 91,0% | 98,6% | 94,0% | 97,6% / 93,1% | 131.793 (95,2%) | 95,0% | 30,5% | 9,6% | 98,8% | 100,0% | 364 | 0 |
| 2019 | 5.579 | 55.137 | 91,1% | 98,7% | 94,0% | 97,8% / 93,1% | 115.188 (83,5%) | 94,9% | 33,9% | 9,7% | 99,5% | 100,0% | 364 | 0 |
| 2020 | 5.098 | 50.245 | 94,2% | 98,8% | 93,4% | 98,0% / 92,8% | 111.420 (82,5%) | 94,4% | 39,9% | 10,9% | 99,6% | 100,0% | 284 | 0 |
| 2021 | 6.011 | 60.593 | 92,2% | 98,6% | 94,3% | 98,0% / 93,8% | 117.386 (78,0%) | 95,2% | 39,6% | 10,7% | 99,5% | 100,0% | 365 | 0 |
| 2022 | 6.490 | 61.725 | 94,2% | 98,6% | 93,9% | 98,2% / 93,6% | 133.856 (93,1%) | 95,0% | 41,9% | 11,2% | 99,5% | 100,0% | 365 | 0 |
| 2023 | 6.402 | 59.935 | 95,2% | 98,8% | 94,1% | 98,5% / 93,8% | 131.180 (93,0%) | 94,9% | 42,6% | 10,7% | 99,5% | 100,0% | 351 | 0 |
| 2024 | 6.580 | 59.548 | 96,2% | 98,8% | 94,1% | 98,7% / 94,0% | 135.876 (93,4%) | 94,9% | 36,1% | 8,5% | 81,4% | 81,9% | 298 | 0 |
| 2025 | 6.491 | 62.547 | 97,7% | 98,9% | 93,8% | 98,9% / 93,9% | 150.504 (95,3%) | 94,6% | 0,0% | 0,0% | 0,0% | 0,0% | 0 | 0 |
| 2026 | 5.464 | 54.548 | 98,9% | 98,8% | 93,3% | 98,2% / 93,6% | 123.112 (95,5%) | 94,4% | 0,0% | 0,0% | 0,0% | 0,0% | 0 | 0 |

### 2.2 Aşama A — Seçim Kümesi Sonuçları (`2017–2021`, `24.843` Koşu)

Sıralama ölçütü: ortalama `ΔLL(varyant − E0)`. Yalnız en iyi 2 V6 adayı (`E3` ve `E5_best_temp`) `+ E0` Aşama B'ye geçmiştir (`Ref_2015_Gecmis` yalnız bilgi amaçlı geçmiş-kesme kontrolüdür, aday seçimine girmez).

| Sıra | Varyant | Aile | Yapılandırma Özeti | Log-Loss | ΔLL vs E0 (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 | Durum |
|---:|---|---|---|---:|---|---:|---:|---:|---:|---|
| — | `B0` | Piyasa | Saf kapanış AGF'si | 1,8578 | `+0,0170` (`+0,0145`…`+0,0196`) | 0/5 | 32,61% | 52,27% | 66,36% | Referans |
| 0 | `E0` | E0 | Taban `B1_SGR` (`2006-03-04→` öz., `2015→` eğ., `300/0.04/31/60/1.0/auto`, tohum `0`) | 1,8408 | — | 0/5 | 33,21% | 53,14% | 67,02% | Taban |
| 1 | `E3` | E3 | `E2_07` üzerinde 5 tohum (`0..4`) olasılık ort. + koşu içi normalize | 1,8364 | **`-0,0044`** (`-0,0057`…`-0,0031`) | 5/5 | 33,30% | 53,36% | 67,21% | **Aşama B'ye Geçti** |
| 2 | `E5_best_temp` | E5 | `E3` üzerinde ileri-yürüyen sıcaklık kalibrasyonu (`< Y` yılları) | 1,8364 | **`-0,0043`** (`-0,0057`…`-0,0030`) | 5/5 | 33,30% | 53,36% | 67,21% | **Aşama B'ye Geçti** |
| 3 | `E2_07` | E2 | HGB `420/0.03/23/400/15.0/es=False` | 1,8365 | `-0,0043` (`-0,0056`…`-0,0029`) | 5/5 | 33,28% | 53,25% | 67,15% | Elendi |
| 4 | `E2_03` | E2 | HGB `450/0.03/15/150/5.0/es=False` | 1,8369 | `-0,0039` (`-0,0051`…`-0,0027`) | 5/5 | 33,29% | 53,07% | 67,32% | Elendi |
| 5 | `E2_10` | E2 | HGB `550/0.03/23/180/6.0/tv=0.15` (zamansal erken durdurma) | 1,8370 | `-0,0038` (`-0,0052`…`-0,0025`) | 5/5 | 33,07% | 53,24% | 67,13% | Elendi |
| 6 | `E2_04` | E2 | HGB `550/0.025/10/200/5.0/es=False` | 1,8370 | `-0,0038` (`-0,0050`…`-0,0025`) | 5/5 | 33,27% | 53,23% | 67,31% | Elendi |
| 7 | `E2_06` | E2 | HGB `380/0.03/31/250/10.0/es=False` | 1,8374 | `-0,0034` (`-0,0048`…`-0,0019`) | 5/5 | 33,07% | 53,35% | 67,15% | Elendi |
| 8 | `E5_best_iso` | E5 | `E3` üzerinde ileri-yürüyen izotonik kalibrasyon | 1,8377 | `-0,0031` (`-0,0046`…`-0,0016`) | 5/5 | 33,06% | 53,20% | 67,16% | Elendi |
| 9 | `E2_05` | E2 | HGB `400/0.03/23/120/3.0/es=False` | 1,8379 | `-0,0029` (`-0,0042`…`-0,0017`) | 5/5 | 33,14% | 53,14% | 67,19% | Elendi |
| 10 | `E2_08` | E2 | HGB `420/0.025/47/200/8.0/auto` | 1,8392 | `-0,0016` (`-0,0027`…`-0,0005`) | 5/5 | 33,18% | 53,20% | 67,22% | Elendi |
| 11 | `E2_02` | E2 | HGB `700/0.02/31/150/5.0/auto` | 1,8395 | `-0,0013` (`-0,0022`…`-0,0004`) | 5/5 | 33,13% | 53,28% | 67,02% | Elendi |
| 12 | `E2_09` | E2 | HGB `360/0.025/63/300/10.0/auto` | 1,8395 | `-0,0013` (`-0,0025`…`+0,0000`) | 5/5 | 33,06% | 53,17% | 67,09% | Elendi |
| 13 | `E2_01` | E2 | HGB `550/0.025/31/100/3.0/auto` | 1,8400 | `-0,0008` (`-0,0016`…`+0,0001`) | 4/5 | 33,26% | 53,17% | 67,11% | Elendi |
| 14 | `E4_s800` | E4 | `E0` + `X_S800` (`race_extra` son 800m hız/tempo `< D`) | 1,8403 | `-0,0005` (`-0,0015`…`+0,0005`) | 3/5 | 33,01% | 53,01% | 67,12% | Elendi |
| 15 | `E5_temp` | E5 | `E0` üzerinde ileri-yürüyen sıcaklık kalibrasyonu | 1,8406 | `-0,0002` (`-0,0005`…`+0,0001`) | 3/5 | 33,21% | 53,14% | 67,02% | Elendi |
| 16 | `E4_prize` | E4 | `E0` + `X_PRIZE` (enflasyon-düzeltmeli `prize_1` sınıfı `< D`) | 1,8406 | `-0,0002` (`-0,0012`…`+0,0009`) | 2/5 | 33,25% | 53,15% | 67,16% | Elendi |
| 17 | `E4_fark` | E4 | `E0` + `X_FARK` (`runner_extra` bitiş farkı / yakın kayıp `< D`) | 1,8407 | `-0,0001` (`-0,0011`…`+0,0008`) | 4/5 | 33,19% | 53,07% | 67,02% | Elendi |
| 18 | `E4_stew` | E4 | `E0` + `X_STEW` (`steward_notes` komiser geçmişi `< D`) | 1,8408 | `+0,0000` (`+0,0000`…`+0,0000`) | 0/5 | 33,21% | 53,14% | 67,02% | Elendi |
| 19 | `E4_pool` | E4 | `E0` + `X_POOL` (`pools` şehir havuz derinliği / deplasman `< D`) | 1,8411 | `+0,0004` (`-0,0006`…`+0,0013`) | 2/5 | 33,08% | 53,27% | 66,84% | Elendi |
| 20 | `E1a` | E1 | Uzun geçmiş (a): `2005-01-01→` öz. geçmişi, `2015→` AGF'li eğitim | 1,8412 | `+0,0004` (`-0,0006`…`+0,0014`) | 1/5 | 33,11% | 53,15% | 67,07% | Elendi |
| 21 | `E4_gc` | E4 | `E0` + `X_GC` (`runner_extra` geç çıkış geçmişi `< D`) | 1,8412 | `+0,0004` (`-0,0005`…`+0,0014`) | 2/5 | 33,18% | 53,16% | 67,05% | Elendi |
| 22 | `E5_iso` | E5 | `E0` üzerinde ileri-yürüyen izotonik kalibrasyon | 1,8417 | `+0,0010` (`+0,0002`…`+0,0018`) | 1/5 | 33,10% | 53,12% | 66,99% | Elendi |
| 23 | `E1b` | E1 | Uzun geçmiş (b): `2005-01-01→` öz. + `2005–2014` AGF'siz satırlar eğitimde | 1,8426 | `+0,0018` (`-0,0004`…`+0,0041`) | 2/5 | 32,86% | 52,84% | 67,02% | Elendi |
| — | `Ref_2015_Gecmis` | Kontrol | `2015-01-01→` öz. geçmişi + `2015→` eğitim (`2005–2014` kesik) | 1,8397 | `-0,0011` (`-0,0026`…`+0,0004`) | 3/5 | 33,22% | 53,20% | 67,10% | Bilgi kontrolü |

### 2.3 Aşama B — Doğrulama Kümesi (`2022–2025`, `24.515` Koşu)

| Varyant | Koşu | Log-Loss | ΔLL vs E0 (%95 GA) | ΔLL vs AGF (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı Kararı |
|---|---:|---:|---|---|---:|---:|---:|---:|---|
| `B0` (Saf AGF) | 24.515 | 1,7898 | `+0,0226` (`+0,0204`…`+0,0249`) | — | 0/4 | 34,28% | 54,97% | 69,04% | Referans |
| `E0` (`B1_SGR`) | 24.515 | 1,7672 | — | `-0,0226` (`-0,0249`…`-0,0204`) | 0/4 | 34,96% | 56,03% | 70,03% | Taban |
| `E3` | 24.515 | 1,7649 | `-0,0023` (`-0,0032`…`-0,0014`) | `-0,0249` (`-0,0273`…`-0,0228`) | 4/4 | 35,13% | 56,12% | 69,93% | **GEÇTİ** |
| **`E5_best_temp`** | **24.515** | **1,7644** | **`-0,0027` (`-0,0037`…`-0,0018`)** | **`-0,0254` (`-0,0277`…`-0,0232`)** | **4/4** | **35,13%** | **56,12%** | **69,93%** | **GEÇTİ (`V6_CONFIG`)** |

### 2.4 Aşama C — 2026 Bilgi Kümesi (`5.362` Koşu — *kilit v5'te tüketildi, temiz test DEĞİL*)

> **Uyarı:** `2026` kilitli testi Model v5'te tek seferlik tüketilmiştir (`docs/V5_KILITLI_SONUC.md`). Bu tablo model seçiminde veya kapı kararında **kullanılmamıştır**; yalnız bilgi amaçlıdır.

| Varyant | Koşu | Log-Loss | ΔLL vs E0 (%95 GA) | ΔLL vs AGF (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |
|---|---:|---:|---|---|---:|---:|---:|
| `B0` (Saf AGF) | 5.362 | 1,8106 | `+0,0223` (`+0,0176`…`+0,0272`) | — | 34,13% | 54,89% | 68,13% |
| `E0` (`B1_SGR`) | 5.362 | 1,7883 | — | `-0,0223` (`-0,0272`…`-0,0176`) | 34,65% | 56,06% | 69,68% |
| **`E5_best_temp`** | **5.362** | **1,7856** | **`-0,0027` (`-0,0045`…`-0,0008`)** | **`-0,0250` (`-0,0298`…`-0,0201`)** | **34,78%** | **55,82%** | **69,56%** |
| `E3` | 5.362 | 1,7852 | `-0,0031` (`-0,0047`…`-0,0014`) | `-0,0254` (`-0,0302`…`-0,0207`) | 34,78% | 55,82% | 69,56% |

### 2.5 Seçilen Aday (`E5_best_temp`) Yıllık ΔLL ve İlk-k Kapsama Tablosu (`2017–2026`)

| Yıl | Dönem | Koşu | Saf AGF LL (Top1 / İlk-2 / İlk-3) | `E0` LL (Top1 / İlk-2 / İlk-3) | `E5_best_temp` LL (Top1 / İlk-2 / İlk-3) | ΔLL (`E5_best_temp` − `E0`, %95 GA) |
|---:|---|---:|---|---|---|---|
| 2017 | Aşama A | 4.834 | 1,8383 (33,8% / 52,9% / 67,3%) | 1,8284 (33,6% / 53,6% / 67,4%) | 1,8234 (33,8% / 53,7% / 67,6%) | `-0,0049` (`-0,0087`…`-0,0010`) |
| 2018 | Aşama A | 4.962 | 1,8481 (32,8% / 53,3% / 66,9%) | 1,8352 (33,4% / 53,0% / 67,1%) | 1,8302 (33,6% / 53,3% / 67,5%) | `-0,0050` (`-0,0081`…`-0,0019`) |
| 2019 | Aşama A | 4.924 | 1,8787 (32,5% / 51,0% / 66,0%) | 1,8544 (32,9% / 53,4% / 67,2%) | 1,8524 (33,1% / 53,0% / 67,0%) | `-0,0021` (`-0,0049`…`+0,0009`) |
| 2020 | Aşama A | 4.721 | 1,8559 (31,3% / 51,9% / 65,5%) | 1,8385 (32,5% / 52,7% / 67,0%) | 1,8324 (32,6% / 53,8% / 66,9%) | `-0,0061` (`-0,0085`…`-0,0036`) |
| 2021 | Aşama A | 5.402 | 1,8668 (32,6% / 52,3% / 66,1%) | 1,8467 (33,6% / 53,1% / 66,5%) | 1,8428 (33,5% / 53,1% / 67,2%) | `-0,0038` (`-0,0059`…`-0,0016`) |
| 2022 | Aşama B | 5.996 | 1,7999 (34,8% / 54,5% / 68,6%) | 1,7782 (34,9% / 55,6% / 69,7%) | 1,7740 (35,1% / 55,6% / 69,7%) | `-0,0042` (`-0,0061`…`-0,0022`) |
| 2023 | Aşama B | 5.998 | 1,7975 (33,3% / 54,2% / 69,2%) | 1,7758 (34,3% / 55,3% / 69,6%) | 1,7722 (34,4% / 55,5% / 69,5%) | `-0,0036` (`-0,0054`…`-0,0018`) |
| 2024 | Aşama B | 6.229 | 1,7690 (34,5% / 55,5% / 69,4%) | 1,7446 (35,1% / 56,8% / 70,5%) | 1,7436 (35,2% / 56,8% / 70,1%) | `-0,0010` (`-0,0029`…`+0,0009`) |
| 2025 | Aşama B | 6.292 | 1,7935 (34,5% / 55,6% / 69,0%) | 1,7708 (35,5% / 56,4% / 70,2%) | 1,7685 (35,8% / 56,5% / 70,4%) | `-0,0023` (`-0,0040`…`-0,0006`) |
| 2026 | 2026 Bilgi | 5.362 | 1,8106 (34,1% / 54,9% / 68,1%) | 1,7883 (34,7% / 56,1% / 69,7%) | 1,7856 (34,8% / 55,8% / 69,6%) | `-0,0027` (`-0,0045`…`-0,0008`) |

*(Not: Aşama B yıllık ayrıntısında tam hassasiyetli 1. tercih / İlk-2 / İlk-3 oranları `E5_best_temp` ve `E3` için birebir aynı olup sırasıyla 2022: `35,11% / 55,62% / 69,71%`, 2023: `34,39% / 55,50% / 69,51%`, 2024: `35,17% / 56,75% / 70,11%`, 2025: `35,79% / 56,55% / 70,36%` şeklindedir.)*

---

## 3. Kapı Sonucu, Denenen Varyant Sayısı ve `V6_CONFIG` Tanımı

- **Denenen varyant sayısı ve çoklu karşılaştırma uyarısı:** `E0` tabanına karşı toplam **23 V6 aday yapılandırması** sınanmıştır:
  - `E1` uzun geçmiş: **2** varyant (`E1a`, `E1b`) [+ aday seçimine girmeyen **1** geçmiş-kesme kontrolü `Ref_2015_Gecmis`]
  - `E2` HGB hiperparametre ızgarası: **10** varyant (`E2_01` … `E2_10`)
  - `E3` çoklu tohum (5 tohum): **1** varyant (`E3`, Aşama A'nın en iyi E1/E2 modeli `E2_07` üzerinde)
  - `E4` yeni koşu-öncesi özellik grupları: **6** varyant (`E4_gc`, `E4_fark`, `E4_s800`, `E4_prize`, `E4_pool`, `E4_stew` — toplam `25` yeni sütun)
  - `E5` ileri-yürüyen kalibrasyon: **4** varyant (`E5_temp`, `E5_iso`, `E5_best_temp`, `E5_best_iso`)
- **Sabit kapı kuralı ve sonucu (Aşama B `2022–2025`):** Koşu-eşli bootstrap (`2.000` tekrar, sabit tohum `0`) `%95 GA` üst sınırı `< 0` **VE** `4` yılın en az `3`'ünde `ΔLL < 0`.
  - Aşama B'ye taşınan iki adaydan `E3` (`ΔLL = −0,0023`, GA `−0,0032…−0,0014`, `4/4` yıl negatif) ve `E5_best_temp` (`ΔLL = −0,0027`, GA `−0,0037…−0,0018`, `4/4` yıl negatif) kapıyı **geçmiştir**; doğrulama kümesinde daha düşük log-loss üreten **`E5_best_temp`** kazanan yapılandırma (`V6_CONFIG`) olmuştur.
  - **Seçilim büzülmesi (winner's curse) değerlendirmesi:** 23 aday arasından seçim yapıldığı için Aşama A'daki `−0,0043` kazancının örnek-dışı Aşama B'de `−0,0027`'ye daralması (~%37 büzülme) beklenen çoklu karşılaştırma etkisidir. Aşama B kapısına yalnız 2 adayın sokulması sayesinde kalan `−0,0027` iyileşmenin üst güven sınırı (`−0,0018`) sıfırdan belirgin biçimde uzakta kalmıştır (`2017–2026` arasındaki **10 yılın 10'unda da** nokta `ΔLL < 0`, bunların `8`'inde tekil yıl bazında da `%95 GA < 0`; yalnız `2019` ve `2024` tek başına sıfırı keser).
  - **Sıralama vs olasılık kalitesi:** Aşama B'de `E5_best_temp` 1. tercih isabetini `%34,96 → %35,13` (`+0,17` puan), İlk-2'yi `%56,03 → %56,12` (`+0,09` puan) taşırken İlk-3 `%70,03 → %69,93` (`−0,10` puan) düzeyinde kalmıştır. Kazanç esasen koşu içi sıralamayı kökten değiştirmekten değil, **sürpriz kuyruğu düzenlileştirmesi ve koşu içi olasılık keskinliğinden** gelmektedir.
- **Sabitlenen `V6_CONFIG` (`ganyan/model_v6.py`):**
  - **Özellik kümesi:** `68` sütun (`B1_SGR` ile birebir aynı; `extra_blocks = []`), özellik geçmişi `2006-03-04→`, eğitim `2015→` (`require_agf = True`).
  - **HGB parametreleri (`E2_07`):** `max_iter=420`, `learning_rate=0.03`, `max_leaf_nodes=23`, `min_samples_leaf=400`, `l2_regularization=15.0`, `early_stopping=False`.
  - **Topluluk ve kalibrasyon:** Tohumlar `[0, 1, 2, 3, 4]` ham olasılık ortalaması + koşu içi normalize (`E3`), ardından yalnız `< Y` yıllarının örnek-dışı tahminleriyle uydurulan koşu-içi logit/sıcaklık ölçeklemesi (`gamma = 1/T`: `2017`'de `0,9794` / `T=1,0211` → `2021`'de `1,0030` / `T=0,9970` → `2022`'de `1,0139` → `2025`'te `1,0336` → `2026`'da `1,0307` / `T=0,9702`).

---

## 4. Hangi Deney İşe Yaradı / Yaramadı ve Olası Nedenleri

1. **İşe yaradı — `E2` ağır yaprak düzenlileştirmesi ve `early_stopping=False` (Aşama A'da `−0,0043`'e kadar):**
   - `E0` tabanının varsayılan HGB ayarları (`max_iter=300, lr=0.04, leaf=31, min_samples_leaf=60, l2=1.0, early_stopping='auto'`) iki açıdan alt-optimaldi: (i) `early_stopping='auto'` eğitim satırlarının %10'unu rastgele doğrulama için ayırarak örneklem kaybı ve rastgele durma varyansı yaratıyordu; (ii) `min_samples_leaf=60, l2=1.0` gürültülü yarış sonuçlarında seyrek yapraklarda aşırı uç olasılıklar üretiyordu.
   - Eğitim verisinin %100'ünü kullanan (`es=False`) ve yüksek yaprak alt sınırı + güçlü L2 uygulayan tüm `E2` varyantları `5/5` yılda iyileşme verdi (`E2_07`: `−0,0043`, `E2_03`: `−0,0039`, `E2_04`: `−0,0038`, `E2_06`: `−0,0034`, `E2_05`: `−0,0029`). Zamansal erken durdurmalı `E2_10` (`tv=0.15`, `−0,0038`) da rastgele `auto` durdurmalı varyantlardan (`E2_01`/`E2_02`/`E2_08`/`E2_09`: `−0,0008…−0,0016`) belirgin biçimde üstün çıktı.
2. **Sınırlı ek katkı verdi — `E3` 5-tohum topluluğu (Aşama A'da `E2_07` üzerine ek `−0,0001`):**
   - `E2_07` üzerinde 5 tohum (`0..4`) ortalaması `LL`'yi `1,8365`'ten `1,8364`'e (`ΔLL` `−0,0043 → −0,0044`) indirdi. `early_stopping=False` olduğunda ağaçlar aynı eğitim verisi üzerinde kurulduğundan tohumlar arası çeşitlilik yalnız HGB'nin içsel histogram kutulama alt-örneklemesinden gelir; bu nedenle kazanımın büyük gövdesi `E2_07` hiperparametrelerine aittir.
3. **Kısmen işe yaradı — `E5` sıcaklık kalibrasyonu (`E5_best_temp`), işe yaramadı — izotonik kalibrasyon (`E5_iso`, `E5_best_iso`):**
   - Ağır düzenlileştirilmiş (`min=400, l2=15.0`) `E3` modeli özellikle eğitim kümesinin büyüdüğü `2022–2025` yıllarında hafifçe tutucu olasılıklar ürettiğinden, tek parametreli sıcaklık ölçeklemesi (`gamma ≈ 1,014–1,034`, yani hafif keskinleştirme) Aşama B'de `E3`'ün kazancını `−0,0023`'ten `−0,0027`'ye çıkardı (`2026` bilgi kümesinde ise `E3` `−0,0031`, `E5_best_temp` `−0,0027` ile başa baş kaldı). Düzenlileştirmesi zayıf `E0` üzerinde ise sıcaklık kalibrasyonu (`E5_temp`: `−0,0002`) neredeyse etkisiz kaldı.
   - İzotonik kalibrasyon hem `E0` üzerinde (`E5_iso`: `+0,0010`) hem `E3` üzerinde (`E5_best_iso`: `−0,0044`'ten `−0,0031`'e gerileme) performansı bozdu; basamaklı (piecewise-constant) marjinal eğrinin koşu içi yeniden normalizasyonla birleştiğinde kuyruk olasılıklarına basamak gürültüsü eklemesi olası nedendir.
4. **İşe yaramadı — `E1` uzun geçmiş (`2005–2014`) denemeleri (`E1a`: `+0,0004`, `E1b`: `+0,0018`):**
   - **Neden `E1a` çalışmadı?** Kod incelemesi ve DB sayımı, v5'in (`run_v5_backtest.py`) `--start-year 2015` süzgecini yalnız eğitim satırlarına uyguladığını, özellik inşasına ise o zamanki DB'nin tamamını (`2006-03-04→`) zaten beslediğini gösterdi. Dolayısıyla `E0` zaten `2006–2014` özellik geçmişini içeriyordu; `E1a` yalnız yeni eklenen `2005-01-01…2006-03-03` dilimini kattı ve `2017+` koşularındaki aktif atlar için 12 yıl önceki verinin marjinal etkisi sıfır oldu (`+0,0004`). Üstelik `2005–2014` özellik geçmişini tamamen kesen `Ref_2015_Gecmis` kontrolü bile Aşama A'da `−0,0011` (`−0,0026…+0,0004`) verdi; yarış atlarının aktif kariyeri kısa olduğundan çok eski yıllar yalnız pist hız referansına rejim kayması taşıyor olabilir.
   - **Neden `E1b` zarar verdi (`+0,0018`, `2017`'de `+0,0078`)?** `2005–2014` arasındaki `429.732` koşucu satırında modelin en güçlü özelliği olan **`agf_close` tamamen boştur (`%0,0`)**, galop yoktur (`%0,0–%0,8`) ve `2005–2009`'da `yb_hiz` yoktur (`%0,0`). AGF'si `NaN` olan yüz binlerce satırı eğitime katmak, ağaç yapısını AGF'siz rejime kaydırarak AGF'li test yıllarında olasılık kalitesini bozdu.
5. **İşe yaramadı — `E4` yeni koşu-öncesi özellik blokları (`−0,0005` … `+0,0004`, hepsi gürültü bandında):**
   - **Veri boşlukları:** `steward_notes` tüm veritabanında `0` satır olduğundan `E4_stew` sıfır bilgi taşıdı (`ΔLL = +0,0000`). Ayrıca `runner_extra` (`fark`, `gec_cikis`), `race_extra` (`son800`, `prize_1`) ve `pools` tabloları `2025` ve `2026` yıllarında `%0,0` doludur (`pools` `2005–2015`'te de `0` gün; `city_ganyan_share_90d` tüm veride `%0,0` sıfır-dışı).
   - **Sinyal örtüşmesi:** Bu alanların dolu olduğu Aşama A yıllarında (`2017–2021`: `son800` `%98,8–%99,6`, `prize_1` `%100`, `fark` `%30,5–%39,9`, `pools` `284–365` gün) bile hiçbir blok anlamlı kazanç üretmedi (`E4_s800`: `−0,0005`, `E4_prize`: `−0,0002`, `E4_fark`: `−0,0001`, `E4_pool`: `+0,0004`, `E4_gc`: `+0,0004`). Kapanış AGF'si (`agf_share`) ile mevcut `B1_SGR` özellikleri (`h_beaten_*`, `h_fpct_*`, `hp`, `sfa_*`, `yb_hiz_*`, `elo_*`) atın sınıfını, temposunu ve bitiş yakınlığını zaten büyük ölçüde soğurmaktadır.

---

## 5. Değer Bahsi ve Kenar Kovası Analizi (Kırılganlık Uyarılarıyla)

1 TL sabit bahis, `EV = p_model × nihai ganyan temettüsü`; güven aralıkları gün-kümeli bootstrap `%95 GA`.

### 5.1 EV Eşikleri Karşılaştırması (`Saf AGF` vs `E0` vs `E5_best_temp`)

| Dönem | Model | Eşik | Bahis | Kazanma % | ROI | ROI %95 GA | En Büyük 10 Hariç Bahis | En Büyük 10 Kazanç Hariç ROI (%95 GA) |
|---|---|---:|---:|---:|---:|---|---:|---|
| Aşama B (2022–2025) | `Saf AGF (B0)` | `≥1,20` | 3.986 | 6,80% | `-5,42%` | `[-19,90%, +8,84%]` | 3.976 | `-19,08%` (`[-29,69%, -8,21%]`) |
| Aşama B (2022–2025) | `Saf AGF (B0)` | `≥1,35` | 1.450 | 6,83% | `+19,77%` | `[-9,56%, +50,90%]` | 1.440 | `-16,33%` (`[-34,74%, +1,67%]`) |
| Aşama B (2022–2025) | `Saf AGF (B0)` | `≥1,50` | 613 | 5,22% | `+3,52%` | `[-42,93%, +58,01%]` | 603 | `-65,76%` (`[-79,84%, -49,23%]`) |
| Aşama B (2022–2025) | `E0 (B1_SGR)` | `≥1,20` | 8.338 | 8,47% | `+16,12%` | `[+5,19%, +27,21%]` | 8.328 | `+8,28%` (`[-1,22%, +17,53%]`) |
| Aşama B (2022–2025) | `E0 (B1_SGR)` | `≥1,35` | 3.942 | 7,66% | `+18,89%` | `[+2,39%, +33,93%]` | 3.932 | `+4,15%` (`[-9,71%, +17,35%]`) |
| Aşama B (2022–2025) | `E0 (B1_SGR)` | `≥1,50` | 1.959 | 7,25% | `+23,37%` | `[-1,64%, +47,61%]` | 1.949 | `-1,25%` (`[-17,09%, +15,19%]`) |
| Aşama B (2022–2025) | `E5_best_temp` | `≥1,20` | 7.599 | 9,00% | `+14,89%` | `[+4,14%, +24,91%]` | 7.589 | `+6,39%` (`[-2,82%, +15,87%]`) |
| Aşama B (2022–2025) | `E5_best_temp` | `≥1,35` | 3.489 | 8,40% | `+17,01%` | `[+1,20%, +31,88%]` | 3.479 | `+3,35%` (`[-10,00%, +15,73%]`) |
| Aşama B (2022–2025) | `E5_best_temp` | `≥1,50` | 1.615 | 8,24% | `+31,02%` | `[+7,44%, +56,86%]` | 1.605 | `+3,93%` (`[-14,65%, +23,32%]`) |
| Dev Tümü (2017–2025) | `Saf AGF (B0)` | `≥1,20` | 5.788 | 7,24% | `-6,25%` | `[-17,93%, +5,08%]` | 5.778 | `-16,22%` (`[-25,04%, -6,97%]`) |
| Dev Tümü (2017–2025) | `Saf AGF (B0)` | `≥1,35` | 2.120 | 7,92% | `+19,06%` | `[-4,62%, +42,44%]` | 2.110 | `-7,52%` (`[-23,24%, +10,02%]`) |
| Dev Tümü (2017–2025) | `Saf AGF (B0)` | `≥1,50` | 908 | 7,38% | `+3,52%` | `[-33,83%, +44,15%]` | 898 | `-46,75%` (`[-61,49%, -29,25%]`) |
| Dev Tümü (2017–2025) | `E0 (B1_SGR)` | `≥1,20` | 13.388 | 8,25% | `+10,32%` | `[+2,68%, +18,61%]` | 13.378 | `+4,82%` (`[-2,30%, +12,32%]`) |
| Dev Tümü (2017–2025) | `E0 (B1_SGR)` | `≥1,35` | 6.291 | 7,71% | `+16,63%` | `[+3,36%, +29,86%]` | 6.281 | `+5,83%` (`[-4,71%, +16,16%]`) |
| Dev Tümü (2017–2025) | `E0 (B1_SGR)` | `≥1,50` | 3.093 | 7,11% | `+17,25%` | `[-1,65%, +37,30%]` | 3.083 | `-0,73%` (`[-14,67%, +13,55%]`) |
| Dev Tümü (2017–2025) | `E5_best_temp` | `≥1,20` | 12.942 | 8,85% | `+11,50%` | `[+3,53%, +19,42%]` | 12.932 | `+5,79%` (`[-1,62%, +13,05%]`) |
| Dev Tümü (2017–2025) | `E5_best_temp` | `≥1,35` | 5.945 | 8,24% | `+16,45%` | `[+5,12%, +30,84%]` | 5.935 | `+5,96%` (`[-5,74%, +16,39%]`) |
| Dev Tümü (2017–2025) | `E5_best_temp` | `≥1,50` | 2.834 | 7,87% | `+25,51%` | `[+7,33%, +45,26%]` | 2.824 | `+6,03%` (`[-8,97%, +21,68%]`) |
| 2026 (Bilgi) | `Saf AGF (B0)` | `≥1,20` | 495 | 12,32% | `+12,20%` | `[-22,18%, +55,65%]` | 485 | `-29,16%` (`[-50,44%, -6,50%]`) |
| 2026 (Bilgi) | `Saf AGF (B0)` | `≥1,35` | 201 | 14,93% | `+36,79%` | `[-9,94%, +92,24%]` | 191 | `-46,31%` (`[-69,54%, -19,54%]`) |
| 2026 (Bilgi) | `Saf AGF (B0)` | `≥1,50` | 100 | 11,00% | `+4,05%` | `[-56,20%, +69,77%]` | 90 | `-96,78%` (`[-100,00%, -90,64%]`) |
| 2026 (Bilgi) | `E0 (B1_SGR)` | `≥1,20` | 1.348 | 10,16% | `+11,00%` | `[-10,10%, +32,63%]` | 1.338 | `-10,65%` (`[-27,10%, +5,69%]`) |
| 2026 (Bilgi) | `E0 (B1_SGR)` | `≥1,35` | 581 | 9,64% | `+13,37%` | `[-13,55%, +43,46%]` | 571 | `-26,08%` (`[-46,99%, -2,91%]`) |
| 2026 (Bilgi) | `E0 (B1_SGR)` | `≥1,50` | 278 | 8,27% | `+4,35%` | `[-36,65%, +50,62%]` | 268 | `-63,99%` (`[-82,10%, -42,87%]`) |
| 2026 (Bilgi) | `E5_best_temp` | `≥1,20` | 1.232 | 11,53% | `+20,48%` | `[+0,80%, +42,94%]` | 1.222 | `-1,11%` (`[-18,44%, +18,09%]`) |
| 2026 (Bilgi) | `E5_best_temp` | `≥1,35` | 542 | 10,70% | `+19,87%` | `[-8,81%, +53,43%]` | 532 | `-21,69%` (`[-42,88%, +0,73%]`) |
| 2026 (Bilgi) | `E5_best_temp` | `≥1,50` | 251 | 8,76% | `+17,63%` | `[-34,70%, +69,05%]` | 241 | `-63,71%` (`[-82,33%, -41,09%]`) |

### 5.2 Kenar Kovası (`edge = p_model / p_mkt`, `compute_edge_buckets`) — Aşama B (`2022–2025`)

| Kenar Kovası (`p_model / p_mkt`) | `Saf AGF (B0)`: Bahis, Kaz.%, ROI (%95 GA) | `E0 (B1_SGR)`: Bahis, Kaz.%, ROI (%95 GA) | `E5_best_temp`: Bahis, Kaz.%, ROI (%95 GA) |
|---|---|---|---|
| `<0,8` | 65.742, `5,72%`, `-59,28%` (`-61,49%…-57,12%`) | 74.890, `5,10%`, `-63,83%` (`-65,75%…-61,92%`) | 80.446, `4,75%`, `-63,41%` (`-65,48%…-61,43%`) |
| `0,8–0,95` | 42.505, `12,06%`, `-37,68%` (`-40,28%…-35,04%`) | 37.827, `12,38%`, `-39,53%` (`-42,16%…-36,80%`) | 36.578, `12,34%`, `-37,74%` (`-40,45%…-34,85%`) |
| `0,95–1,05` | 30.634, `13,52%`, `-32,88%` (`-35,83%…-29,98%`) | 26.281, `14,56%`, `-33,60%` (`-36,55%…-30,40%`) | 24.999, `14,58%`, `-35,13%` (`-38,11%…-32,20%`) |
| `1,05–1,2` | 39.623, `13,69%`, `-29,19%` (`-31,83%…-26,38%`) | 33.401, `15,07%`, `-28,07%` (`-30,87%…-25,27%`) | 32.576, `15,47%`, `-27,19%` (`-30,09%…-24,06%`) |
| `1,2–1,5` | 39.398, `11,95%`, `-25,91%` (`-28,78%…-22,93%`) | 38.281, `13,06%`, `-19,78%` (`-22,92%…-16,66%`) | 37.126, `14,11%`, `-17,44%` (`-20,52%…-14,47%`) |
| `>1,5` | 15.145, `8,94%`, `-22,08%` (`-27,58%…-16,17%`) | 22.367, `9,62%`, `-7,37%` (`-12,44%…-2,04%`) | 21.322, `10,57%`, `-5,85%` (`-10,85%…-0,65%`) |
| **Yalnız 1. Tercih (1 TL)** | 24.515, `34,28%`, `-27,96%` (`-29,34%…-26,65%`) | 24.515, `34,96%`, `-24,86%` (`-26,27%…-23,45%`) | 24.515, `35,13%`, `-24,23%` (`-25,65%…-22,81%`) |

### 5.3 Kırılganlık Uyarıları (Neden Doğrudan Kâr Kanıtı Değildir?)

1. **En büyük 10 kazanç bağımlılığı (sağ kuyruk kırılganlığı):** Görünürdeki çift haneli ROI rakamları bir avuç yüksek ganyanlı sürpriz isabete dayanmaktadır. **En büyük 10 kazanç çıkarıldığında hiçbir dönemde ve hiçbir eşikte `%95 GA` alt sınırı sıfırın üzerinde kalmamaktadır:** Aşama B'de `E5_best_temp` ROI'si `EV ≥ 1,20`'de `+14,89% → +6,39%` (`[-2,82%, +15,87%]`), `EV ≥ 1,35`'te `+17,01% → +3,35%` (`[-10,00%, +15,73%]`), `EV ≥ 1,50`'de `+31,02% → +3,93%` (`[-14,65%, +23,32%]`) düzeyine çöker; `2026` bilgi kümesinde ise en büyük 10 kazanç çıkarıldığında tüm eşikler negatife döner (`-1,11%`, `-21,69%`, `-63,71%`).
2. **Nihai temettü, canlı oran gürültüsü ve kapanış AGF yanlılığı:** Tablodaki seçim `agf_close` ve koşu bittikten sonra kesinleşen **nihai ganyan temettüsü** üzerinden yapılmıştır; canlıda bahis anında yalnız geçici oran ve daha erken alınmış AGF bilinir. Kapanışa doğru havuza giren geç para modelin beğendiği atların nihai oranını düşürdüğünde veya canlı oranda gürültü olduğunda gerçekleşen ROI hızla erir.
3. **Yüksek örnekleme gürültüsü:** `EV ≥ 1,35` eşiğinde hiç model kullanmayan `Saf AGF (B0)` bile Aşama B'de `+19,77%` (`[-9,56%, +50,90%]`) ve `2026`'da `+36,79%` (`[-9,94%, +92,24%]`) görünmekte, en büyük 10 kazanç çıkarıldığında ise sırasıyla `-16,33%` ve `-46,31%` olmaktadır. `E5_best_temp`, ağır yaprak düzenlileştirmesi sayesinde `E0`'a kıyasla daha seçici davranıp her eşikte kazanma yüzdesini yükseltse de (`Aşama B EV ≥ 1,20`: `8,47% → 9,00%`, `EV ≥ 1,50`: `7,25% → 8,24%`), iki model arasındaki ROI farkları `±%10–25` genişliğindeki güven aralıkları içinde gürültü düzeyindedir.

---

## 6. Bir Sonraki Adım Önerisi (Canlıya Alma Ön Koşulları ve 2027 Kilidi)

1. **Canlıya / ileri-teste alma ön koşulları (`V6_CONFIG` = `E5_best_temp`):**
   - **Sıfır ek veri bağımlılığı:** `E5_best_temp` yeni E4 tablolarının hiçbirini kullanmaz (`extra_blocks = []`); `B1_SGR` ile birebir aynı `68` özelliği ister. Dolayısıyla canlıya alma ön koşulu `B1_SGR` ile aynıdır: koşu öncesinde `yenibeygir` hız, `liderform` galop ve `2006-03-04→` geçmiş veritabanından hesaplanan `sfa_*` + gün-dondurulmuş `Elo` özelliklerinin canlı hatta sızıntısız ve kesintisiz üretildiğinin doğrulanması.
   - **AGF ve canlı ganyan zamanlaması:** Tarihsel avantaj `agf_close` üzerinde ölçüldüğünden, ileri-test tahminlerinin AGF havuzu olgunlaştığında (altılı ilk ayak startına yakın / sonraki ayaklar için ilk ayak startı sonrasında) ayrıca kaydedilmesi ve canlı ganyan oranlarının kapanışa yakın zaman serisi olarak toplanıp nihai temettü sapmasının ölçülmesi gerekir.
   - **5-tohum + sıcaklık kalibrasyonu entegrasyonu:** Canlı özellik eşdeğerliği kanıtlandıktan sonra `V6_CONFIG`, mevcut ileri-test boru hattını bozmadan ayrı bir `model_version` olarak eklenebilir. 5 tohum (`0..4`) yıllık uyumu `~79 sn` sürdüğünden (`data/v6_run.log`: `2026` yılı `E3` `78,9 sn` + `E5_best_temp` `0,2 sn`) günlük toplu çalışmada hesaplama dar boğazı yoktur; sıcaklık katsayısı (`gamma`) her yıl başında yalnız önceki yılların örnek-dışı tahminleriyle güncellenmelidir.
2. **2027 kilitli testi planı:**
   - `2026` kilitli testi v5'te tüketildiği için `2026` verisi üzerinde yeni varyant/eşik araması yapılmamalıdır; `2026` sonuçları yalnız `2027` modelinin ileri-yürüyen eğitim (`2015–2026`) ve kalibrasyon (`2016–2026`) penceresine dahil edilebilir.
   - `2027` koşuları başlamadan önce dondurulmuş `V6_CONFIG` (`E5_best_temp`), `E0 (B1_SGR)` ve canlıdaki `B1` modellerini karşılaştıran ön-kayıtlı tek seferlik **"2027 Kilitli Testi"** tanımlanmalı ve paralel olarak ileri-test (`forward`) kaydıyla canlı AGF koşullarında izlenmelidir.
3. **Veri kazıyıcı hijyeni (V6 için şart değil, gelecek araştırmalar için not):** `2025–2026`'da `%0,0` görünen `race_extra` / `runner_extra` / `pools` alanları ile tüm yıllarda `0` satır olan `steward_notes` tablosu doldurulmadan bu tablolardan yeni özellik denemesi tekrarlanmamalıdır.
