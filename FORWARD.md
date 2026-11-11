# Ganyan — İleri Test (Forward-Test) Raporu

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-11`
- **Toplam Kayıtlı Tahmin:** `252` koşu (`2589` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `224` koşu
- **Sonuçlanmış Geçerli Koşu:** `200`

## 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 33.0% | 1.9335 |
| Model (`v1_agf`) | 34.0% | 1.9267 |
| **Fark (Model − AGF)** | **+1.0%** | **-0.0068** |

## 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `38`
- **Sabit-k 6/6:** `4 / 38`
- **Model Amaç A 6/6:** `6 / 38`
