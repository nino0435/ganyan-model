# Ganyan İki Aşamalı Model (Bill Benter: P_temel + AGF) — Deneyler ve Kapı Raporu

> **Uyarı 1 (Kapanış AGF):** Standart Aşama A/B/C karşılaştırması kapanış AGF (`agf_close`) ile yapılır; erken/gürültülü sabah AGF etkisi Bölüm 6'da ayrıca ölçülmüştür.
> **Uyarı 2 (Seçim Protokolü):** `V10_1s` tabanına karşı önceden dondurulmuş 5 iki-aşamalı aday yalnız Aşama A (`2017–2021`) üzerinde `-0.0002` sıkı (`<`) eşiğiyle sınanır; Aşama B resmi kapısına **en fazla tek** aday taşınır.

## 1. Mimari ve Özellik Ayrımı Özeti

- **Veritabanı:** `data/ganyan.db` (salt-okunur, `2005-01-01` … `2026-11-22`)
- **Toplam Sonuçlanmış Koşucu / Koşu:** `1,071,637` satır / `107,472` koşu
- **Taban Model (`V10_CONFIG`):** `V10_HLB_CAL` (`v10_hlb`, `155` özellik)
- **Bugünün AGF'sine Bağımlı Sütunlar (`TODAY_AGF_COLS`, `8` adet — `P_temel`'den çıkarıldı):** `agf_share, log_agf, own_is_sub_agf, own_mate_agf, trn_is_sub_agf, agf_surge_ratio, sleep_wakeup_flag, h2h_vs_fav_margin`
- **Geçmiş `< D` Piyasa Sütunları (`PAST_MKT_COLS`, `10` adet — yalnız `SPORT_15`'ten çıkarıldı):** `h_logodds_last, h_logodds_m3, h_logodds_m3_rel, h_logodds_m3_rk, trn_away_resid_730d, trn_resid_14d, trn_resid_28d, trn_fpct_resid_28d, trn_resid_28d_rel, bias_gate_resid`
- **1. Aşama Saf Güç Özellikleri:** `FUND_15` / `FUND_06` = **`147` özellik** (bugünkü AGF `%0`), `SPORT_15` = **`137` özellik** (tüm tarih boyunca oran/AGF `%0`)
- **Değerlendirme Koşu Sayıları:** Aşama A `24,843` | Aşama B `24,515` | Aşama C (2026 bilgi) `5,483`

## 2. Aşama 0 — Tek Başına Saf Güç (`P_temel`, AGF=YOK) Performansı

Bu tablo **hiçbir AGF bilgisi görmeyen** 1. aşama saf modellerin tek başına ne kadar isabet ürettiğini (uygulamadaki *"Saf Pist Gücü"* kartı için) halkın kapanış AGF'si (`B0`) ile karşılaştırır:

| Dönem | Varyant | Eğitim Baş. | Öz. Sayısı | Koşu | Log-Loss | ΔLL vs AGF (`B0`) | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|
| `2017–2021` | `B0` | — | 1 (AGF) | 24,843 | 1.8578 | — | 32.61% | 52.27% | 66.36% |
| `2017–2021` | `FUND_06` | 2006 | 147 | 24,843 | 1.8924 | `+0.0346` (`+0.0291`…`+0.0398`) | 30.50% | 50.46% | 64.64% |
| `2017–2021` | `FUND_15` | 2015 | 147 | 24,843 | 1.8973 | `+0.0395` (`+0.0337`…`+0.0448`) | 30.48% | 50.24% | 64.45% |
| `2017–2021` | `SPORT_15` | 2015 | 137 | 24,843 | 1.8994 | `+0.0416` (`+0.0357`…`+0.0470`) | 30.38% | 50.17% | 64.55% |
| `2022–2025` | `B0` | — | 1 (AGF) | 24,515 | 1.7898 | — | 34.28% | 54.97% | 69.04% |
| `2022–2025` | `FUND_06` | 2006 | 147 | 24,515 | 1.8342 | `+0.0444` (`+0.0389`…`+0.0500`) | 32.37% | 52.57% | 66.90% |
| `2022–2025` | `FUND_15` | 2015 | 147 | 24,515 | 1.8316 | `+0.0418` (`+0.0363`…`+0.0473`) | 32.44% | 52.86% | 67.16% |
| `2022–2025` | `SPORT_15` | 2015 | 137 | 24,515 | 1.8346 | `+0.0447` (`+0.0392`…`+0.0503`) | 32.25% | 52.62% | 67.04% |
| `2026 (bilgi)` | `B0` | — | 1 (AGF) | 5,483 | 1.8140 | — | 34.05% | 54.59% | 67.85% |
| `2026 (bilgi)` | `FUND_06` | 2006 | 147 | 5,483 | 1.8678 | `+0.0538` (`+0.0425`…`+0.0657`) | 31.72% | 52.33% | 66.30% |
| `2026 (bilgi)` | `FUND_15` | 2015 | 147 | 5,483 | 1.8657 | `+0.0517` (`+0.0401`…`+0.0634`) | 31.70% | 52.36% | 66.44% |
| `2026 (bilgi)` | `SPORT_15` | 2015 | 137 | 5,483 | 1.8718 | `+0.0578` (`+0.0463`…`+0.0699`) | 31.48% | 52.03% | 66.42% |

## 3. Aşama A — İki Aşamalı Aday Taraması (`2017–2021`, 1-Tohum, Seçim Eşiği `< -0.0002`)

| Varyant | Açıklama | Koşu | Log-Loss | ΔLL vs `V10_1s` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---:|---|---:|---:|---:|---:|
| `B0` | Saf kapanış AGF | 24,843 | 1.8578 | `+0.0275` (`+0.0246`…`+0.0305`) | — | 32.61% | 52.27% | 66.36% |
| `V10_1s` | Tek aşamalı V10 tabanı (155 öz., 1 tohum) | 24,843 | 1.8303 | — | — | 33.49% | 53.52% | 67.46% |
| `BSTACK_HGB` | İki aşamalı yığılmış HGB: V10 (155 öz.) + sızıntısız FUND_06 dış-örneklem 4 öz. | 24,843 | 1.8278 | `-0.0025` (`-0.0043`…`-0.0007`) | 5/5 | 33.16% | 53.46% | 67.60% |
| `BBLEND_V10` | 3-yollu koşullu logit harmanı: V10 + FUND_06 + AGF | 24,843 | 1.8318 | `+0.0015` (`+0.0002`…`+0.0027`) | 1/5 | 33.22% | 53.36% | 67.35% |
| `BRICH_06` | Zengin koşullu logit: FUND_06 + AGF + asimetrik fark + saha boyu + 6 AGF etkileşimi | 24,843 | 1.8445 | `+0.0142` (`+0.0115`…`+0.0167`) | 0/5 | 32.62% | 52.64% | 66.79% |
| `B2P_15` | Benter 2-param koşullu logit: FUND_15 (2015→, 147 öz.) + AGF | 24,843 | 1.8466 | `+0.0163` (`+0.0138`…`+0.0186`) | 0/5 | 32.52% | 52.32% | 66.62% |
| `B2P_06` | Benter 2-param koşullu logit: FUND_06 (2006→ tam geçmiş, 147 öz.) + AGF | 24,843 | 1.8468 | `+0.0164` (`+0.0137`…`+0.0190`) | 0/5 | 32.35% | 52.43% | 66.71% |

### Aşama A Yıllık ΔLL(varyant − V10_1s) (`2017–2021`)

| Varyant | 2017 | 2018 | 2019 | 2020 | 2021 | Ort. ΔLL vs `V10_1s` |
|---| ---: | ---: | ---: | ---: | ---: |---:|
| `B0` | `+0.0214` | `+0.0260` | `+0.0322` | `+0.0293` | `+0.0285` | `+0.0275` |
| `V10_1s` | 1.8170 (LL) | 1.8221 (LL) | 1.8465 (LL) | 1.8266 (LL) | 1.8382 (LL) | 1.8303 (LL) |
| `BSTACK_HGB` | `-0.0021` | `-0.0012` | `-0.0028` | `-0.0048` | `-0.0019` | `-0.0025` |
| `BBLEND_V10` | `+0.0006` | `+0.0047` | `+0.0026` | `+0.0002` | `-0.0006` | `+0.0015` |
| `BRICH_06` | `+0.0095` | `+0.0170` | `+0.0172` | `+0.0132` | `+0.0139` | `+0.0142` |
| `B2P_15` | `+0.0097` | `+0.0177` | `+0.0194` | `+0.0166` | `+0.0177` | `+0.0163` |
| `B2P_06` | `+0.0096` | `+0.0193` | `+0.0204` | `+0.0170` | `+0.0159` | `+0.0164` |

- **Aşama A Seçim Kararı:** Aşama A'da `-0.0002` eşiğini geçen 1 aday arasından en düşük log-loss'a sahip `BSTACK_HGB` (`ΔLL = -0.0025`) tek aday olarak Aşama 3 resmi kapısına taşınmıştır.
- **Aşama 3 Resmi Kapı Adayı:** `BSTACK_HGB`

## 4. Aşama 2 — Tanısal Karşılaştırma (`2022–2025`, 1-Tohum, Seçimde Kullanılmaz)

| Varyant | Koşu | Log-Loss | ΔLL vs `V10_1s` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 |
|---|---:|---:|---|---:|---:|---:|---:|
| `B0` | 24,515 | 1.7898 | `+0.0317` (`+0.0293`…`+0.0344`) | — | 34.28% | 54.97% | 69.04% |
| `V10_1s` | 24,515 | 1.7581 | — | — | 35.37% | 56.35% | 70.41% |
| `BSTACK_HGB` | 24,515 | 1.7572 | `-0.0009` (`-0.0022`…`+0.0006`) | 3/4 | 35.34% | 56.37% | 70.54% |
| `BBLEND_V10` | 24,515 | 1.7583 | `+0.0002` (`-0.0004`…`+0.0009`) | 2/4 | 35.33% | 56.07% | 70.28% |
| `BRICH_06` | 24,515 | 1.7788 | `+0.0208` (`+0.0186`…`+0.0232`) | 0/4 | 34.60% | 55.30% | 69.33% |
| `B2P_15` | 24,515 | 1.7789 | `+0.0208` (`+0.0187`…`+0.0231`) | 0/4 | 34.66% | 55.26% | 69.31% |
| `B2P_06` | 24,515 | 1.7807 | `+0.0227` (`+0.0204`…`+0.0252`) | 0/4 | 34.62% | 55.12% | 69.04% |

### Aşama 2 Tanısal Yıllık ΔLL(varyant − V10_1s) (`2022–2025`)

| Varyant | 2022 | 2023 | 2024 | 2025 | Ort. ΔLL vs `V10_1s` |
|---| ---: | ---: | ---: | ---: |---:|
| `B0` | `+0.0333` | `+0.0298` | `+0.0319` | `+0.0319` | `+0.0317` |
| `V10_1s` | 1.7666 (LL) | 1.7677 (LL) | 1.7370 (LL) | 1.7615 (LL) | 1.7581 (LL) |
| `BSTACK_HGB` | `-0.0023` | `-0.0002` | `+0.0006` | `-0.0017` | `-0.0009` |
| `BBLEND_V10` | `-0.0005` | `+0.0006` | `+0.0010` | `-0.0001` | `+0.0002` |
| `BRICH_06` | `+0.0179` | `+0.0200` | `+0.0223` | `+0.0227` | `+0.0208` |
| `B2P_15` | `+0.0195` | `+0.0203` | `+0.0226` | `+0.0207` | `+0.0208` |
| `B2P_06` | `+0.0203` | `+0.0222` | `+0.0253` | `+0.0228` | `+0.0227` |

### Öğrenilen İki Aşamalı Birleştirici Ağırlıkları (Yalnız `< Y` Yıllarından)

| Birleştirici | Test Yılı | Eğitim Yılları | Öğrenilen Katsayılar |
|---|---:|---|---|
| `B2P_15` | 2017 | `2016` | `a(temel)=0.4804, b(agf)=0.6197` |
| `B2P_15` | 2019 | `2016–2018` | `a(temel)=0.4105, b(agf)=0.6668` |
| `B2P_15` | 2021 | `2016–2020` | `a(temel)=0.4111, b(agf)=0.6677` |
| `B2P_15` | 2022 | `2016–2021` | `a(temel)=0.4116, b(agf)=0.6754` |
| `B2P_15` | 2024 | `2016–2023` | `a(temel)=0.4164, b(agf)=0.6882` |
| `B2P_15` | 2025 | `2016–2024` | `a(temel)=0.4122, b(agf)=0.6932` |
| `B2P_15` | 2026 | `2016–2025` | `a(temel)=0.4128, b(agf)=0.6936` |
| `B2P_06` | 2017 | `2015–2016` | `a(temel)=0.5896, b(agf)=0.5490` |
| `B2P_06` | 2019 | `2015–2018` | `a(temel)=0.4992, b(agf)=0.6067` |
| `B2P_06` | 2021 | `2015–2020` | `a(temel)=0.4745, b(agf)=0.6237` |
| `B2P_06` | 2022 | `2015–2021` | `a(temel)=0.4715, b(agf)=0.6321` |
| `B2P_06` | 2024 | `2015–2023` | `a(temel)=0.4592, b(agf)=0.6554` |
| `B2P_06` | 2025 | `2015–2024` | `a(temel)=0.4467, b(agf)=0.6664` |
| `B2P_06` | 2026 | `2015–2025` | `a(temel)=0.4406, b(agf)=0.6717` |
| `BRICH_06` | 2017 | `2015–2016` | `temel=0.550, agf=0.552, +edge=-0.220, -edge=0.218` |
| `BRICH_06` | 2019 | `2015–2018` | `temel=0.517, agf=0.571, +edge=-0.095, -edge=0.041` |
| `BRICH_06` | 2021 | `2015–2020` | `temel=0.510, agf=0.574, +edge=-0.060, -edge=-0.004` |
| `BRICH_06` | 2022 | `2015–2021` | `temel=0.512, agf=0.579, +edge=-0.057, -edge=-0.011` |
| `BRICH_06` | 2024 | `2015–2023` | `temel=0.513, agf=0.592, +edge=-0.037, -edge=-0.043` |
| `BRICH_06` | 2025 | `2015–2024` | `temel=0.508, agf=0.595, +edge=-0.035, -edge=-0.052` |
| `BRICH_06` | 2026 | `2015–2025` | `temel=0.506, agf=0.599, +edge=-0.033, -edge=-0.060` |
| `BBLEND_V10` | 2017 | `2016` | `w_v10=0.4350, w_temel=0.4325, w_agf=0.2440` |
| `BBLEND_V10` | 2019 | `2016–2018` | `w_v10=0.6424, w_temel=0.2324, w_agf=0.1839` |
| `BBLEND_V10` | 2021 | `2016–2020` | `w_v10=0.7677, w_temel=0.1853, w_agf=0.0987` |
| `BBLEND_V10` | 2022 | `2016–2021` | `w_v10=0.8040, w_temel=0.1797, w_agf=0.0751` |
| `BBLEND_V10` | 2024 | `2016–2023` | `w_v10=0.8987, w_temel=0.1497, w_agf=0.0195` |
| `BBLEND_V10` | 2025 | `2016–2024` | `w_v10=0.9421, w_temel=0.1297, w_agf=-0.0088` |
| `BBLEND_V10` | 2026 | `2016–2025` | `w_v10=0.9705, w_temel=0.1220, w_agf=-0.0339` |

## 5. Aşama 3 — Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Kalibrasyon, `vs V10_HLB_CAL`)

| Varyant | Koşu | Log-Loss | ΔLL vs `V10_HLB_CAL` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 | Kapı |
|---|---:|---:|---|---|---:|---:|---:|---:|---|
| `B0` | 24,515 | 1.7898 | `+0.0329` (`+0.0304`…`+0.0355`) | — | 0/4 | 34.28% | 54.97% | 69.04% | Referans |
| `V10_HLB_CAL` | 24,515 | 1.7569 | — | `-0.0329` (`-0.0355`…`-0.0304`) | 0/4 | 35.33% | 56.48% | 70.46% | Canlı Taban |
| `BSTACK_HGB_5s_CAL` | 24,515 | 1.7557 | `-0.0013` (`-0.0026`…`+0.0002`) | `-0.0341` (`-0.0371`…`-0.0312`) | 3/4 | 35.38% | 56.54% | 70.37% | **KALDI** |

### Aşama 3 Yıllık Kırılım (`vs V10_HLB_CAL`)

| Yıl | Varyant | Koşu | Log-Loss | ΔLL vs `V10_HLB_CAL` (%95 GA) | 1. Tercih | İlk-3 |
|---:|---|---:|---:|---|---:|---:|
| 2022 | `V10_HLB_CAL` | 5,996 | 1.7648 | — | 35.47% | 70.35% |
| 2022 | `BSTACK_HGB_5s_CAL` | 5,996 | 1.7628 | `-0.0020` (`-0.0048`…`+0.0008`) | 35.49% | 70.28% |
| 2023 | `V10_HLB_CAL` | 5,998 | 1.7659 | — | 34.68% | 69.96% |
| 2023 | `BSTACK_HGB_5s_CAL` | 5,998 | 1.7661 | `+0.0003` (`-0.0025`…`+0.0030`) | 34.68% | 69.79% |
| 2024 | `V10_HLB_CAL` | 6,229 | 1.7363 | — | 35.27% | 70.56% |
| 2024 | `BSTACK_HGB_5s_CAL` | 6,229 | 1.7362 | `-0.0002` (`-0.0027`…`+0.0023`) | 35.77% | 70.67% |
| 2025 | `V10_HLB_CAL` | 6,292 | 1.7614 | — | 35.87% | 70.95% |
| 2025 | `BSTACK_HGB_5s_CAL` | 6,292 | 1.7583 | `-0.0031` (`-0.0057`…`-0.0003`) | 35.57% | 70.69% |

### Aşama C — 2026 Bilgi Kümesi *(Seçim ve Kapıda Kullanılmaz)*

| Varyant | Koşu | Log-Loss | Tabana Göre ΔLL (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |
|---|---:|---:|---|---:|---:|---:|
| `B0` | 5,483 | 1.8140 | `+0.0319` (`+0.0267`…`+0.0371`) | 34.05% | 54.59% | 67.85% |
| `V10_HLB_CAL` | 5,483 | 1.7821 | — | 34.60% | 55.75% | 69.63% |
| `BSTACK_HGB_5s_CAL` | 5,483 | 1.7813 | `-0.0008` (`-0.0037`…`+0.0021`) | 34.51% | 55.75% | 69.76% |

## 6. Ürün ve Canlı Tanı 1 — Sabah / Erken Gürültülü AGF Dayanıklılığı (`2025`)

`V5_BULGULAR.md` §5'te ölçüldüğü üzere sabah erken AGF (`~5-6 saat` önce), kapanış AGF'den yaklaşık `+0.11` nats daha gürültülüdür (`σ_log ≈ 0.25–0.35`). Aşağıdaki tablo `2025` koşularında test anındaki AGF gürültülendiğinde veya sabah 07:00'de AGF henüz hiç açılmadığında tek aşamalı `V10_1s` ile iki aşamalı `B2P_06` / `FUND_06` modellerinin log-loss davranışını gösterir:

| Senaryo | Koşu | Gürültülü AGF LL | Tek Aşamalı `V10_1s` LL | `B2P_06` (Sabit) LL | `B2P_06` (Uyumlu) LL | Saf `FUND_06` LL | Uyumlu Ağırlıklar |
|---|---:|---:|---:|---:|---:|---:|---|
| σ=0.00 (Kapanış AGF) | 6,292 | 1.7935 | 1.7615 | 1.7843 | **1.7843** | 1.8424 | `a=0.447, b=0.666` |
| σ=0.15 | 6,292 | 1.8019 | 1.7700 | 1.7882 | **1.7885** | 1.8424 | `a=0.509, b=0.604` |
| σ=0.30 | 6,292 | 1.8276 | 1.7919 | 1.7999 | **1.7979** | 1.8424 | `a=0.635, b=0.479` |
| σ=0.50 | 6,292 | 1.8880 | 1.8440 | 1.8273 | **1.8102** | 1.8424 | `a=0.796, b=0.321` |
| AGF Yok (Sabah 07:00 bülteni) | 6,292 | — | 2.1019 | 1.8424 | **1.8424** | 1.8424 | `a=1.000, b=0.000 (saf P_temel)` |

## 7. Ürün ve Canlı Tanı 2 — Değer Ayrışması (`p >= %8` ve `p / AGF >= 1.5`, `2022–2025`)

`KUMARBAZ.md` içindeki *Değerci Deniz* kuralı (günde en çok 6 at, 1 TL düz ganyan, gün-kümeli 2000 bootstrap %95 GA) AGF'yi hiç görmeyen `FUND_06`, iki aşamalı modeller ve `V10_1s` için karşılaştırılmıştır:

| Model | Açıklama | Bahis Sayısı | İsabet | Tutan Medyan Ganyan | Bahis Başına Getiri [%95 GA] |
|---|---|---:|---:|---:|---|
| `V10_1s` | Tek aşamalı V10 (1 tohum) | 3,969 | 15.3% | 6.00 | `+7.0%` (`[-2.5%, +17.0%]`) |
| `FUND_06` | Saf Pist Gücü (AGF=Yok, 2006→) | 8,645 | 8.1% | 8.70 | `-19.4%` (`[-26.1%, -12.6%]`) |
| `B2P_06` | Benter 2-param (FUND_06 + AGF) | 971 | 11.8% | 6.70 | `-14.2%` (`[-31.5%, +5.6%]`) |
| `BRICH_06` | Zengin koşullu logit | 1,620 | 13.6% | 5.07 | `-18.9%` (`[-31.3%, -6.5%]`) |
| `BSTACK_HGB` | İki aşamalı yığılmış HGB | 5,564 | 13.6% | 6.95 | `+5.9%` (`[-2.9%, +14.4%]`) |
| `BBLEND_V10` | 3-yollu koşullu logit harmanı | 3,820 | 15.9% | 5.95 | `+8.2%` (`[-1.1%, +18.2%]`) |
