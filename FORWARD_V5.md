# Ganyan Model v5 / v6 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats mertebesindedir ve bu ölçekte bir farkın gürültüden ayrışması binlerce ileri-test koşusu gerektirir. Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `40`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `40` / `40` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması (`v5_sgr_all` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 40 | 1.8248 | 32.50% | 50.00% | 60.00% |
| `v5_sgr_all` | 40 | 1.7790 | 35.00% | 50.00% | 62.50% |
| `v6_e5` | 40 | 1.7601 | 35.00% | 47.50% | 65.00% |

### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v6_e5 − v5_sgr_all` | 40 | `-0.0189` | `[-0.0399, +0.0031]` |
| `v6_e5 − AGF` | 40 | `-0.0647` | `[-0.1224, -0.0117]` |
| `v5_sgr_all − AGF` | 40 | `-0.0458` | `[-0.1017, +0.0070]` |

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 45 | `2026-11-15`…`2026-11-19` | 90.2% (100.0% / 36.4%) | 95.7% (100.0% / 69.2%) | 44 | 1.7838 | 34.1% / 52.3% / 63.6% | `-0.0479` (`[-0.0985, +0.0006]`) |
| `v6_e5` | 41 | `2026-11-17`…`2026-11-19` | 89.2% (92.9% / 36.4%) | 95.4% (100.0% / 69.2%) | 40 | 1.7601 | 35.0% / 47.5% / 65.0% | `-0.0647` (`[-0.1224, -0.0117]`) |
