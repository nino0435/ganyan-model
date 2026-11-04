# Ganyan — İleri Test (Forward-Test) Raporu

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-03`
- **Toplam Kayıtlı Tahmin:** `110` koşu (`1143` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `109` koşu
- **Sonuçlanmış Geçerli Koşu:** `102`

## 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 36.3% | 1.8165 |
| Model (`v1_agf`) | 34.3% | 1.8021 |
| **Fark (Model − AGF)** | **-2.0%** | **-0.0144** |

## 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `20`
- **Sabit-k 6/6:** `2 / 20`
- **Model Amaç A 6/6:** `4 / 20`
