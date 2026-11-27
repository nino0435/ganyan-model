# Ganyan Model v5 / v6 / v7 / v8 / v9 / v10 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats, `v7_tcjp − v6_e5` farkı yaklaşık `-0.0019` nats, `v8_an − v7_tcjp` farkı yaklaşık `-0.0027` nats, `v9_kssb − v8_an` farkı yaklaşık `-0.0021` nats, `v10_hlb − v9_kssb` farkı yaklaşık `-0.0009` nats mertebesindedir ve bu ölçekte farkların gürültüden ayrışması binlerce ileri-test koşusu gerektirir (`v5_sgr_all` ve `v6_e5` yeni canlı üretimden emekli edilmiştir; tarihsel kayıtları arşivde korunmaktadır). Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Aktif Canlı Eşli Karşılaştırma Koşu Sayısı (`v7_tcjp` ∩ `v8_an` ∩ `v9_kssb` ∩ `v10_hlb` ∩ `AGF`):** `45`
- **V9 Dönemi Eşli Karşılaştırma Koşu Sayısı (`v6_e5` ∩ `v7_tcjp` ∩ `v8_an` ∩ `v9_kssb` ∩ `AGF`):** `8`
- **V8 Dönemi Eşli Karşılaştırma Koşu Sayısı (`v6_e5` ∩ `v7_tcjp` ∩ `v8_an` ∩ `AGF`):** `17`
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `86`
- **Dörtlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `v7_tcjp` ∩ `AGF`):** `0`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `148` / `148` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması

### Aktif Canlı Karşılaştırma (`v10_hlb` vs `v9_kssb` vs `v8_an` vs `v7_tcjp` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 45 | 1.8832 | 33.33% | 51.11% | 64.44% |
| `v7_tcjp` | 45 | 1.8897 | 33.33% | 55.56% | 71.11% |
| `v8_an` | 45 | 1.8796 | 35.56% | 55.56% | 71.11% |
| `v9_kssb` | 45 | 1.8764 | 42.22% | 57.78% | 71.11% |
| `v10_hlb` | 45 | 1.8863 | 33.33% | 55.56% | 71.11% |

#### Aktif Canlı Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v10_hlb − v9_kssb` | 45 | `+0.0099` | `[-0.0032, +0.0247]` |
| `v10_hlb − v8_an` | 45 | `+0.0067` | `[-0.0156, +0.0307]` |
| `v10_hlb − v7_tcjp` | 45 | `-0.0033` | `[-0.0290, +0.0259]` |
| `v10_hlb − AGF` | 45 | `+0.0031` | `[-0.0553, +0.0627]` |
| `v9_kssb − v8_an` | 45 | `-0.0032` | `[-0.0229, +0.0152]` |
| `v9_kssb − AGF` | 45 | `-0.0068` | `[-0.0635, +0.0495]` |
| `v8_an − v7_tcjp` | 45 | `-0.0100` | `[-0.0262, +0.0068]` |
| `v8_an − AGF` | 45 | `-0.0036` | `[-0.0543, +0.0467]` |
| `v7_tcjp − AGF` | 45 | `+0.0064` | `[-0.0441, +0.0572]` |

### V9 Dönemi Eşli Karşılaştırma (`v9_kssb` vs `v8_an` vs `v7_tcjp` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 8 | 2.2979 | 25.00% | 25.00% | 37.50% |
| `v6_e5` | 8 | 2.2404 | 37.50% | 37.50% | 62.50% |
| `v7_tcjp` | 8 | 2.2118 | 37.50% | 37.50% | 62.50% |
| `v8_an` | 8 | 2.2287 | 37.50% | 37.50% | 62.50% |
| `v9_kssb` | 8 | 2.2093 | 37.50% | 50.00% | 62.50% |

#### V9 Dönemi Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v9_kssb − v8_an` | 8 | `-0.0193` | `[-0.0607, +0.0333]` |
| `v9_kssb − v7_tcjp` | 8 | `-0.0025` | `[-0.0621, +0.0626]` |
| `v9_kssb − v6_e5` | 8 | `-0.0311` | `[-0.1279, +0.0767]` |
| `v9_kssb − AGF` | 8 | `-0.0886` | `[-0.2708, +0.1178]` |
| `v8_an − v7_tcjp` | 8 | `+0.0169` | `[-0.0193, +0.0638]` |
| `v8_an − AGF` | 8 | `-0.0693` | `[-0.2276, +0.0892]` |
| `v7_tcjp − v6_e5` | 8 | `-0.0286` | `[-0.1046, +0.0571]` |
| `v7_tcjp − AGF` | 8 | `-0.0861` | `[-0.2620, +0.0867]` |
| `v6_e5 − AGF` | 8 | `-0.0575` | `[-0.2068, +0.0966]` |

