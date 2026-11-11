# Ganyan — İleri Test (Forward-Test) Raporu

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-11`
- **Toplam Kayıtlı Tahmin:** `252` koşu (`2589` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `215` koşu
- **AGF'si eksik/sıfır olduğu için dışlanan koşu:** `9`
- **Sonuçlanmış Geçerli Koşu:** `208`

## 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 32.2% | 1.9212 |
| Model (`v1_agf`) | 34.1% | 1.9179 |
| **Fark (Model − AGF)** | **+1.9%** | **-0.0033** |

## 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `39`
- **Sabit-k 6/6:** `4 / 39`
- **Model Amaç A 6/6:** `6 / 39`
