# Ganyan Model v5 / v6 / v7 / v8 / v9 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats, `v7_tcjp − v6_e5` farkı yaklaşık `-0.0019` nats, `v8_an − v7_tcjp` farkı yaklaşık `-0.0027` nats, `v9_kssb − v8_an` farkı yaklaşık `-0.0021` nats mertebesindedir ve bu ölçekte farkların gürültüden ayrışması binlerce ileri-test koşusu gerektirir (`v5_sgr_all` yeni canlı üretimden emekli edilmiştir; tarihsel kayıtları arşivde korunmaktadır). Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Aktif Canlı Eşli Karşılaştırma Koşu Sayısı (`v6_e5` ∩ `v7_tcjp` ∩ `v8_an` ∩ `v9_kssb` ∩ `AGF`):** `7`
- **V8 Dönemi Eşli Karşılaştırma Koşu Sayısı (`v6_e5` ∩ `v7_tcjp` ∩ `v8_an` ∩ `AGF`):** `16`
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `86`
- **Dörtlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `v7_tcjp` ∩ `AGF`):** `0`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `102` / `102` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması

### Aktif Canlı Karşılaştırma (`v9_kssb` vs `v8_an` vs `v7_tcjp` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 7 | 2.4096 | 14.29% | 14.29% | 28.57% |
| `v6_e5` | 7 | 2.3131 | 28.57% | 28.57% | 57.14% |
| `v7_tcjp` | 7 | 2.2936 | 28.57% | 28.57% | 57.14% |
| `v8_an` | 7 | 2.3172 | 28.57% | 28.57% | 57.14% |
| `v9_kssb` | 7 | 2.2951 | 28.57% | 42.86% | 57.14% |

#### Aktif Canlı Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v9_kssb − v8_an` | 7 | `-0.0221` | `[-0.0675, +0.0375]` |
| `v9_kssb − v7_tcjp` | 7 | `+0.0015` | `[-0.0691, +0.0762]` |
| `v9_kssb − v6_e5` | 7 | `-0.0180` | `[-0.1280, +0.1000]` |
| `v9_kssb − AGF` | 7 | `-0.1145` | `[-0.3084, +0.1210]` |
| `v8_an − v7_tcjp` | 7 | `+0.0237` | `[-0.0178, +0.0769]` |
| `v8_an − AGF` | 7 | `-0.0924` | `[-0.2489, +0.0903]` |
| `v7_tcjp − v6_e5` | 7 | `-0.0196` | `[-0.1042, +0.0764]` |
| `v7_tcjp − AGF` | 7 | `-0.1161` | `[-0.2943, +0.0846]` |
| `v6_e5 − AGF` | 7 | `-0.0965` | `[-0.2502, +0.0763]` |

### V8 Dönemi Eşli Karşılaştırma (`v8_an` vs `v7_tcjp` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 16 | 2.0631 | 25.00% | 37.50% | 43.75% |
| `v6_e5` | 16 | 1.9433 | 31.25% | 50.00% | 62.50% |
| `v7_tcjp` | 16 | 1.9183 | 31.25% | 50.00% | 62.50% |
| `v8_an` | 16 | 1.9253 | 31.25% | 50.00% | 62.50% |

#### V8 Dönemi Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v8_an − v7_tcjp` | 16 | `+0.0070` | `[-0.0130, +0.0336]` |
| `v8_an − v6_e5` | 16 | `-0.0179` | `[-0.0591, +0.0304]` |
| `v8_an − AGF` | 16 | `-0.1377` | `[-0.2450, -0.0285]` |
| `v7_tcjp − v6_e5` | 16 | `-0.0249` | `[-0.0666, +0.0198]` |
| `v7_tcjp − AGF` | 16 | `-0.1447` | `[-0.2593, -0.0270]` |
| `v6_e5 − AGF` | 16 | `-0.1198` | `[-0.2153, -0.0201]` |

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

Ortak sonuçlanmış V7 koşu sayısı `0` (`v7_tcjp` sonuçlanmış: `16`) — dörtlü eşli karşılaştırma için **yeterli veri yok**.

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 90 | `2026-11-15`…`2026-11-22` | 86.4% (100.0% / 0.0%) | 92.8% (100.0% / 0.0%) | 90 | 1.9046 | 33.3% / 48.9% / 63.3% | `-0.0117` (`[-0.0504, +0.0287]`) |
| `v6_e5` | 103 | `2026-11-17`…`2026-11-23` | 86.7% (92.9% / 0.0%) | 92.8% (100.0% / 0.0%) | 102 | 1.9090 | 33.3% / 47.1% / 63.7% | `-0.0310` (`[-0.0706, +0.0076]`) |
| `v7_tcjp` | 17 | `2026-11-23`…`2026-11-23` | 91.5% (92.3% / 71.4%) | 94.3% (100.0% / 62.5%) | 16 | 1.9183 | 31.2% / 50.0% / 62.5% | `-0.1447` (`[-0.2593, -0.0270]`) |
| `v8_an` | 17 | `2026-11-23`…`2026-11-23` | 91.5% (92.3% / 71.4%) | 94.3% (100.0% / 62.5%) | 16 | 1.9253 | 31.2% / 50.0% / 62.5% | `-0.1377` (`[-0.2450, -0.0285]`) |
| `v9_kssb` | 8 | `2026-11-23`…`2026-11-23` | 89.6% (89.9% / 76.9%) | 96.5% (100.0% / 83.3%) | 7 | 2.2951 | 28.6% / 42.9% / 57.1% | `-0.1145` (`[-0.3084, +0.1210]`) |
