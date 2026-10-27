# Ganyan — Hava ve Pist Durumu Özellikleri İleri-Yürüyen (Walk-Forward) Değerlendirme Raporu

**Karar (§0):** **GEÇMEDİ** — Kazanan log-loss farkı `ll(v2_agf_hava) − ll(v1_agf) = +0.00055` olup 2000 tekrarlı koşu-eşli bootstrap %95 güven aralığı (`-0.00154` … `+0.00255`) 0'ı kapsadığı / üst sınırı < 0 olmadığı için istatistiksel olarak anlamlı bir iyileşme sağlamamıştır.

> **Metodoloji Notları (§4.1, §8):**
> - **Pist durumu ön-ilan varsayımı (§4.1):** TJK geçmiş günlerin program ve sonuç HTML sayfalarında `<div class="conditions-race">` içinde pist durumu yer almaktadır; ancak yarış sabahı erken saatte (`06:40`) çekilen canlı gelecek program sayfasında pist durumu henüz boş olduğundan, pist durumunun bahis anından önce ilan edildiği **varsayım** olarak işaretlenmiştir.
> - **Open-Meteo lisans ve canlı kullanım (§3.3, §8):** Open-Meteo ücretsiz API'si ticari olmayan (araştırma) kullanım içindir; uygulamada ticari kullanım veya `v2_agf_hava`'nın günlük ileri teste (`forward_log.py`) paralel eklenmesi **kullanıcı kararıdır**. Bu çalışmada kâr (ROI) iddiası yoktur ve bütçeli kupon backtest'i çalıştırılmamıştır.

## 1. Aylık İleri-Yürüyen Karşılaştırma (`v1_agf` vs `v2_agf_hava`, 2025-07 … 2026-10)

| Ay | Koşu | Islak Koşu | `v1_agf` 1.Tercih | `v2_agf_hava` 1.Tercih | `v1_agf` Log-Loss | `v2_agf_hava` Log-Loss | Fark (`v2 − v1` LL) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025-07 | 591 | 7 | 34.18% | 33.67% | 1.7552 | 1.7638 | +0.0086 |
| 2025-08 | 603 | 7 | 30.02% | 31.84% | 1.8478 | 1.8371 | -0.0107 |
| 2025-09 | 568 | 73 | 30.81% | 32.57% | 1.8227 | 1.8166 | -0.0061 |
| 2025-10 | 589 | 268 | 33.62% | 33.11% | 1.8158 | 1.8164 | +0.0006 |
| 2025-11 | 531 | 131 | 34.09% | 33.33% | 1.8337 | 1.8434 | +0.0097 |
| 2025-12 | 474 | 126 | 36.50% | 36.50% | 1.7873 | 1.7852 | -0.0022 |
| 2026-01 | 457 | 240 | 36.76% | 36.32% | 1.7586 | 1.7585 | -0.0001 |
| 2026-02 | 420 | 226 | 39.52% | 39.76% | 1.6994 | 1.6946 | -0.0048 |
| 2026-03 | 464 | 153 | 37.50% | 38.15% | 1.7089 | 1.7157 | +0.0068 |
| 2026-04 | 502 | 149 | 35.26% | 35.86% | 1.7765 | 1.7770 | +0.0005 |
| 2026-05 | 555 | 138 | 32.61% | 33.15% | 1.8441 | 1.8471 | +0.0029 |
| 2026-06 | 529 | 22 | 34.22% | 33.08% | 1.8339 | 1.8354 | +0.0015 |
| 2026-07 | 550 | 32 | 32.73% | 33.27% | 1.8080 | 1.8123 | +0.0042 |
| 2026-08 | 561 | 16 | 32.80% | 31.73% | 1.8461 | 1.8487 | +0.0026 |
| 2026-09 | 508 | 81 | 33.86% | 32.68% | 1.8497 | 1.8485 | -0.0012 |
| 2026-10 | 474 | 199 | 30.80% | 31.86% | 1.8968 | 1.8927 | -0.0041 |

## 2. Toplam ve Alt Küme (Islak / Kuru) Sonuçları — Eşleştirilmiş Bootstrap (2000 Tekrar)

- **Islak Koşu Tanımı (§4.2):** `wet = (track_cond in {nemli, islak, agir, yumusak})` (bilinmiyorsa `rain_72h >= 5.0 mm`). Veritabanındaki toplam `12797` sonuçlanmış koşunun **`2625`** tanesi ıslak (`10172` kuru); 16 aylık değerlendirme dönemindeki `8376` koşunun **`1868`** tanesi ıslak (`6508` kuru) sayılmıştır.

