# Ganyan — İleri Test (Forward-Test) Raporu

## Model Sürümü: `v1_agf`

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-15`
- **Toplam Kayıtlı Tahmin:** `325` koşu (`3307` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `288` koşu
- **AGF'si eksik/sıfır olduğu için dışlanan koşu:** `9`
- **Sonuçlanmış Geçerli Koşu:** `281`

### 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 34.5% | 1.8927 |
| Model (`v1_agf`) | 33.5% | 1.8962 |
| **Fark (Model − AGF)** | **-1.1%** | **+0.0035** |

- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** 1. tercih `[-5.0%, +2.8%]`, log-loss `[-0.0159, +0.0223]`
- **Model ≠ AGF Favorisi:** `48` koşu (AGF favorisi kazandı: `17`, Model favorisi kazandı: `14`)

### 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `53`
- **Sabit-k 6/6:** `9 / 53`
- **AGF — Amaç A 6/6:** `11 / 53`
- **Model Amaç A 6/6:** `10 / 53`

| Yöntem | 6/6 | Maliyet (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Sabit-k (AGF) | 9 / 53 | 48,296.25 | 17,371.54 | -64.0% |
| AGF — Amaç A | 11 / 53 | 49,896.25 | 19,613.58 | -60.7% |
| Model (`v1_agf`) — Amaç A | 10 / 53 | 49,616.25 | 16,829.40 | -66.1% |

### 3. Para (1 TL ganyan)

- **GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `0`

| Yöntem | Oynanan Koşu | Yatırılan (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Anlık AGF Favorisi | 281 | 281.00 | 221.30 | -21.2% |
| Model (`v1_agf`) | 281 | 281.00 | 206.95 | -26.4% |
| **Fark (Model − AGF)** | — | — | **-14.35** | **-5.1%** |

- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** `[-19.1%, +8.6%]`

## Model Sürümü: `v1_agf_late`

- **Model Sürümü:** `v1_agf_late`
- **Kayıt Tarih Aralığı:** `2026-11-15` … `2026-11-15`
- **Toplam Kayıtlı Tahmin:** `9` koşu (`88` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `9` koşu
- **Sonuçlanmış Geçerli Koşu:** `9`

### 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 22.2% | 1.9696 |
| Model (`v1_agf_late`) | 22.2% | 2.0133 |
| **Fark (Model − AGF)** | **+0.0%** | **+0.0437** |

- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** 1. tercih `[+0.0%, +0.0%]`, log-loss `[-0.0511, +0.1419]`
- **Model ≠ AGF Favorisi:** `0` koşu (AGF favorisi kazandı: `0`, Model favorisi kazandı: `0`)

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
| Anlık AGF Favorisi | 9 | 9.00 | 3.85 | -57.2% |
| Model (`v1_agf_late`) | 9 | 9.00 | 3.85 | -57.2% |
| **Fark (Model − AGF)** | — | — | **+0.00** | **+0.0%** |

- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** `[+0.0%, +0.0%]`

## Erken ve Geç Tahmin (aynı koşular)

- **Ortak Sonuçlanmış Geçerli Koşu:** `9`

| Yöntem | Koşu | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|---:|
| AGF (erken, `v1_agf`) | 9 | 22.2% | 2.0355 |
| Model (erken, `v1_agf`) | 9 | 22.2% | 2.0744 |
| AGF (geç, `v1_agf_late`) | 9 | 22.2% | 1.9696 |
| Model (geç, `v1_agf_late`) | 9 | 22.2% | 2.0133 |
| **Fark (Model_geç − AGF_geç)** | 9 | **+0.0%** | **+0.0437** |

- **Koşu-Eşli Bootstrap %95 GA (Model_geç − AGF_geç, 2000 tekrar):** 1. tercih `[+0.0%, +0.0%]`, log-loss `[-0.0511, +0.1419]`

> ROI kapanış öncesi oranlarla değil, kesinleşmiş ödemelerle hesaplanır; küçük örneklemde tek büyük ikramiye sonucu belirler.
