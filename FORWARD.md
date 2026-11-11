# Ganyan — İleri Test (Forward-Test) Raporu

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-10`
- **Toplam Kayıtlı Tahmin:** `227` koşu (`2338` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `199` koşu
- **Sonuçlanmış Geçerli Koşu:** `192`

## 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 32.8% | 1.9341 |
| Model (`v1_agf`) | 34.4% | 1.9259 |
| **Fark (Model − AGF)** | **+1.6%** | **-0.0083** |

## 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `36`
- **Sabit-k 6/6:** `4 / 36`
- **Model Amaç A 6/6:** `6 / 36`
