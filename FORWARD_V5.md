# Ganyan Model v5 / v6 — İleri Test (Forward) Karşılaştırma Raporu

> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats mertebesindedir ve bu ölçekte bir farkın gürültüden ayrışması binlerce ileri-test koşusu gerektirir. Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.

## 1. Veri ve AGF Kaynağı Özeti

- **Ana Veritabanı:** `data/ganyan.db` (salt-okunur)
- **İleri-Test Tahmin Veritabanı:** `state/forward_v5.db` (salt-okunur)
- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `69`
- **Kullanılan AGF Kaynağı:** `agf_snapshots` (tahmin anındaki AGF — `69` / `69` koşunun tamamı)

## 2. Eşli Performans Karşılaştırması (`v5_sgr_all` vs `v6_e5` vs `AGF`)

| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |
|---|---:|---:|---:|---:|---:|
| `AGF` | 69 | 1.9169 | 33.33% | 43.48% | 62.32% |
| `v5_sgr_all` | 69 | 1.9253 | 33.33% | 47.83% | 62.32% |
| `v6_e5` | 69 | 1.9195 | 33.33% | 44.93% | 63.77% |

### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)

| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |
|---|---:|---:|---|
| `v6_e5 − v5_sgr_all` | 69 | `-0.0058` | `[-0.0233, +0.0115]` |
| `v6_e5 − AGF` | 69 | `+0.0026` | `[-0.0436, +0.0481]` |
| `v5_sgr_all − AGF` | 69 | `+0.0084` | `[-0.0350, +0.0511]` |

## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti

| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |
|---|---:|---|---|---|---:|---:|---|---|
| `v5_sgr_all` | 74 | `2026-11-15`…`2026-11-21` | 87.6% (100.0% / 0.0%) | 96.5% (100.0% / 69.2%) | 73 | 1.9202 | 32.9% / 49.3% / 63.0% | `+0.0042` (`[-0.0371, +0.0451]`) |
| `v6_e5` | 70 | `2026-11-17`…`2026-11-21` | 86.9% (96.4% / 0.0%) | 96.4% (100.0% / 69.2%) | 69 | 1.9195 | 33.3% / 44.9% / 63.8% | `+0.0026` (`[-0.0436, +0.0481]`) |
