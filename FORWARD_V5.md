# Ganyan Model v5 / v6 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats mertebesindedir ve bu ölçekte bir farkın gürültüden ayrışması binlerce ileri-test koşusu gerektirir. Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `52`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `52` / `52` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması (`v5_sgr_all` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 52 | 1.9167 | 30.77% | 44.23% | 63.46% |
| `v5_sgr_all` | 52 | 1.9111 | 32.69% | 48.08% | 61.54% |
| `v6_e5` | 52 | 1.9002 | 32.69% | 44.23% | 63.46% |

### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v6_e5 − v5_sgr_all` | 52 | `-0.0110` | `[-0.0300, +0.0083]` |
| `v6_e5 − AGF` | 52 | `-0.0166` | `[-0.0713, +0.0371]` |
| `v5_sgr_all − AGF` | 52 | `-0.0056` | `[-0.0599, +0.0469]` |

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 57 | `2026-11-15`…`2026-11-20` | 90.7% (100.0% / 36.4%) | 95.9% (100.0% / 69.2%) | 56 | 1.9055 | 32.1% / 50.0% / 62.5% | `-0.0101` (`[-0.0612, +0.0404]`) |
| `v6_e5` | 53 | `2026-11-17`…`2026-11-20` | 90.0% (100.0% / 36.4%) | 95.8% (100.0% / 69.2%) | 52 | 1.9002 | 32.7% / 44.2% / 63.5% | `-0.0166` (`[-0.0713, +0.0371]`) |
