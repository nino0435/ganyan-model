# Model v8 — Prime Dönem ve Ahır İlişki Ağı Özellik Bulguları ve Doğrulama Kapısı (23.11.2026)

Ham rapor: `reports/V8.md`. Koşu günlüğü: `data/v8_run.log`. Özellik modülü: `ganyan/features_v8.py`. Deney betiği: `scripts/run_v8_experiments.py`.

---

## 1. Sonuç Özeti

**Evet, sabit doğrulama kapısını açık ara geçen ve yeni canlı şampiyonumuz `V7_CONFIG` (`V7_TCJP_CAL`)'yi geride bırakan bir V8 adayı bulundu: `V8_SEL_CAL` (`100` V7 özelliği + Paket `A` [At Prime/Zirve] `10` öz. + Paket `N` [Ahır Ağı & Uyanış] `12` öz. = `122` özellik, 5 tohum + ileri-yürüyen sıcaklık kalibrasyonu).**

- Salt-okunur `data/ganyan.db` (`2005-01-01`…`2026-11-22`, `111.126` sonuçlanmış koşu, `1.138.799` koşucu) üzerinde halihazırda her gün çekilen TJK verisiyle oluşturulan `3` yeni özellik paketi (`A`: At prime/zirve/yıpranma, `K`: Jokey prime/kıdem/çoklu pencere, `N`: Ahır ağı/aile ekürisi/uykudan uyanış) sınandı; **Paket `A` ve Paket `N` büyük iyileşme getirirken, Paket `K` ekstra fayda sağlamadı ve otomatik eleme kuralıyla (`V8_SEL`) dışarıda bırakıldı.**
- **Resmi Aşama B Doğrulama Kapısı (`2022–2025`, `24.515` koşu):**
  - **`V8_SEL_CAL` (`V7 + A + N`, `122` öz.):** `LL = 1,7599`, **`ΔLL vs V7_BASE = −0,0027` (`%95 GA −0,0036…−0,0018`, `4/4` negatif yıl)**, **`ΔLL vs AGF = −0,0299` (`%95 GA −0,0324…−0,0275`)**, 1. Tercih `%35,21` (`V7_BASE` `%35,07`, `Saf AGF` `%34,28`) → **KAPIYI GEÇTİ (KAZANAN)**.
  - `V8_AKN_CAL` (`V7 + A + K + N`, `129` öz.): `LL = 1,7600`, `ΔLL vs V7_BASE = −0,0027` (`%95 GA −0,0036…−0,0018`, `4/4` yıl) → kapıyı geçti ancak gereksiz `K` sütunları olmadan `V8_SEL_CAL` aynı/daha iyi sonucu verdi.
