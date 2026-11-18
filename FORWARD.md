# Ganyan — İleri Test (Forward-Test) Raporu

## Model Sürümü: `v1_agf`

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-18`
- **Toplam Kayıtlı Tahmin:** `372` koşu (`3829` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `335` koşu
- **AGF'si eksik/sıfır olduğu için dışlanan koşu:** `9`
- **Sonuçlanmış Geçerli Koşu:** `328`

### 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 32.9% | 1.9201 |
| Model (`v1_agf`) | 32.0% | 1.9261 |
| **Fark (Model − AGF)** | **-0.9%** | **+0.0060** |

- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** 1. tercih `[-4.3%, +2.1%]`, log-loss `[-0.0117, +0.0234]`
- **Model ≠ AGF Favorisi:** `55` koşu (AGF favorisi kazandı: `18`, Model favorisi kazandı: `15`)

### 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `62`
- **Sabit-k 6/6:** `9 / 62`
- **AGF — Amaç A 6/6:** `12 / 62`
- **Model Amaç A 6/6:** `10 / 62`

| Yöntem | 6/6 | Maliyet (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Sabit-k (AGF) | 9 / 62 | 56,497.50 | 17,371.54 | -69.3% |
| AGF — Amaç A | 12 / 62 | 58,165.00 | 24,219.95 | -58.4% |
| Model (`v1_agf`) — Amaç A | 10 / 62 | 58,086.25 | 16,829.40 | -71.0% |

### 3. Para (1 TL ganyan)

- **GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `0`

| Yöntem | Oynanan Koşu | Yatırılan (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Anlık AGF Favorisi | 328 | 328.00 | 239.65 | -26.9% |
| Model (`v1_agf`) | 328 | 328.00 | 228.15 | -30.4% |
| **Fark (Model − AGF)** | — | — | **-11.50** | **-3.5%** |

- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** `[-15.2%, +8.0%]`

## Model Sürümü: `v1_agf_late`

- **Model Sürümü:** `v1_agf_late`
- **Kayıt Tarih Aralığı:** `2026-11-15` … `2026-11-18`
- **Toplam Kayıtlı Tahmin:** `27` koşu (`294` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `27` koşu
- **Sonuçlanmış Geçerli Koşu:** `27`

### 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 33.3% | 1.8383 |
| Model (`v1_agf_late`) | 22.2% | 1.8469 |
| **Fark (Model − AGF)** | **-11.1%** | **+0.0087** |

- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** 1. tercih `[-22.2%, +0.0%]`, log-loss `[-0.0660, +0.0758]`
- **Model ≠ AGF Favorisi:** `4` koşu (AGF favorisi kazandı: `3`, Model favorisi kazandı: `0`)

### 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `2`
- **Sabit-k 6/6:** `0 / 2`
- **AGF — Amaç A 6/6:** `0 / 2`
- **Model Amaç A 6/6:** `0 / 2`

| Yöntem | 6/6 | Maliyet (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Sabit-k (AGF) | 0 / 2 | 1,822.50 | 0.00 | -100.0% |
| AGF — Amaç A | 0 / 2 | 1,890.00 | 0.00 | -100.0% |
| Model (`v1_agf_late`) — Amaç A | 0 / 2 | 1,845.00 | 0.00 | -100.0% |

### 3. Para (1 TL ganyan)

- **GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `0`

| Yöntem | Oynanan Koşu | Yatırılan (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Anlık AGF Favorisi | 27 | 27.00 | 15.55 | -42.4% |
| Model (`v1_agf_late`) | 27 | 27.00 | 9.20 | -65.9% |
| **Fark (Model − AGF)** | — | — | **-6.35** | **-23.5%** |

- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** `[-48.5%, +0.0%]`

## Erken ve Geç Tahmin (aynı koşular)

- **Ortak Sonuçlanmış Geçerli Koşu:** `27`

| Yöntem | Koşu | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|---:|
| AGF (erken, `v1_agf`) | 27 | 29.6% | 1.8728 |
| Model (erken, `v1_agf`) | 27 | 29.6% | 1.8761 |
| AGF (geç, `v1_agf_late`) | 27 | 33.3% | 1.8383 |
| Model (geç, `v1_agf_late`) | 27 | 22.2% | 1.8469 |
| **Fark (Model_geç − AGF_geç)** | 27 | **-11.1%** | **+0.0087** |

- **Koşu-Eşli Bootstrap %95 GA (Model_geç − AGF_geç, 2000 tekrar):** 1. tercih `[-22.2%, +0.0%]`, log-loss `[-0.0660, +0.0758]`

> ROI kapanış öncesi oranlarla değil, kesinleşmiş ödemelerle hesaplanır; küçük örneklemde tek büyük ikramiye sonucu belirler.
