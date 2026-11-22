# Ganyan Model v5 / v6 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats mertebesindedir ve bu ölçekte bir farkın gürültüden ayrışması binlerce ileri-test koşusu gerektirir. Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `85`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `85` / `85` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması (`v5_sgr_all` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 85 | 1.9149 | 34.12% | 43.53% | 61.18% |
| `v5_sgr_all` | 85 | 1.9073 | 34.12% | 48.24% | 62.35% |
| `v6_e5` | 85 | 1.9028 | 34.12% | 45.88% | 63.53% |

### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v6_e5 − v5_sgr_all` | 85 | `-0.0045` | `[-0.0194, +0.0115]` |
| `v6_e5 − AGF` | 85 | `-0.0121` | `[-0.0550, +0.0318]` |
| `v5_sgr_all − AGF` | 85 | `-0.0076` | `[-0.0487, +0.0348]` |

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 90 | `2026-11-15`…`2026-11-22` | 86.4% (100.0% / 0.0%) | 92.8% (100.0% / 0.0%) | 89 | 1.9040 | 33.7% / 49.4% / 62.9% | `-0.0103` (`[-0.0497, +0.0323]`) |
| `v6_e5` | 86 | `2026-11-17`…`2026-11-22` | 85.8% (92.9% / 0.0%) | 92.5% (100.0% / 0.0%) | 85 | 1.9028 | 34.1% / 45.9% / 63.5% | `-0.0121` (`[-0.0550, +0.0318]`) |
