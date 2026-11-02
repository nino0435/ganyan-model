# Ganyan — Ahır Arkadaşı (Aynı Sahip/Antrenör) Özellikleri Walk-Forward Değerlendirmesi

**Karar:** **GEÇMEDİ** — `ll(v4_agf_ahir) − ll(v1_agf) = -0.00074`, 2000 tekrarlı koşu-eşli bootstrap %95 GA `[-0.00252, +0.00107]` (geçme koşulu: üst sınır < 0, `v2_agf_hava` kapısıyla aynı).

Eklenen özellikler: `own_mates`, `own_mate_agf`, `own_is_top`, `trn_mates`, `trn_mate_agf`, `trn_is_top`.
Genç-at kümesi: koşudaki atların en az %30'u `h_n <= 3` olan koşular.

| Küme | Koşu | `v1_agf` LL | `v4_agf_ahir` LL | LL Fark | LL %95 GA | `v1` 1.Tercih | `v4_agf_ahir` 1.Tercih | 1.Tercih Fark (%95 GA) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tüm koşular | 8468 | 1.8076 | 1.8069 | `-0.00074` | `[-0.00252, +0.00107]` | 33.89% | 33.89% | `+0.00%` (`-0.38%`…`+0.40%`) |
| Genç at ağırlıklı | 2279 | 1.7544 | 1.7514 | `-0.00297` | `[-0.00628, +0.00035]` | 35.81% | 36.11% | `+0.31%` (`-0.44%`…`+1.05%`) |
| Diğer | 6189 | 1.8272 | 1.8273 | `+0.00008` | `[-0.00206, +0.00218]` | 33.19% | 33.07% | `-0.11%` (`-0.55%`…`+0.37%`) |

> Kapanış AGF kullanılır; canlı AGF daha az bilgi içerir. Damsire (anne babası) veride yok.
