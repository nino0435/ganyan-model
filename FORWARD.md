# Ganyan — İleri Test (Forward-Test) Raporu

## Model Sürümü: `v1_agf`

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-16`
- **Toplam Kayıtlı Tahmin:** `339` koşu (`3493` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `302` koşu
- **AGF'si eksik/sıfır olduğu için dışlanan koşu:** `9`
- **Sonuçlanmış Geçerli Koşu:** `295`

### 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 33.6% | 1.9194 |
| Model (`v1_agf`) | 32.5% | 1.9240 |
| **Fark (Model − AGF)** | **-1.0%** | **+0.0046** |

- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** 1. tercih `[-4.7%, +2.7%]`, log-loss `[-0.0143, +0.0239]`
- **Model ≠ AGF Favorisi:** `49` koşu (AGF favorisi kazandı: `17`, Model favorisi kazandı: `14`)

### 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `54`
- **Sabit-k 6/6:** `9 / 54`
- **AGF — Amaç A 6/6:** `11 / 54`
- **Model Amaç A 6/6:** `10 / 54`

| Yöntem | 6/6 | Maliyet (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Sabit-k (AGF) | 9 / 54 | 49,207.50 | 17,371.54 | -64.7% |
| AGF — Amaç A | 11 / 54 | 50,815.00 | 19,613.58 | -61.4% |
| Model (`v1_agf`) — Amaç A | 10 / 54 | 50,516.25 | 16,829.40 | -66.7% |

### 3. Para (1 TL ganyan)

- **GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `0`

| Yöntem | Oynanan Koşu | Yatırılan (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Anlık AGF Favorisi | 295 | 295.00 | 224.65 | -23.8% |
| Model (`v1_agf`) | 295 | 295.00 | 210.30 | -28.7% |
| **Fark (Model − AGF)** | — | — | **-14.35** | **-4.9%** |

- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** `[-17.7%, +7.7%]`

## Model Sürümü: `v1_agf_late`

- **Model Sürümü:** `v1_agf_late`
- **Kayıt Tarih Aralığı:** `2026-11-15` … `2026-11-16`
- **Toplam Kayıtlı Tahmin:** `13` koşu (`145` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `13` koşu
- **Sonuçlanmış Geçerli Koşu:** `13`

### 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 30.8% | 1.8475 |
| Model (`v1_agf_late`) | 23.1% | 1.9119 |
| **Fark (Model − AGF)** | **-7.7%** | **+0.0644** |

- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** 1. tercih `[-23.1%, +0.0%]`, log-loss `[-0.0203, +0.1418]`
- **Model ≠ AGF Favorisi:** `1` koşu (AGF favorisi kazandı: `1`, Model favorisi kazandı: `0`)

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
| Anlık AGF Favorisi | 13 | 13.00 | 7.20 | -44.6% |
| Model (`v1_agf_late`) | 13 | 13.00 | 5.20 | -60.0% |
| **Fark (Model − AGF)** | — | — | **-2.00** | **-15.4%** |

- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** `[-46.2%, +0.0%]`

## Erken ve Geç Tahmin (aynı koşular)

- **Ortak Sonuçlanmış Geçerli Koşu:** `13`

| Yöntem | Koşu | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|---:|
| AGF (erken, `v1_agf`) | 13 | 30.8% | 1.8015 |
| Model (erken, `v1_agf`) | 13 | 30.8% | 1.8672 |
| AGF (geç, `v1_agf_late`) | 13 | 30.8% | 1.8475 |
| Model (geç, `v1_agf_late`) | 13 | 23.1% | 1.9119 |
| **Fark (Model_geç − AGF_geç)** | 13 | **-7.7%** | **+0.0644** |

- **Koşu-Eşli Bootstrap %95 GA (Model_geç − AGF_geç, 2000 tekrar):** 1. tercih `[-23.1%, +0.0%]`, log-loss `[-0.0203, +0.1418]`

> ROI kapanış öncesi oranlarla değil, kesinleşmiş ödemelerle hesaplanır; küçük örneklemde tek büyük ikramiye sonucu belirler.
