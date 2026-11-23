# Model v9 — Yeni Paket Bulguları ve Doğrulama Sonucu (23.11.2026)

Ham rapor: `reports/V9.md`. Koşu günlüğü: `data/v9_run.log`. Özellik modülü: `ganyan/features_v9.py`. Deney betiği: `scripts/run_v9_experiments.py`. Testler: `tests/test_features_v9.py`.

## Sade Özet

- Bu turda canlı **v8** modelinin üstüne 5 yeni fikir paketi (`anahtar yarış`, `şehir dışı nakliye`, `ahır sıcaklığı`, `galop binicisi`, `kalıcı kulvar eğilimi`) ile canlıda veri çekilmeyen bilgi amaçlı `gün içi kulvar eğilimi` sınandı.
- **İşe yarayan fikirler:** En büyük kazancı **3 yıllık pist-mesafe-kulvar eğilimi** sağladı; aynı yarıştan çıkan atların sonraki kazanma oranını izleyen **anahtar yarış** ikinci sırada anlamlı katkı verdi, **şehir dışı nakliye** küçük bir ek artı sundu.
- **Katkı vermeyen fikirler:** **Galop binicisi** ve canlıda bulunmayan **gün içi kulvar eğilimi** model gücünü artırmadı; **ahır sıcaklığı** ise eğitim yıllarında umut verip gerçek test yıllarında yerinde saydı.
- **Ne kadar iyileşti ve kapıyı geçti mi?** Seçilen 4 paketin birleşimi (`V9_SEL`), **2022–2025 doğrulama kapısını 4 yılın 4'ünde de v8'i geride bırakarak geçti**; 1. tercih isabeti **%35,21'den %35,38'e**, ilk-3 isabeti **%70,10'dan %70,36'ya** yükseldi (halk favorisinde %34,28 ve %69,04; son 8 yılın tamamında v8'in önünde).
- **Hız uyarısı:** 5 paketin tamamını çalıştırmak **44,8 saniye** sürdüğü için canlıdaki 30 saniyelik ek süre bütçesini aşıyor; ancak galop binicisi çıkarıldığında seçilen 4 paket toplamda **28,3 saniyeye** inerek sınırın içinde kalıyor.
- **Canlı durum:** Bu turda canlı modellere ve zamanlayıcılara hiç dokunulmadı; her şey yalnızca araştırma ve test aşamasında bırakıldı.

---

## 1. Teknik Sonuç Özeti ve Kapsam

**Sabit doğrulama kapısını geçen V9 adayı belirlendi: `V9_SEL_CAL` (`122` V8 özelliği + `KEY` `6` + `SHIP` `4` + `STAB` `5` + `BIAS` `2` = `139` özellik, 5 tohum + ileri-yürüyen sıcaklık kalibrasyonu).**

- Salt-okunur `data/ganyan.db` (`2005-01-01`…`2026-11-22`, `111.126` sonuçlanmış koşu, `1.138.799` koşucu) üzerinde `V8_CONFIG` (`V8_SEL_CAL`, `122` özellik) taban alınarak 5 aday paket (`KEY`, `SHIP`, `STAB`, `WORK`, `BIAS`) ve 1 tanısal paket (`DAY`) test edildi.
- **Sabit Aşama A Seçimi (`2017–2021`, `24.843` koşu, `SEL_THRESHOLD_DLL = -0.0002`):** `KEY` (`−0,0002`), `SHIP` (`−0,0006`), `STAB` (`−0,0006`) ve `BIAS` (`−0,0013`) eşiği geçti; `WORK` (`+0,0000`) elendi. `V9_SEL` (`1,8315`, `ΔLL = −0,0018`), `V9_ALL`'ı (`1,8315`, `−0,0017`) geçerek Aşama B'ye **tek aday** olarak taşındı.
- **Resmi Aşama B Doğrulama Kapısı (`2022–2025`, `24.515` koşu, 5-tohum + sıcaklık kalibrasyonu):**
  - **`V9_SEL_CAL` (`V8 + KEY + SHIP + STAB + BIAS`, `139` öz.):** `LL = 1,7578`, **`ΔLL vs V8_BASE = −0,0021` (`%95 GA −0,0029…−0,0014`, `4/4` negatif yıl)**, **`ΔLL vs AGF = −0,0320` (`%95 GA −0,0347…−0,0295`)**, 1. Tercih `%35,38`, İlk-2 `%56,49`, İlk-3 `%70,36` → **KAPIYI GEÇTİ**.
- **2026 Bilgi Kümesi (`5.483` koşu — *kilit v5'te tüketildi, temiz test DEĞİL*):**
  - `V9_SEL_CAL` `LL = 1,7826` vs `V8_BASE` `1,7852` (**`ΔLL = −0,0026`**, `%95 GA −0,0043…−0,0008`, `ΔLL vs AGF = −0,0314`), İlk-2 `%55,85` (vs `V8_BASE` `%55,64`), İlk-3 `%69,82` (`AGF` `%67,85`).
  - `V9_SEL_CAL`, **`2019–2026` arasındaki son `8` yılın `8`'inde kesintisiz biçimde `V8_BASE`'in önünde yer aldı** (`2017–2026` arasında `10` yılın `9`'u).

> **Kapsam Notu:** Şartname gereği canlıya dokunulmamıştır (`ganyan/model_v6.py`, `model_v7.py`, `model_v8.py`, `scripts/forward_v5.py`, `.github/workflows/*.yml`, `features_v5..v8.py` değiştirilmedi; `model_v9.py` yazılmadı).

---

## 2. Süre Ölçümleri ve Canlı Bütçe

- **Mevcut canlı taban (`LIVE_BASELINE_S`):** Aktif 3 canlı model (`v6_e5` + `v7_tcjp` + `v8_an`) koşu döngüsü toplam **`~175` sn (`2 dk 55 sn`)** sürmektedir; önerilen ek süre bütçesi `30` sn'dir.
- **`attach_v9` Tüm Geçmiş Süresi (`2006-03-04`→`2026-11-22`, `1.071.637` satır):**
  - **5 aday paket toplamı (`KEY+SHIP+STAB+WORK+BIAS`):** **`44,79` sn** (**UYARI:** `30` sn ek bütçeyi **aşıyor**).
  - **`DAY` dahil 6 paket toplamı:** `50,57` sn.
  - **Paket bazlı süre kırılımı:** `KEY` `8,35` sn | `SHIP` `7,76` sn | `STAB` `6,12` sn | `WORK` `16,44` sn | `BIAS` `6,11` sn | `DAY` `5,78` sn.
  - **`V9_SEL` 4 paketi (`KEY+SHIP+STAB+BIAS`, yavaş `WORK` hariç) toplamı:** **`28,34` sn** (`30` sn bütçenin hemen altında).
- **Tek Günlük Program İzole Dilimi (`2026-11-22`, `15` koşu / `155` koşucu):** `8,488` sn (not: canlı hat geçmiş pencere hesapları için `2006→bugün` tarih matrisini çalıştırdığından gerçek canlı ek yük tam geçmiş süresine yakındır).

---

## 3. Veri ve Özellik Doluluk Tabloları (`data/ganyan.db`, `2017+` Değerlendirme Kümesi)

### 3.1 Özellik Bazında Dolu ve Sıfır-Dışı Oranları (`24` Özellik)

| Paket | Sütun | Tüm Veri Dolu (%) | Değerlendirme `2017+` Dolu (%) | Değerlendirme `2017+` Sıfır-Dışı (%) |
|---|---|---:|---:|---:|
| `KEY` | `key_n_ran` | 94.8% | 94.9% | 75.4% |
| `KEY` | `key_n_won` | 94.8% | 94.9% | 34.8% |
| `KEY` | `key_wr` | 74.7% | 75.4% | 75.4% |
| `KEY` | `key_ahead_wr` | 56.2% | 56.1% | 56.1% |
| `KEY` | `key_behind_wr` | 56.2% | 57.0% | 57.0% |
| `KEY` | `key_wr_m3` | 93.7% | 93.9% | 93.9% |
| `SHIP` | `trn_away` | 97.0% | 97.3% | 34.3% |
| `SHIP` | `trn_city_share_365d` | 97.0% | 97.3% | 96.0% |
| `SHIP` | `trn_away_resid_730d` | 59.7% | 95.9% | 95.9% |
| `SHIP` | `h_ship_first` | 94.8% | 94.9% | 10.2% |
| `STAB` | `trn_n_28d` | 100.0% | 100.0% | 98.3% |
| `STAB` | `trn_resid_14d` | 60.4% | 95.4% | 95.4% |
| `STAB` | `trn_resid_28d` | 62.1% | 98.1% | 98.1% |
| `STAB` | `trn_fpct_resid_28d` | 62.1% | 98.1% | 97.4% |
| `STAB` | `trn_resid_28d_rel` | 62.1% | 98.1% | 98.1% |
| `WORK` | `gw_jk_last` | 52.8% | 85.7% | 14.3% |
| `WORK` | `gw_jk_n30` | 99.2% | 98.6% | 19.0% |
| `WORK` | `gw_hard_days` | 27.4% | 47.2% | 47.2% |
| `WORK` | `gw_jk_first_ride` | 99.2% | 98.6% | 6.9% |
| `BIAS` | `bias_gate_resid` | 63.5% | 99.9% | 99.9% |
| `BIAS` | `bias_n` | 100.0% | 100.0% | 99.9% |
| `DAY` | `day_bias_n` | 100.0% | 100.0% | 87.3% |
| `DAY` | `day_gate_bias` | 82.9% | 87.3% | 86.0% |
| `DAY` | `day_gate_bias_x_gf` | 82.9% | 87.3% | 86.0% |

### 3.2 `WORK` Jokey Eşleşme Oranları — Kaynak × Yıl Kırılımı (`liderform` vs `yenibeygir`)

> **Veri Notu:** Liderform galop akışı `18 Kas 2026` tarihinde durmuş olup canlı hat galop verisini **Yenibeygir**'den çekmektedir. Yenibeygir galop kayıtlarında binici sütunu **~%18–22 oranında boştur** (`2026`'da `4.194` satırın **`%21,6`**'sı null; `2025`'te `67` satırın **`%11,9`**'u null); buna karşılık binici dolu geldiğinde tam ad formatıyla geldiği için TJK yarış binicileriyle eşleşme oranı (`%13,9`), Liderform'un `2026` bilinen-binici içi eşleşme oranıyla (`%14,0`) neredeyse birebir aynıdır. Liderform'da `APRANTİ` etiketi `2026`'da `%8,4`'e çıkmıştır ve kural gereği `NaN` sayılmıştır.

#### Tekil Galop Satırlarında Binici Bilgisi

| Kaynak | Yıl | Galop Satırı | Bilinen Binici (%) | `APRANTİ` (%) | Boş/Null (%) |
|---|---:|---:|---:|---:|---:|
| `liderform` | 2017 | 129,098 | 99.3% | 0.7% | 0.0% |
| `liderform` | 2018 | 131,793 | 99.1% | 0.9% | 0.0% |
| `liderform` | 2019 | 115,188 | 98.2% | 1.8% | 0.0% |
| `liderform` | 2020 | 111,420 | 97.1% | 2.9% | 0.0% |
| `liderform` | 2021 | 117,386 | 98.0% | 2.0% | 0.0% |
| `liderform` | 2022 | 133,856 | 99.2% | 0.8% | 0.0% |
| `liderform` | 2023 | 131,180 | 98.8% | 1.2% | 0.0% |
| `liderform` | 2024 | 135,876 | 98.3% | 1.7% | 0.0% |
| `liderform` | 2025 | 150,504 | 96.5% | 3.4% | 0.0% |
| `liderform` | 2026 | 124,492 | 91.6% | 8.4% | 0.0% |
| `yenibeygir` | 2022 | 2 | 0.0% | 0.0% | 100.0% |
| `yenibeygir` | 2023 | 7 | 100.0% | 0.0% | 0.0% |
| `yenibeygir` | 2024 | 15 | 100.0% | 0.0% | 0.0% |
| `yenibeygir` | 2025 | 67 | 88.1% | 0.0% | 11.9% |
| `yenibeygir` | 2026 | 4,194 | 78.4% | 0.0% | 21.6% |

#### Koşucu Düzeyinde Son 30g Galop → Yarış Jokeyi Eşleşme Oranı

| Kaynak | Yıl | Son 30g Galoplu Koşucu | Bilinen Binici (%) | Tüm Koşucuda Eşleşme (%) | Bilinen İçinde Eşleşme (%) |
|---|---:|---:|---:|---:|---:|
| `liderform` | 2017 | 46,320 | 99.1% | 20.0% | 20.2% |
| `liderform` | 2018 | 46,172 | 99.1% | 18.7% | 18.9% |
| `liderform` | 2019 | 40,582 | 97.0% | 14.2% | 14.7% |
| `liderform` | 2020 | 37,809 | 94.4% | 13.8% | 14.6% |
| `liderform` | 2021 | 42,326 | 95.8% | 12.7% | 13.2% |
| `liderform` | 2022 | 52,293 | 99.2% | 18.1% | 18.2% |
| `liderform` | 2023 | 51,290 | 98.9% | 17.7% | 17.9% |
| `liderform` | 2024 | 51,713 | 98.3% | 16.4% | 16.7% |
| `liderform` | 2025 | 56,768 | 96.8% | 16.2% | 16.7% |
| `liderform` | 2026 | 50,762 | 91.3% | 12.8% | 14.0% |
| `yenibeygir` | 2022 | 3 | 0.0% | 0.0% | 0.0% |
| `yenibeygir` | 2023 | 9 | 100.0% | 22.2% | 22.2% |
| `yenibeygir` | 2024 | 18 | 100.0% | 0.0% | 0.0% |
| `yenibeygir` | 2025 | 56 | 73.2% | 12.5% | 17.1% |
| `yenibeygir` | 2026 | 2,051 | 77.4% | 10.7% | 13.9% |

---

## 4. Deney Sonuçları

### 4.1 Aşama A — Paket Taraması (`2017–2021`, `24.843` Koşu, 1-Tohum `seed=0`)

`V9_SEL` seçimi yalnız bu tablodaki sabit `ΔLL < −0,0002` kuralıyla yapılmıştır → seçilen paketler: **`KEY`, `SHIP`, `STAB`, `BIAS`**.

| Varyant | Paketler | Log-Loss | ΔLL vs `V8_1s` (%95 GA) | Neg. Yıl (/5) | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---|---:|---:|---:|---:|
| `B0` | Saf AGF | 1.8578 | `+0.0246` (`+0.0216`…`+0.0275`) | 0/5 | 32.61% | 52.27% | 66.36% |
| `V8_1s` | Taban (122 öz.) | 1.8332 | — | — | 33.49% | 53.43% | 67.48% |
| **`V9_SEL`** | `KEY+SHIP+STAB+BIAS` (139 öz.) | **1.8315** | **`−0.0018`** (`−0.0028`…`−0.0007`) | 4/5 | 33.39% | 53.46% | 67.42% |
| `V9_ALL` | 5 Aday Paket (143 öz.) | 1.8315 | `−0.0017` (`−0.0028`…`−0.0006`) | **5/5** | 33.45% | 53.39% | 67.42% |
| `V9_BIAS` | `BIAS` (Kalıcı Kulvar Eğilimi) | 1.8319 | `−0.0013` (`−0.0022`…`−0.0004`) | **5/5** | 33.36% | 53.38% | 67.40% |
| `V9_SHIP` | `SHIP` (Şehir Dışı Nakliye) | 1.8326 | `−0.0006` (`−0.0013`…`+0.0001`) | **5/5** | 33.55% | 53.52% | 67.47% |
| `V9_STAB` | `STAB` (Ahır Sıcaklığı) | 1.8326 | `−0.0006` (`−0.0014`…`+0.0002`) | 4/5 | 33.51% | **53.56%** | 67.42% |
| `V9_DAY` | `DAY` (Tanı: Gün İçi Kulvar) | 1.8329 | `−0.0003` (`−0.0010`…`+0.0004`) | 4/5 | **33.58%** | 53.51% | **67.55%** |
| `V9_KEY` | `KEY` (Anahtar Yarış) | 1.8330 | `−0.0002` (`−0.0009`…`+0.0005`) | 4/5 | 33.49% | 53.44% | 67.43% |
| `V9_WORK` | `WORK` (Galop Binicisi) | 1.8333 | `+0.0000` (`−0.0006`…`+0.0007`) | 2/5 | 33.54% | 53.45% | 67.52% |

### 4.2 Aşama 2 Tanısal Karşılaştırma (`2022–2025`, `24.515` Koşu, 1-Tohum `seed=0`, `DAY` Dahil)

| Varyant | Paketler | Log-Loss | ΔLL vs `V8_1s` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---|---:|---:|---:|---:|
| `B0` | Saf AGF | 1.7898 | `+0.0290` (`+0.0266`…`+0.0315`) | 0/4 | 34.28% | 54.97% | 69.04% |
| `V8_1s` | Taban (122 öz.) | 1.7608 | — | — | 35.30% | 56.21% | 70.27% |
| **`V9_SEL`** | `KEY+SHIP+STAB+BIAS` | **1.7587** | **`−0.0022`** (`−0.0030`…`−0.0013`) | **4/4** | 35.23% | 56.44% | 70.37% |
| `V9_ALL` | 5 Aday Paket | 1.7588 | `−0.0021` (`−0.0029`…`−0.0012`) | 4/4 | 35.20% | **56.45%** | 70.31% |
| `V9_BIAS` | `BIAS` | 1.7589 | `−0.0020` (`−0.0027`…`−0.0012`) | 4/4 | 35.27% | 56.40% | **70.43%** |
| `V9_KEY` | `KEY` | 1.7602 | `−0.0007` (`−0.0012`…`−0.0001`) | 3/4 | 35.19% | 56.27% | 70.21% |
| `V9_SHIP` | `SHIP` | 1.7606 | `−0.0003` (`−0.0008`…`+0.0003`) | 3/4 | **35.33%** | 56.21% | 70.14% |
| `V9_DAY` | `DAY` (Tanı) | 1.7607 | `−0.0001` (`−0.0006`…`+0.0004`) | 2/4 | 35.32% | 56.21% | 70.19% |
| `V9_WORK` | `WORK` | 1.7608 | `−0.0001` (`−0.0005`…`+0.0004`) | 2/4 | 35.30% | 56.13% | 70.16% |
| `V9_STAB` | `STAB` | 1.7609 | `+0.0000` (`−0.0005`…`+0.0005`) | 2/4 | 35.24% | 56.22% | 70.23% |

### 4.3 Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Sıcaklık Kalibrasyonu)

| Varyant | Koşu | Log-Loss | ΔLL vs `V8_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı |
|---|---:|---:|---|---|---:|---:|---:|---:|---|
| `B0` | 24,515 | 1.7898 | `+0.0299` (`+0.0275`…`+0.0324`) | — | 0/4 | 34.28% | 54.97% | 69.04% | Referans |
| `V8_BASE` | 24,515 | 1.7599 | — | `−0.0299` (`−0.0324`…`−0.0275`) | 0/4 | 35.21% | 56.28% | 70.10% | Taban |
| **`V9_SEL_CAL`** | **24,515** | **1.7578** | **`−0.0021` (`−0.0029`…`−0.0014`)** | **`−0.0320` (`−0.0347`…`−0.0295`)** | **4/4** | **35.38%** | **56.49%** | **70.36%** | **GEÇTİ** |

`V9_SEL_CAL` yıllık `ΔLL` kırılımı (`vs V8_BASE`, 5-tohum + sıcaklık kalibrasyonu):
- **Aşama A Yılları (5-tohum bilgi):** `2017:` `−0.0015` | `2018:` `+0.0001` | `2019:` `−0.0017` | `2020:` `−0.0021` | `2021:` `−0.0013`
- **Aşama B Resmi Yılları:** **2022:** `−0.0023` (`−0.0038`…`−0.0008`) | **2023:** `−0.0025` (`−0.0040`…`−0.0011`) | **2024:** `−0.0022` (`−0.0036`…`−0.0007`) | **2025:** `−0.0015` (`−0.0032`…`+0.0001`)
- **2026 (Bilgi, `5.483` koşu):** `−0.0026` (`−0.0043`…`−0.0008`), 1. Tercih `%34.69` (`V8_BASE` `%34.62`), İlk-2 `%55.85` (`%55.64`), İlk-3 `%69.82` (`%69.82`, `AGF` `%67.85`).

---

## 5. Hangi Fikir Nasıl Çalıştı?

1. **`BIAS` (3 Yıllık Kalıcı Kulvar Eğilimi) açık ara ana itici güç oldu (`−0,0013` Aşama A, `−0,0020` Aşama 2, her dönemde yılların tamamında pozitif katkı):**
   - V7'de yalnızca şehir × pist × genel start bandı varken, `BIAS`'ın **4 mesafe bandı + 5 başlangıç kulvar dilimi** düzeyinde **kazanma − AGF beklentisi artığı** çıkarması AGF'nin göremediği iç/dış kulvar avantajlarını doğrudan yakaladı.
2. **`KEY` (Anahtar Yarış / Rakiplerin Sonraki Başarısı) örnek-dışında güçlenerek #2 konuma yerleşti (`−0,0002` Aşama A → `−0,0007` Aşama 2):**
   - Atın son yarışında önüne düşen ve arkasına düşen rakiplerin 28 gün içindeki sonraki galibiyet oranlarını ayırmak, koşunun gerçek sertliğini AGF'nin üzerinde ölçtü; aynı gün (`D`) koşan rakiplerin dışlanması tam sızıntısız çalıştı.
3. **`SHIP` (Şehir Dışı Nakliye Niyeti) küçük ama tutarlı ek sinyal verdi (`−0,0006` Aşama A, `−0,0003` Aşama 2):**
   - Ev şehri dışına gönderilen atın antrenörünün 730 günlük deplasman artığı ve atın ilk nakliyesi ekstra ayırt edicilik ekledi.
4. **`STAB` (Ahırın 14g/28g Kısa Form Dalgası) örnek-dışı nötr çıktı (`−0,0006` Aşama A, `+0,0000` Aşama 2):**
   - Aşama A'da sabit `−0,0002` eşiğini geçtiği için protokole sadık kalınarak `V9_SEL` içinde korundu; ancak `2022–2025`'te ek faydası `0` göründü (V8'deki `N` paketi ahır bilgisinin önemli kısmını zaten taşıyor).
5. **`WORK` (Galop Binicisi Eşleşmesi) ekstra kazanç sağlamadı (`+0,0000` Aşama A, `−0,0001` Aşama 2) ve yavaş (`16,44` sn):**
   - Doğru biçimde elendi; böylece gereksiz `16,44` sn yük de canlı adayından düştü.
6. **`DAY` (Tanısal Gün İçi Kulvar Eğilimi) neredeyse sıfır etki gösterdi (`−0,0001` Aşama 2, `2/4` yıl):**
   - Canlıda günün bitmiş koşu sonuçlarını çekmemekten doğan kayıp ihmal edilebilir düzeydedir (`~0,0001`).

---

## 6. Bir Sonraki Adım Önerisi

1. **Bu turda canlıya dokunulmadı** (şartname gereği yalnız araştırma + test tamamlandı).
2. **Tur 2 için canlıya alma değerlendirmesi:**
   - `V9_SEL_CAL` (`KEY + SHIP + STAB + BIAS`, `139` özellik) kapıyı `4/4` yıl ile güçlü biçimde geçti ve `WORK` dışarıda kaldığı için ek süre **`28,34` sn** (`< 30` sn bütçe).
   - İstenirse Tur 2'de yalnızca Aşama B kapısından geçmiş olan bu yapı üzerinden `ganyan/model_v9.py` (veya `STAB`'sız `KEY+SHIP+BIAS` ablatif kontrolü yapılmak istenirse yeni sabit protokolde sınanarak) canlıya alım planlanabilir.