| Küme | Koşu Sayısı | `v1_agf` Log-Loss | `v2_agf_hava` Log-Loss | LL Fark (`v2 − v1`) | LL %95 GA (Bootstrap) | `v1_agf` 1.Tercih | `v2_agf_hava` 1.Tercih | 1.Tercih Fark (%95 GA) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Tüm Koşular (Birincil Ölçüt)** | 8376 | 1.8078 | 1.8083 | `+0.00055` | `[-0.00154, +0.00255]` | 33.89% | 34.00% | `+0.11%` (`-0.35%`…`+0.54%`) |
| Islak Koşular (`wet == 1`) | 1868 | 1.7673 | 1.7655 | `-0.00177` | `[-0.00631, +0.00286]` | 36.13% | 36.62% | `+0.48%` (`-0.48%`…`+1.50%`) |
| Kuru Koşular (`wet == 0`) | 6508 | 1.8194 | 1.8206 | `+0.00122` | `[-0.00116, +0.00355]` | 33.25% | 33.25% | `+0.00%` (`-0.49%`…`+0.49%`) |

## 3. Özellik Önemi — Permutation Importance (Test Ayları Üzerinde)

Test aylarında her özelliğin koşular arasında rastgele karıştırılmasıyla (5 tekrar) kazananın log-loss değerinde oluşan ortalama artış (`Δ Log-Loss`, büyük pozitif = daha önemli) aşağıda sıralanmıştır (`79` toplam özellik içinde yeni hava/pist özelliklerinin genel sırası):

### 3.1 İlk 15 Genel Özellik

| Genel Sıra | Özellik | Yeni (Hava/Pist)? | Ortalama Δ Log-Loss |
|---:|---|---:|---:|
| 1 | `agf_share` | Hayır | `+0.74664` |
| 2 | `log_agf` | Hayır | `+0.00987` |
| 3 | `h_sf_m3_rel` | Hayır | `+0.00227` |
| 4 | `h_fpct_last` | Hayır | `+0.00173` |
| 5 | `son6_mean` | Hayır | `+0.00162` |
| 6 | `weight_rk` | Hayır | `+0.00154` |
| 7 | `h_sf_m3_rk` | Hayır | `+0.00136` |
| 8 | `gate_frac` | Hayır | `+0.00129` |
| 9 | `weight_rel` | Hayır | `+0.00127` |
| 10 | `h_wr` | Hayır | `+0.00098` |
| 11 | `hp_rel` | Hayır | `+0.00090` |
| 12 | `t_wr` | Hayır | `+0.00082` |
| 13 | `son6_last` | Hayır | `+0.00065` |
| 14 | `h_t3r` | Hayır | `+0.00061` |
| 15 | `t_n` | Hayır | `+0.00059` |

### 3.2 Yeni Eklenen Hava ve Pist Özelliklerinin Sıralaması

| Genel Sıra (`/ 79`) | Yeni Özellik | Ortalama Δ Log-Loss |
|---:|---|---:|
| 32 | `temp_post` | `+0.00007` |
| 35 | `rain_72h` | `+0.00006` |
| 37 | `wet` | `+0.00005` |
| 41 | `rain_24h` | `+0.00002` |
| 42 | `cim_normal` | `+0.00002` |
| 44 | `sire_wet_delta` | `+0.00001` |
| 45 | `wet_x_sire_wet_delta` | `+0.00001` |
| 46 | `cim_yumusak` | `+0.00000` |
| 47 | `kum_islak` | `+0.00000` |
| 48 | `kum_kuru` | `+0.00000` |
| 49 | `sentetik_islak` | `+0.00000` |
| 50 | `cim_nemli` | `+0.00000` |
| 51 | `cim_islak` | `+0.00000` |
| 52 | `sentetik_agir` | `+0.00000` |
| 53 | `cim_agir` | `+0.00000` |
| 54 | `sentetik_nemli` | `+0.00000` |
| 55 | `kum_agir` | `+0.00000` |
| 56 | `sentetik_yumusak` | `+0.00000` |
| 57 | `cim_kuru` | `+0.00000` |
| 58 | `kum_yumusak` | `+0.00000` |
| 59 | `sentetik_normal` | `+0.00000` |
| 60 | `sentetik_kuru` | `+0.00000` |
| 62 | `kum_nemli` | `-0.00001` |
| 65 | `horse_n_wet` | `-0.00003` |
| 68 | `kum_normal` | `-0.00003` |
| 71 | `wet_x_horse_wet_delta` | `-0.00004` |
| 76 | `wind_post` | `-0.00032` |
| 78 | `horse_wet_delta` | `-0.00039` |
