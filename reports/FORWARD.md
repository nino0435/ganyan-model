# Ganyan — İleri Test (Forward-Test) Raporu

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-27` … `2026-10-27`
- **Toplam Kayıtlı Tahmin:** `16` koşu (`188` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `16` koşu
- **Sonuçlanmış Geçerli Koşu:** `16`

## 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 37.5% | 1.8451 |
| Model (`v1_agf`) | 6.2% | 2.3470 |
| **Fark (Model − AGF)** | **-31.2%** | **+0.5018** |

## 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `4`
- **Sabit-k 6/6:** `0 / 4`
- **Model Amaç A 6/6:** `0 / 4`
