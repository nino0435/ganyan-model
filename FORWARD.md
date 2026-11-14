# Ganyan — İleri Test (Forward-Test) Raporu

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-14`
- **Toplam Kayıtlı Tahmin:** `308` koşu (`3139` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `271` koşu
- **AGF'si eksik/sıfır olduğu için dışlanan koşu:** `9`
- **Sonuçlanmış Geçerli Koşu:** `264`

## 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 35.6% | 1.8785 |
| Model (`v1_agf`) | 34.1% | 1.8818 |
| **Fark (Model − AGF)** | **-1.5%** | **+0.0032** |

- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** 1. tercih `[-5.7%, +2.7%]`, log-loss `[-0.0148, +0.0219]`
- **Model ≠ AGF Favorisi:** `44` koşu (AGF favorisi kazandı: `17`, Model favorisi kazandı: `13`)

## 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `49`
- **Sabit-k 6/6:** `9 / 49`
- **AGF — Amaç A 6/6:** `11 / 49`
- **Model Amaç A 6/6:** `10 / 49`

| Yöntem | 6/6 | Maliyet (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Sabit-k (AGF) | 9 / 49 | 44,651.25 | 17,371.54 | -61.1% |
| AGF — Amaç A | 11 / 49 | 46,151.25 | 19,613.58 | -57.5% |
| Model (`v1_agf`) — Amaç A | 10 / 49 | 45,896.25 | 16,829.40 | -63.3% |

## 3. Para (1 TL ganyan)

- **GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `0`

| Yöntem | Oynanan Koşu | Yatırılan (TL) | Dönüş (TL) | ROI |
|---|---:|---:|---:|---:|
| Anlık AGF Favorisi | 264 | 264.00 | 214.65 | -18.7% |
| Model (`v1_agf`) | 264 | 264.00 | 198.90 | -24.7% |
| **Fark (Model − AGF)** | — | — | **-15.75** | **-6.0%** |

- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** `[-20.4%, +7.7%]`

> ROI kapanış öncesi oranlarla değil, kesinleşmiş ödemelerle hesaplanır; küçük örneklemde tek büyük ikramiye sonucu belirler.
