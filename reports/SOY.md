# Ganyan — Soy (Baba/Anne) Özellikleri Walk-Forward Değerlendirmesi

**Karar:** **GEÇMEDİ** — `ll(v3_agf_soy) − ll(v1_agf) = -0.00015`, 2000 tekrarlı koşu-eşli bootstrap %95 GA `[-0.00235, +0.00239]` (geçme koşulu: üst sınır < 0, `v2_agf_hava` kapısıyla aynı).

Eklenen özellikler: `sire_n`, `sire_wr`, `sire_fpct`, `sire_surf_fpct`, `sire_dist_fpct`, `dam_n`, `dam_fpct` (yalnız D gününden önceki yavru sonuçları, büzülmeli).
Genç-at kümesi: koşudaki atların en az %30'u `h_n <= 3` olan koşular.

| Küme | Koşu | `v1_agf` LL | `v3_agf_soy` LL | LL Fark | LL %95 GA | `v1` 1.Tercih | `v3` 1.Tercih | 1.Tercih Fark (%95 GA) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tüm koşular | 8468 | 1.8076 | 1.8075 | `-0.00015` | `[-0.00235, +0.00239]` | 33.89% | 33.67% | `-0.22%` (`-0.67%`…`+0.22%`) |
| Genç at ağırlıklı | 2279 | 1.7544 | 1.7554 | `+0.00096` | `[-0.00314, +0.00521]` | 35.81% | 35.54% | `-0.26%` (`-1.10%`…`+0.57%`) |
| Diğer | 6189 | 1.8272 | 1.8266 | `-0.00055` | `[-0.00320, +0.00213]` | 33.19% | 32.98% | `-0.21%` (`-0.78%`…`+0.37%`) |

> Kapanış AGF kullanılır; canlı AGF daha az bilgi içerir. Damsire (anne babası) veride yok, eklenmedi.
