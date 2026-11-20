# Ganyan Model v5 / v6 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats mertebesindedir ve bu ölçekte bir farkın gürültüden ayrışması binlerce ileri-test koşusu gerektirir. Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `41`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `41` / `41` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması (`v5_sgr_all` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 41 | 1.8255 | 31.71% | 48.78% | 60.98% |
| `v5_sgr_all` | 41 | 1.7887 | 34.15% | 48.78% | 60.98% |
| `v6_e5` | 41 | 1.7690 | 34.15% | 46.34% | 63.41% |

### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v6_e5 − v5_sgr_all` | 41 | `-0.0197` | `[-0.0405, +0.0016]` |
| `v6_e5 − AGF` | 41 | `-0.0564` | `[-0.1118, +0.0002]` |
| `v5_sgr_all − AGF` | 41 | `-0.0367` | `[-0.0915, +0.0168]` |

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 45 | `2026-11-15`…`2026-11-19` | 90.2% (100.0% / 36.4%) | 95.7% (100.0% / 69.2%) | 45 | 1.7926 | 33.3% / 51.1% / 62.2% | `-0.0396` (`[-0.0921, +0.0103]`) |
| `v6_e5` | 41 | `2026-11-17`…`2026-11-19` | 89.2% (92.9% / 36.4%) | 95.4% (100.0% / 69.2%) | 41 | 1.7690 | 34.1% / 46.3% / 63.4% | `-0.0564` (`[-0.1118, +0.0002]`) |
