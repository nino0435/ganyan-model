# Ganyan Model v5 / v6 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats mertebesindedir ve bu ölçekte bir farkın gürültüden ayrışması binlerce ileri-test koşusu gerektirir. Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `53`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `53` / `53` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması (`v5_sgr_all` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 53 | 1.9289 | 30.19% | 43.40% | 62.26% |
| `v5_sgr_all` | 53 | 1.9255 | 32.08% | 47.17% | 60.38% |
| `v6_e5` | 53 | 1.9156 | 32.08% | 43.40% | 62.26% |

### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v6_e5 − v5_sgr_all` | 53 | `-0.0099` | `[-0.0298, +0.0097]` |
| `v6_e5 − AGF` | 53 | `-0.0133` | `[-0.0681, +0.0422]` |
| `v5_sgr_all − AGF` | 53 | `-0.0034` | `[-0.0541, +0.0518]` |

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 57 | `2026-11-15`…`2026-11-20` | 90.7% (100.0% / 36.4%) | 95.9% (100.0% / 69.2%) | 57 | 1.9190 | 31.6% / 49.1% / 61.4% | `-0.0080` (`[-0.0591, +0.0409]`) |
| `v6_e5` | 53 | `2026-11-17`…`2026-11-20` | 90.0% (100.0% / 36.4%) | 95.8% (100.0% / 69.2%) | 53 | 1.9156 | 32.1% / 43.4% / 62.3% | `-0.0133` (`[-0.0681, +0.0422]`) |
