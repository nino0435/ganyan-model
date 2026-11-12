# Ganyan — İleri Test (Forward-Test) Raporu

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-12`
- **Toplam Kayıtlı Tahmin:** `270` koşu (`2756` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `233` koşu
- **AGF'si eksik/sıfır olduğu için dışlanan koşu:** `9`
- **Sonuçlanmış Geçerli Koşu:** `226`

## 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 33.2% | 1.9165 |
| Model (`v1_agf`) | 34.5% | 1.9130 |
| **Fark (Model − AGF)** | **+1.3%** | **-0.0035** |

## 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `43`
- **Sabit-k 6/6:** `4 / 43`
- **Model Amaç A 6/6:** `6 / 43`
