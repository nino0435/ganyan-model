# Ganyan Model v5 / v6 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats mertebesindedir ve bu ölçekte bir farkın gürültüden ayrışması binlerce ileri-test koşusu gerektirir. Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `70`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `70` / `70` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması (`v5_sgr_all` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 70 | 1.9275 | 32.86% | 42.86% | 61.43% |
| `v5_sgr_all` | 70 | 1.9325 | 32.86% | 47.14% | 61.43% |
| `v6_e5` | 70 | 1.9274 | 32.86% | 44.29% | 62.86% |

### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v6_e5 − v5_sgr_all` | 70 | `-0.0052` | `[-0.0223, +0.0117]` |
| `v6_e5 − AGF` | 70 | `-0.0001` | `[-0.0457, +0.0435]` |
| `v5_sgr_all − AGF` | 70 | `+0.0051` | `[-0.0384, +0.0487]` |

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 74 | `2026-11-15`…`2026-11-21` | 87.6% (100.0% / 0.0%) | 96.5% (100.0% / 69.2%) | 74 | 1.9271 | 32.4% / 48.6% / 62.2% | `+0.0011` (`[-0.0414, +0.0411]`) |
| `v6_e5` | 70 | `2026-11-17`…`2026-11-21` | 86.9% (96.4% / 0.0%) | 96.4% (100.0% / 69.2%) | 70 | 1.9274 | 32.9% / 44.3% / 62.9% | `-0.0001` (`[-0.0457, +0.0435]`) |
