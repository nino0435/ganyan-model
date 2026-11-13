# Ganyan — İleri Test (Forward-Test) Raporu

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-13`
- **Toplam Kayıtlı Tahmin:** `285` koşu (`2900` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `248` koşu
- **AGF'si eksik/sıfır olduğu için dışlanan koşu:** `9`
- **Sonuçlanmış Geçerli Koşu:** `241`

## 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 33.2% | 1.9093 |
| Model (`v1_agf`) | 34.0% | 1.9087 |
| **Fark (Model − AGF)** | **+0.8%** | **-0.0006** |

## 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `45`
- **Sabit-k 6/6:** `5 / 45`
- **Model Amaç A 6/6:** `7 / 45`
