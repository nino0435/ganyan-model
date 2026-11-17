# Ganyan — İleri Test (Forward-Test) Raporu

## Model Sürümü: `v1_agf`

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-17`
- **Toplam Kayıtlı Tahmin:** `355` koşu (`3654` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `318` koşu
- **AGF'si eksik/sıfır olduğu için dışlanan koşu:** `9`
- **Sonuçlanmış Geçerli Koşu:** `311`

### 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 33.1% | 1.9099 |
| Model (`v1_agf`) | 32.2% | 1.9181 |
| **Fark (Model − AGF)** | **-1.0%** | **+0.0082** |

- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** 1. tercih `[-4.5%, +2.3%]`, log-loss `[-0.0105, +0.0274]`
- **Model ≠ AGF Favorisi:** `51` koşu (AGF favorisi kazandı: `17`, Model favorisi kazandı: `14`)

### 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `58`
- **Sabit-k 6/6:** `9 / 58`
- **AGF — Amaç A 6/6:** `12 / 58`
- **Model Amaç A 6/6:** `10 / 58`

| Yöntem | 6/6 | Maliyet (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Sabit-k (AGF) | 9 / 58 | 52,852.50 | 17,371.54 | -67.1% |
| AGF — Amaç A | 12 / 58 | 54,520.00 | 24,219.95 | -55.6% |
| Model (`v1_agf`) — Amaç A | 10 / 58 | 54,296.25 | 16,829.40 | -69.0% |

### 3. Para (1 TL ganyan)

- **GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `0`

| Yöntem | Oynanan Koşu | Yatırılan (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Anlık AGF Favorisi | 311 | 311.00 | 232.15 | -25.4% |
| Model (`v1_agf`) | 311 | 311.00 | 217.80 | -30.0% |
| **Fark (Model − AGF)** | — | — | **-14.35** | **-4.6%** |

- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** `[-17.6%, +6.9%]`

## Model Sürümü: `v1_agf_late`

- **Model Sürümü:** `v1_agf_late`
- **Kayıt Tarih Aralığı:** `2026-11-15` … `2026-11-17`
- **Toplam Kayıtlı Tahmin:** `18` koşu (`202` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `18` koşu
- **Sonuçlanmış Geçerli Koşu:** `18`

### 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 27.8% | 1.8404 |
| Model (`v1_agf_late`) | 16.7% | 1.9028 |
| **Fark (Model − AGF)** | **-11.1%** | **+0.0624** |

- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** 1. tercih `[-27.8%, +0.0%]`, log-loss `[-0.0027, +0.1258]`
- **Model ≠ AGF Favorisi:** `3` koşu (AGF favorisi kazandı: `2`, Model favorisi kazandı: `0`)

### 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `1`
- **Sabit-k 6/6:** `0 / 1`
- **AGF — Amaç A 6/6:** `0 / 1`
- **Model Amaç A 6/6:** `0 / 1`

| Yöntem | 6/6 | Maliyet (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Sabit-k (AGF) | 0 / 1 | 911.25 | 0.00 | -100.0% |
| AGF — Amaç A | 0 / 1 | 945.00 | 0.00 | -100.0% |
| Model (`v1_agf_late`) — Amaç A | 0 / 1 | 945.00 | 0.00 | -100.0% |

### 3. Para (1 TL ganyan)

- **GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `0`

| Yöntem | Oynanan Koşu | Yatırılan (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Anlık AGF Favorisi | 18 | 18.00 | 9.45 | -47.5% |
| Model (`v1_agf_late`) | 18 | 18.00 | 5.20 | -71.1% |
| **Fark (Model − AGF)** | — | — | **-4.25** | **-23.6%** |

- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** `[-58.3%, +0.0%]`

## Erken ve Geç Tahmin (aynı koşular)

- **Ortak Sonuçlanmış Geçerli Koşu:** `18`

| Yöntem | Koşu | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|---:|
| AGF (erken, `v1_agf`) | 18 | 22.2% | 1.8874 |
| Model (erken, `v1_agf`) | 18 | 22.2% | 1.9469 |
| AGF (geç, `v1_agf_late`) | 18 | 27.8% | 1.8404 |
| Model (geç, `v1_agf_late`) | 18 | 16.7% | 1.9028 |
| **Fark (Model_geç − AGF_geç)** | 18 | **-11.1%** | **+0.0624** |

- **Koşu-Eşli Bootstrap %95 GA (Model_geç − AGF_geç, 2000 tekrar):** 1. tercih `[-27.8%, +0.0%]`, log-loss `[-0.0027, +0.1258]`

> ROI kapanış öncesi oranlarla değil, kesinleşmiş ödemelerle hesaplanır; küçük örneklemde tek büyük ikramiye sonucu belirler.
