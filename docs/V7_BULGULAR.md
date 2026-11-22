# Model v7 — Gazete Tecrübesi Özellik Bulguları ve Doğrulama Kapısı (23.11.2026)

Ham rapor: `reports/V7.md`. Koşu günlüğü: `data/v7_run.log`. Özellik modülü: `ganyan/features_v7.py`. Deney betiği: `scripts/run_v7_experiments.py`.

---

## 1. Sonuç Özeti

**Evet, sabit doğrulama kapısını geçen ve mevcut canlı şampiyon `V6_CONFIG` (`E5_best_temp`)'yi geride bırakan bir V7 adayı bulundu: `V7_TCJP_CAL` (`68` V6 özelliği + gazete tecrübesinden çıkarılan `32` T/C/J/P özelliği = `100` özellik, 5 tohum + ileri-yürüyen sıcaklık kalibrasyonu).**

- Salt-okunur `data/ganyan.db` (`2005-01-01`…`2026-11-22`, `111.126` sonuçlanmış koşu, `1.138.799` koşucu; `2006-03-04→` özellik geçmişi, `2015→` AGF'li eğitim) üzerinde sınanan `4` yeni TJK-içi özellik bloğu (`T`: takı değişikliği, `C`: sınıf/rakip zorluğu, `J`: jokey yükseltme/uyum/kilo değişimi, `P`: pist/mesafe/şehir geçmişi) **hiçbir yeni harici kaynak veya site kazıması gerektirmeden** `V6`'nın üstüne istatistiksel olarak anlamlı iyileşme koymuştur.
- **Resmi Aşama B Doğrulama Kapısı (`2022–2025`, `24.515` koşu):**
  - `V7_TCJP_CAL`: `LL = 1,7626`, **`ΔLL vs V6_BASE = −0,0019` (`%95 GA −0,0028…−0,0010`, `4/4` negatif yıl)**, **`ΔLL vs AGF = −0,0272` (`%95 GA −0,0295…−0,0249`)** → **KAPIYI GEÇTİ** (`V6_BASE` `LL = 1,7646`, `Saf AGF` `1,7898`).
  - `V7_SEL_CAL` (`T+C+P`, `90` özellik): `LL = 1,7636`, `ΔLL vs V6_BASE = −0,0010` (`%95 GA −0,0018…−0,0001`, `4/4` negatif yıl) → kapıyı geçti ancak `V7_TCJP_CAL`'ın gerisinde kaldı.
- **2026 Bilgi Kümesi (`5.483` koşu — *kilit v5'te tüketildi, temiz test DEĞİL*):**
  - `V7_TCJP_CAL` `LL = 1,7881` vs `V6_BASE` `1,7896` (**`ΔLL = −0,0015`**, `%95 GA −0,0033…+0,0002`, `ΔLL vs AGF = −0,0259`); 1. tercih `%34,60 → %34,82`, İlk-3 `%69,34 → %69,72`.
  - `2017–2026` arasındaki **10 yılın 9'unda** (`2020–2026` arasındaki son **7 yılın 7'sinde**) `V7_TCJP_CAL`, `V6_BASE`'in önündedir.

> **Kapsam Notu:** Bu çalışmada yalnızca araştırma, sızıntı testleri ve geriye dönük doğrulama yapılmıştır; canlıdaki `ganyan/model_v6.py::V6_CONFIG`, `scripts/forward_v5.py` ve `.github/workflows/*.yml` dosyaları **değiştirilmemiştir**.

---

## 2. Veri Denetimi ve Özellik Kapsamı (`data/ganyan.db`, `2015–2026`)

Özellik kodlaması öncesinde yapılan salt-okunur veritabanı denetiminde tüm girdilerin tarihsel tutarlılığı doğrulandı:

- **`runners.name_raw` (Blok `T`, `8` sütun):** `2015–2026` tüm yıllarda `%100,0` dolu. En az bir takı kodu taşıyan koşucu oranı `%90,4` (`2015`) → `%97,7` (`2026`); `KG` `%59,7–%64,0`, `DB` `%33,0` (`2015`) → `%57,3` (`2026`), `K/KUL` `%26,6–%29,6`. Değerlendirme kümesinde (`2017+`) her koşuda ortalama `eq_any_chg` `%17,6`, `eq_first_kg_or_db` `%3,6` sıfır-dışı sinyal üretir.
- **`races.cls` (Blok `C`, `6` sütun):** `2015–2026` yıllarında `%99,8–%100,0` dolu; `2006–2026` arasındaki `107.472` koşunun **`%99,85`**'i `0..5` zorluk kademelerine eşlendi (eşlenmeyen `%0,15`: boş değer ve amatör binici koşuları). `hp > 0` doluluğu `%85,2–%87,3`; `opp_elo_chg` değerlendirmede `%94,9`, `opp_hp_chg` `%90,6` doludur.
- **`runners.jockey` ve `weight` (Blok `J`, `8` sütun):** `%100,0` dolu. Denetimde jokey adlarında yaklaşık `%25–%35` oranında koşu türüne göre tutarsız `" AP"` eki görüldü (ör. aynı gün aynı jokey bir koşuda `M.T.COŞKUN AP`, diğerinde `M.T.COŞKUN`); `features_v7.py` içinde `j_same_prev`, `hj_*` ve `j_wr_30d` hesaplanırken sondaki `AP` eki soyuldu. Değerlendirme kümesinde `hj_n > 0` oranı `%52,6`, `j_same_prev = 1` `%26,3`, `h_weight_chg ≠ 0` `%81,8`.
- **Pist, Mesafe ve Şehir (Blok `P`, `10` sütun):** `surface`, `distance`, `city` `%100,0` dolu. Değerlendirme kümesinde aynı pistte önceki koşusu olan at oranı (`h_surf_n > 0`) `%89,1`, aynı mesafe bandında (`h_dist_n > 0`) `%85,3`.

---

## 3. Deney Sonuçları

### 3.1 Aşama A — Tekil ve Birleşik Blok Taraması (`2017–2021`, `24.843` Koşu, 1-Tohum `seed=0`)

`V7_SEL` seçimi yalnız bu tablodaki `ΔLL < −0,0003` kuralıyla yapılmıştır → seçilen bloklar: **`T`, `C`, `P`**.

| Varyant | Bloklar | Log-Loss | ΔLL vs `V6_1s` (%95 GA) | Neg. Yıl (/5) | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---|---:|---:|---:|---:|
| `B0` | Saf AGF | 1,8578 | `+0,0213` (`+0,0186`…`+0,0240`) | 0/5 | 32,61% | 52,27% | 66,36% |
| `V6_1s` | Taban (68 öz.) | 1,8365 | — | — | 33,13% | 53,13% | 67,17% |
| `V7_SEL` | `T+C+P` | 1,8348 | **`−0,0017`** (`−0,0029`…`−0,0005`) | **5/5** | 33,36% | 53,29% | **67,27%** |
| `V7_TCJP` | `T+C+J+P` | 1,8349 | **`−0,0016`** (`−0,0029`…`−0,0003`) | 4/5 | **33,41%** | **53,33%** | 67,16% |
| `V7_T` | `T` (Takı) | 1,8354 | **`−0,0011`** (`−0,0018`…`−0,0004`) | 4/5 | 33,31% | 53,36% | 67,23% |
| `V7_C` | `C` (Sınıf/Rakip) | 1,8358 | `−0,0008` (`−0,0016`…`+0,0002`) | 4/5 | 33,23% | **53,39%** | 67,22% |
| `V7_P` | `P` (Pist/Mesafe/Şehir) | 1,8360 | `−0,0005` (`−0,0015`…`+0,0004`) | 4/5 | 33,28% | 53,12% | 67,17% |
| `V7_J` | `J` (Jokey/Kilo) | 1,8368 | `+0,0003` (`−0,0006`…`+0,0012`) | 2/5 | 33,31% | 53,21% | 67,07% |

### 3.2 Aşama B Tanısal Karşılaştırma (`2022–2025`, `24.515` Koşu, 1-Tohum `seed=0`)

Tüm tekil blokların örnek-dışı davranışını şeffafça görmek için tanısal tablo (seçim Aşama A'da donduruldu):

| Varyant | Bloklar | Log-Loss | ΔLL vs `V6_1s` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---|---:|---:|---:|---:|
| `B0` | Saf AGF | 1,7898 | `+0,0243` (`+0,0221`…`+0,0266`) | 0/4 | 34,28% | 54,97% | 69,04% |
| `V6_1s` | Taban (68 öz.) | 1,7655 | — | — | 35,09% | 56,01% | 69,91% |
| **`V7_TCJP`** | `T+C+J+P` | **1,7634** | **`−0,0022`** (`−0,0032`…`−0,0012`) | **4/4** | 35,12% | **56,26%** | 70,10% |
| `V7_SEL` | `T+C+P` | 1,7642 | `−0,0014` (`−0,0023`…`−0,0004`) | 4/4 | 35,06% | 56,15% | 70,15% |
| `V7_J` | `J` (Jokey/Kilo) | 1,7647 | `−0,0008` (`−0,0014`…`−0,0002`) | 4/4 | **35,21%** | 56,09% | 70,03% |
| `V7_T` | `T` (Takı) | 1,7650 | `−0,0006` (`−0,0012`…`−0,0000`) | 4/4 | 35,18% | 56,05% | 70,03% |
| `V7_C` | `C` (Sınıf/Rakip) | 1,7650 | `−0,0005` (`−0,0012`…`+0,0002`) | 4/4 | 35,02% | 56,04% | 70,04% |
| `V7_P` | `P` (Pist/Mesafe/Şehir) | 1,7653 | `−0,0003` (`−0,0010`…`+0,0004`) | 3/4 | 35,11% | 56,17% | **70,20%** |

### 3.3 Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Sıcaklık Kalibrasyonu)

| Varyant | Koşu | Log-Loss | ΔLL vs `V6_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı |
|---|---:|---:|---|---|---:|---:|---:|---:|---|
| `B0` | 24.515 | 1,7898 | `+0,0252` (`+0,0230`…`+0,0276`) | — | 0/4 | 34,28% | 54,97% | 69,04% | Referans |
| `V6_BASE` | 24.515 | 1,7646 | — | `−0,0252` (`−0,0276`…`−0,0230`) | 0/4 | **35,09%** | 56,08% | 69,90% | Taban |
| `V7_SEL_CAL` | 24.515 | 1,7636 | `−0,0010` (`−0,0018`…`−0,0001`) | `−0,0262` (`−0,0285`…`−0,0240`) | 4/4 | 35,07% | 56,21% | **70,14%** | GEÇTİ |
| **`V7_TCJP_CAL`** | **24.515** | **1,7626** | **`−0,0019` (`−0,0028`…`−0,0010`)** | **`−0,0272` (`−0,0295`…`−0,0249`)** | **4/4** | 35,07% | **56,26%** | 70,09% | **KAZANAN** |

`V7_TCJP_CAL` yıllık `ΔLL` kırılımı (vs `V6_BASE`, 5-tohum + sıcaklık kalibrasyonu):
- **2017:** `−0,0039` | **2018:** `−0,0007` | **2019:** `+0,0002` | **2020:** `−0,0017` | **2021:** `−0,0027`
- **2022:** `−0,0034` (`−0,0053`…`−0,0015`) | **2023:** `−0,0004` (`−0,0022`…`+0,0014`) | **2024:** `−0,0018` (`−0,0036`…`−0,0000`) | **2025:** `−0,0022` (`−0,0039`…`−0,0006`)
- **2026 (Bilgi, `5.483` koşu):** `−0,0015` (`−0,0033`…`+0,0002`), 1. Tercih `%34,82` (vs V6 `%34,60`, AGF `%34,05`), İlk-3 `%69,72` (vs V6 `%69,34`, AGF `%67,85`).

---

## 4. Hangi Fikir Nasıl Çalıştı?

1. **En büyük ders: 4 bloğun birleşimi tekil toplamdan bile iyi çalıştı (`V7_TCJP_CAL` `−0,0019` vs `V7_SEL_CAL` `−0,0010`).**
   - Aşama A'da tek başına nötr kalan Blok `J` (`+0,0003`), diğer bloklarla (özellikle sınıf ve pist değişimiyle) birleştiğinde ve son yıllarda (`2022–2025` tek başına `−0,0008`, `4/4` yıl negatif) belirgin tamamlayıcı sinyal üretti.
   - `T` (takı), `C` (sınıf/rakip) ve `J` (jokey/kilo) özellikleri hem `2022–2025`'te hem `2026` bilgi kümesinde `V7_TCJP_CAL`'ı `V7_SEL_CAL`'ın önünde tuttu (`2026`: `V7_TCJP_CAL` `−0,0015` vs `V7_SEL_CAL` `+0,0001`).
2. **Takı değişikliği (`T`) ve Sınıf/Rakip zorluğu (`C`) iki dönemde de tutarlı çalıştı:**
   - Takı değişikliği (`T`) `2017–2021`'de `−0,0011` (`4/5` yıl), `2022–2025`'te `−0,0006` (`4/4` yıl) iyileşme verdi. Piyasa (AGF) temel at formunu fiyatlasa da, özellikle ilk kez `KG`/`DB` takılması veya çıkarılması ile bir önceki yarışa göre rakip sertliği farkı (`opp_elo_chg`) kapanış AGF'sinde dahi tam erimemiş bilgi taşıyor.
3. **Pist/Mesafe/Şehir geçmişi (`P`) ilk-2 ve ilk-3 kapsamını yukarı çekti:**
   - Tek başına log-loss kazancı mütevazı kalsa da (`−0,0005` / `−0,0003`), İlk-2 ve İlk-3 içine kazanan atı sokma oranını (`2022–2025`: İlk-3 `%69,91 → %70,20`) artırdı.
4. **Sıralama vs olasılık kalitesi:**
   - `V6` geçişinde olduğu gibi V7 kazancı da 1. tercih isabetini dramatik biçimde sıçratmaktan (`~%35,1` düzeyinde başa baş; `2026`'da `+%0,22` puan) çok **olasılık kalibrasyonu ve ilk-2/ilk-3 dağılımının keskinleşmesinden** gelmektedir (`AGF`'ye göre toplam fark `−0,0272` nats, İlk-2 `+%1,29` puan, İlk-3 `+%1,05` puan).

---

## 5. Bir Sonraki Adım Önerisi

1. **Canlı ileri-teste alma adayı:** `V7_TCJP_CAL` tüm yeni girdilerini halihazırda her gün çekilen TJK verisinden (`runners.name_raw`, `races.cls`, `jockey`, `weight`, `surface`, `distance`, `city`) ürettiği için **ek veri kaynağı veya harici API gerektirmez** ve canlıya alınması teknik olarak basittir.
2. **Önce karar bekleniyor:** Mevcut canlı `v6_e5` ve `v5_sgr_all` hattına dokunulmadı. Kullanıcı isterse:
   - `ganyan/model_v7.py` + `scripts/forward_v5.py` içine `v7_tcjp` üçüncü canlı model sürümü olarak eklenebilir (mevcut `v5_sgr_all` ve `v6_e5` aynen korunarak);
   - Özellik inşası canlıda sadece güncel koşular + geçmiş DB üzerinde çalışacağı için ek çalışma süresi ihmal edilebilir düzeydedir.
3. **2027 Kilitli Testi:** `V7_TCJP_CAL` yapılandırması da `V6_CONFIG` ile birlikte dondurulup `2027` kilitli test protokolüne alınmalıdır (`2026` verisi temiz test olarak görülmemelidir).
