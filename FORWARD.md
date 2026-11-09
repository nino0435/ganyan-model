# Ganyan — İleri Test (Forward-Test) Raporu

- **Model Sürümü:** `v1_agf`
- **Kayıt Tarih Aralığı:** `2026-10-28` … `2026-11-09`
- **Toplam Kayıtlı Tahmin:** `218` koşu (`2252` at)
- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `190` koşu
- **Sonuçlanmış Geçerli Koşu:** `183`

## 1. Koşu Bazında Performans

| Yöntem | 1. Tercih Kazandı | Log-Loss |
|---|---:|---:|
| Anlık AGF Favorisi | 33.3% | 1.9300 |
| Model (`v1_agf`) | 35.0% | 1.9227 |
| **Fark (Model − AGF)** | **+1.6%** | **-0.0074** |

## 2. Altılı Karşılaştırması (Bütçe 1000 TL)

- **Değerlendirilen Altılı:** `35`
- **Sabit-k 6/6:** `4 / 35`
- **Model Amaç A 6/6:** `6 / 35`