### V8 Dönemi Eşli Karşılaştırma (`v8_an` vs `v7_tcjp` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 17 | 2.0309 | 29.41% | 41.18% | 47.06% |
| `v6_e5` | 17 | 1.9308 | 35.29% | 52.94% | 64.71% |
| `v7_tcjp` | 17 | 1.9019 | 35.29% | 52.94% | 64.71% |
| `v8_an` | 17 | 1.9067 | 35.29% | 52.94% | 64.71% |

#### V8 Dönemi Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v8_an − v7_tcjp` | 17 | `+0.0048` | `[-0.0138, +0.0304]` |
| `v8_an − v6_e5` | 17 | `-0.0241` | `[-0.0638, +0.0220]` |
| `v8_an − AGF` | 17 | `-0.1242` | `[-0.2314, -0.0226]` |
| `v7_tcjp − v6_e5` | 17 | `-0.0289` | `[-0.0677, +0.0114]` |
| `v7_tcjp − AGF` | 17 | `-0.1289` | `[-0.2402, -0.0192]` |
| `v6_e5 − AGF` | 17 | `-0.1001` | `[-0.1957, -0.0014]` |

### Tarihsel Arşiv (`v5_sgr_all` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 86 | 1.9170 | 33.72% | 43.02% | 61.63% |
| `v5_sgr_all` | 86 | 1.9080 | 33.72% | 47.67% | 62.79% |
| `v6_e5` | 86 | 1.9026 | 33.72% | 46.51% | 63.95% |

#### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v6_e5 − v5_sgr_all` | 86 | `-0.0054` | `[-0.0202, +0.0096]` |
| `v6_e5 − AGF` | 86 | `-0.0145` | `[-0.0542, +0.0291]` |
| `v5_sgr_all − AGF` | 86 | `-0.0090` | `[-0.0491, +0.0329]` |

### V7 Eşli Karşılaştırma (`v7_tcjp` vs `v6_e5` vs `v5_sgr_all` vs `AGF`)

Ortak sonuçlanmış V7 koşu sayısı `0` (`v7_tcjp` sonuçlanmış: `62`) — dörtlü eşli karşılaştırma için **yeterli veri yok**.

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 90 | `2026-11-15`…`2026-11-22` | 86.4% (100.0% / 0.0%) | 92.8% (100.0% / 0.0%) | 90 | 1.9046 | 33.3% / 48.9% / 63.3% | `-0.0117` (`[-0.0504, +0.0287]`) |
| `v6_e5` | 103 | `2026-11-17`…`2026-11-23` | 86.7% (92.9% / 0.0%) | 92.8% (100.0% / 0.0%) | 103 | 1.9072 | 34.0% / 47.6% / 64.1% | `-0.0286` (`[-0.0688, +0.0110]`) |
| `v7_tcjp` | 62 | `2026-11-23`…`2026-11-26` | 87.8% (90.5% / 33.3%) | 95.9% (100.0% / 62.5%) | 62 | 1.8930 | 33.9% / 54.8% / 69.4% | `-0.0307` (`[-0.0781, +0.0197]`) |
| `v8_an` | 62 | `2026-11-23`…`2026-11-26` | 87.8% (90.5% / 33.3%) | 95.9% (100.0% / 62.5%) | 62 | 1.8870 | 35.5% / 54.8% / 69.4% | `-0.0367` (`[-0.0832, +0.0129]`) |
| `v9_kssb` | 53 | `2026-11-23`…`2026-11-26` | 86.9% (88.9% / 33.3%) | 96.5% (100.0% / 81.2%) | 53 | 1.9267 | 41.5% / 56.6% / 69.8% | `-0.0191` (`[-0.0776, +0.0381]`) |
| `v10_hlb` | 45 | `2026-11-24`…`2026-11-26` | 86.4% (88.9% / 33.3%) | 96.5% (100.0% / 81.2%) | 45 | 1.8863 | 33.3% / 55.6% / 71.1% | `+0.0031` (`[-0.0553, +0.0627]`) |

**Düşük kapsamlı (<%50) koşular** (genelde debut/az-koşmuş at kaynaklı; scraper arızası değil — bkz. `race_id`):

- `v5_sgr_all` s_cov min → `2026-11-21_Adana_1` (0%)
- `v5_sgr_all` g_cov min → `2026-11-22_İzmir_3` (0%)
- `v6_e5` s_cov min → `2026-11-21_Adana_1` (0%)
- `v6_e5` g_cov min → `2026-11-22_İzmir_3` (0%)
- `v7_tcjp` s_cov min → `2026-11-25_Elazığ_6` (33%)
- `v8_an` s_cov min → `2026-11-25_Elazığ_6` (33%)
- `v9_kssb` s_cov min → `2026-11-25_Elazığ_6` (33%)
- `v10_hlb` s_cov min → `2026-11-25_Elazığ_6` (33%)
