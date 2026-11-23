# Ganyan Model v5 / v6 / v7 / v8 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats, `v7_tcjp − v6_e5` farkı yaklaşık `-0.0019` nats, `v8_an − v7_tcjp` farkı yaklaşık `-0.0027` nats mertebesindedir ve bu ölçekte farkların gürültüden ayrışması binlerce ileri-test koşusu gerektirir (`v5_sgr_all` yeni canlı üretimden emekli edilmiştir; tarihsel kayıtları arşivde korunmaktadır). Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Aktif Canlı Eşli Karşılaştırma Koşu Sayısı (`v6_e5` ∩ `v7_tcjp` ∩ `v8_an` ∩ `AGF`):** `0`
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `86`
- **Dörtlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `v7_tcjp` ∩ `AGF`):** `0`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `86` / `86` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması

### Aktif Canlı Karşılaştırma (`v8_an` vs `v7_tcjp` vs `v6_e5` vs `AGF`)

Ortak sonuçlanmış aktif canlı koşu sayısı `0` (`v8_an` sonuçlanmış: `0`) — aktif üçlü eşli karşılaştırma için **yeterli veri yok**.

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

Ortak sonuçlanmış V7 koşu sayısı `0` (`v7_tcjp` sonuçlanmış: `0`) — dörtlü eşli karşılaştırma için **yeterli veri yok**.

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 90 | `2026-11-15`…`2026-11-22` | 86.4% (100.0% / 0.0%) | 92.8% (100.0% / 0.0%) | 90 | 1.9046 | 33.3% / 48.9% / 63.3% | `-0.0117` (`[-0.0504, +0.0287]`) |
| `v6_e5` | 86 | `2026-11-17`…`2026-11-22` | 85.8% (92.9% / 0.0%) | 92.5% (100.0% / 0.0%) | 86 | 1.9026 | 33.7% / 46.5% / 64.0% | `-0.0145` (`[-0.0542, +0.0291]`) |
| `v7_tcjp` | 0 | — | — | — | 0 | — | — | — |
| `v8_an` | 0 | — | — | — | 0 | — | — | — |
