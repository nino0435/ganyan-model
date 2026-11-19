# Ganyan Model v5 / v6 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats mertebesindedir ve bu ölçekte bir farkın gürültüden ayrışması binlerce ileri-test koşusu gerektirir. Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `/Users/berhantekdemir/.gemini/antigravity/brain/ac9a8917-cc80-44ea-b896-be9814e163de/scratch/actions_state_seed/forward_v5.db` (salt-okunur)
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `27`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `27` / `27` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması (`v5_sgr_all` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 27 | 1.8088 | 33.33% | 48.15% | 51.85% |
| `v5_sgr_all` | 27 | 1.7630 | 33.33% | 44.44% | 59.26% |
| `v6_e5` | 27 | 1.7402 | 33.33% | 40.74% | 59.26% |

### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v6_e5 − v5_sgr_all` | 27 | `-0.0228` | `[-0.0473, +0.0021]` |
| `v6_e5 − AGF` | 27 | `-0.0686` | `[-0.1418, +0.0019]` |
| `v5_sgr_all − AGF` | 27 | `-0.0458` | `[-0.1158, +0.0198]` |

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 34 | `2026-11-15`…`2026-11-19` | 89.6% (100.0% / 36.4%) | 95.3% (100.0% / 69.2%) | 31 | 1.7719 | 32.3% / 48.4% / 61.3% | `-0.0488` (`[-0.1130, +0.0072]`) |
| `v6_e5` | 30 | `2026-11-17`…`2026-11-19` | 88.2% (96.4% / 36.4%) | 95.0% (100.0% / 69.2%) | 27 | 1.7402 | 33.3% / 40.7% / 59.3% | `-0.0686` (`[-0.1418, +0.0019]`) |