- **2026 Bilgi Kümesi (`5.483` koşu — *kilit v5'te tüketildi, temiz test DEĞİL*):**
  - `V8_SEL_CAL` `LL = 1,7852` vs `V7_BASE` `1,7881` (**`ΔLL = −0,0028`**, `%95 GA −0,0046…−0,0011`, `ΔLL vs AGF = −0,0288`), İlk-3 `%69,82` (vs `V7_BASE` `%69,72`, `AGF` `%67,85`).
  - `V8_SEL_CAL`, **`2018–2026` arasındaki son `9` yılın `9`'unda da kesintisiz biçimde `V7_BASE`'i geçmiştir** (`2017–2026` arasında `10` yılın `9`'u).

> **Kapsam Notu:** Bu çalışmada yalnızca araştırma, sızıntı/birim testleri ve geriye dönük doğrulama yapılmıştır; canlıdaki `scripts/forward_v5.py` ve `.github/workflows/ganyan-v6-canli.yml` dosyalarına dokunulmamıştır.

---

## 2. Veri ve Özellik Kapsamı (`data/ganyan.db`, `2017+` Değerlendirme Kümesi)

- **Paket `A` (`10` özellik — Atın Prime Dönemi, Zirveden Düşüşü ve Ara Dönüşü):**
  - `hp_drop_from_peak` / `hp_peak_ratio` `%82,7` dolu; `days_since_peak_sf` ve `starts_since_peak_sf` `%94,8` dolu; `sf_trend_3v3` / `fpct_trend_3v3` `%81,4–%81,5` dolu; `h_starts_90d` `%100,0` dolu; `h_layoff_run_no` `%94,9` dolu (yıllık `%11,1–%12,5` aktif ara dönüşü sinyali; pandemi yılı `2020`'de `%20,7`).
- **Paket `K` (`7` özellik — Jokey Prime Dönemi, Kıdem ve Çoklu Pencere Formu):**
  - Tüm sütunlar `%100,0` dolu; `j_is_ap` oranı `%28,7`.
- **Paket `N` (`12` özellik — Ahır İlişki Ağı, Ortaklıklar ve Uykudan Uyanış):**
  - `own_mates_cnt` (`%5,1` sıfır-dışı resmi eküri), `trn_mates_cnt` (`%23,9` aynı antrenörlü çoklu at), `fam_hidden_ekuri` (`%2,1` farklı sahip ama aynı soyadı + aynı antrenörlü gizli aile bağı), `tj_n` (`%89,9` önceden birlikte koşmuş antrenör–jokey ikilisi), `agf_surge_ratio` (`%81,0` dolu), `sleep_wakeup_flag` (`%0,7` uykudan ani uyanış).

---

## 3. Deney Sonuçları

### 3.1 Aşama A — Paket Taraması (`2017–2021`, `24.843` Koşu, 1-Tohum `seed=0`)

`V8_SEL` seçimi yalnız bu tablodaki `ΔLL < −0,0002` kuralıyla yapılmıştır → seçilen paketler: **`A`, `N`**.

| Varyant | Paketler | Log-Loss | ΔLL vs `V7_1s` (%95 GA) | Neg. Yıl (/5) | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---|---:|---:|---:|---:|
| `B0` | Saf AGF | 1,8578 | `+0,0229` (`+0,0200`…`+0,0257`) | 0/5 | 32,61% | 52,27% | 66,36% |
| `V7_1s` | Taban (100 öz.) | 1,8349 | — | — | 33,41% | 53,33% | 67,16% |
| **`V8_SEL`** | `A+N` (122 öz.) | **1,8332** | **`−0,0017`** (`−0,0029`…`−0,0004`) | 3/5 | 33,49% | 53,43% | **67,48%** |
| `V8_N` | `N` (Ahır Ağı/Uyanış) | 1,8335 | `−0,0014` (`−0,0024`…`−0,0004`) | 3/5 | **33,58%** | **53,60%** | 67,42% |
| `V8_AKN` | `A+K+N` (129 öz.) | 1,8337 | `−0,0012` (`−0,0025`…`+0,0001`) | 3/5 | 33,49% | 53,40% | 67,42% |
| `V8_A` | `A` (At Prime/Zirve) | 1,8338 | `−0,0011` (`−0,0022`…`−0,0001`) | **4/5** | 33,35% | 53,18% | 67,20% |
| `V8_K` | `K` (Jokey Prime) | 1,8349 | `+0,0000` (`−0,0007`…`+0,0008`) | 3/5 | 33,46% | 53,33% | 67,32% |

### 3.2 Aşama B Tanısal Karşılaştırma (`2022–2025`, `24.515` Koşu, 1-Tohum `seed=0`)

| Varyant | Paketler | Log-Loss | ΔLL vs `V7_1s` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---|---:|---:|---:|---:|
| `B0` | Saf AGF | 1,7898 | `+0,0265` (`+0,0242`…`+0,0288`) | 0/4 | 34,28% | 54,97% | 69,04% |
| `V7_1s` | Taban (100 öz.) | 1,7634 | — | — | 35,12% | 56,26% | 70,10% |
| **`V8_SEL`** | `A+N` | **1,7608** | **`−0,0025`** (`−0,0035`…`−0,0015`) | **4/4** | **35,30%** | 56,21% | **70,27%** |
| `V8_AKN` | `A+K+N` | 1,7610 | `−0,0023` (`−0,0033`…`−0,0013`) | 4/4 | 35,24% | 56,14% | 70,19% |
| `V8_A` | `A` | 1,7616 | `−0,0017` (`−0,0025`…`−0,0009`) | 4/4 | 35,24% | 56,14% | 70,19% |
| `V8_N` | `N` | 1,7621 | `−0,0012` (`−0,0020`…`−0,0004`) | 4/4 | 35,17% | 56,23% | 70,18% |
| `V8_K` | `K` | 1,7635 | `+0,0001` (`−0,0004`…`+0,0006`) | 2/4 | 35,13% | **56,28%** | 70,12% |

### 3.3 Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Sıcaklık Kalibrasyonu)

| Varyant | Koşu | Log-Loss | ΔLL vs `V7_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı |
|---|---:|---:|---|---|---:|---:|---:|---:|---|
| `B0` | 24.515 | 1,7898 | `+0,0272` (`+0,0249`…`+0,0295`) | — | 0/4 | 34,28% | 54,97% | 69,04% | Referans |
| `V7_BASE` | 24.515 | 1,7626 | — | `−0,0272` (`−0,0295`…`−0,0249`) | 0/4 | 35,07% | 56,26% | 70,09% | Taban |
| **`V8_SEL_CAL`** | **24.515** | **1,7599** | **`−0,0027` (`−0,0036`…`−0,0018`)** | **`−0,0299` (`−0,0324`…`−0,0275`)** | **4/4** | 35,21% | **56,28%** | 70,10% | **KAZANAN** |
| `V8_AKN_CAL` | 24.515 | 1,7600 | `−0,0027` (`−0,0036`…`−0,0018`) | `−0,0299` (`−0,0324`…`−0,0275`) | 4/4 | **35,31%** | 56,22% | **70,15%** | GEÇTİ |

`V8_SEL_CAL` yıllık `ΔLL` kırılımı (`vs V7_BASE`, 5-tohum + sıcaklık kalibrasyonu):
- **2017:** `+0,0011` | **2018:** `−0,0045` | **2019:** `−0,0035` | **2020:** `−0,0018` | **2021:** `−0,0007`
- **2022:** `−0,0032` (`−0,0052`…`−0,0011`) | **2023:** `−0,0035` (`−0,0054`…`−0,0016`) | **2024:** `−0,0023` (`−0,0043`…`−0,0004`) | **2025:** `−0,0020` (`−0,0036`…`−0,0002`)
- **2026 (Bilgi, `5.483` koşu):** `−0,0028` (`−0,0046`…`−0,0011`), İlk-3 `%69,82` (vs V7 `%69,72`, AGF `%67,85`).

---

## 4. Hangi Fikir Nasıl Çalıştı?

1. **Paket `A` (At Prime/Zirve/Yıpranma) ve Paket `N` (Ahır İlişki Ağı/Uyanış) birlikte mükemmel tamamlayıcı etki üretti:**
   - İkisinin birleşimi (`V8_SEL_CAL`), V7 üzerine `−0,0027` nats iyileşme koydu (`V6→V7` kazancı `−0,0019` idi — yani **V8 sıçraması V7 sıçramasından bile büyüktür**).
   - AGF'ye göre toplam kazanç **`−0,0299` nats** (`−0,03`'e dayandı) ve son `9` yılın `9`'unda (`2018–2026`) V7'nin üzerinde kaldı.
2. **Paket `K` (Jokey Prime/Kıdem) neden elendi?**
   - Jokeyin güncel 30 günlük sıcaklığı, genel kazanma oranı, `elo_j` ve `hj_*` uyumu V6+V7'de zaten mevcut olduğundan jokey kariyer yaşı ve ek pencere oranları ekstra sinyal eklemedi (`+0,0000` / `+0,0001`). Aşama A seçim kuralı bu fazlalığı otomatik olarak model dışında tuttu.
3. **Canlı Parite Güvencesi:**
   - Tüm `A` ve `N` sütunları bugünkü program tablosunda bulunan alanlardan (`owner`, `trainer`, `jockey`, `age`, `hp`, `agf_pct`) ve `< D` geçmişten hesaplanır; `j_wins_today` gibi gün-içi canlı senkronizasyona bağımlı hiçbir alan eklenmemiştir.

---

## 5. Bir Sonraki Adım Önerisi

1. **Canlıya alma adayı:** `V8_SEL_CAL` (`v8_an`, `122` özellik) ek veri kaynağı gerektirmeden canlıya alınmaya hazırdır (`V8_YEARLY_GAMMA` `reports/V8.md`'deki `V8_SEL_CAL` değerlerinden alınarak `ganyan/model_v8.py` olarak eklenebilir).
2. **Canlı hat sadeleştirmesi:** Mevcut bulut canlı döngüsünü hızlı tutmak için `v5_sgr_all` emekliye ayrılıp (mevcut geçmiş kayıtları `forward_v5.db` içinde saklı kalarak) canlı takip **`v6_e5` + `v7_tcjp` + `v8_an`** üçlüsüyle sürdürülebilir.
3. **Canlı oran verisi (`nino0435/tjk-canli-oran`):** Birkaç aylık canlı ganyan + AGF zaman serisi biriktiğinde, V9 aşamasında "son dakika canlı ganyan vs AGF akıllı para farkı" sinyali de aynı protokolle test edilebilir.
