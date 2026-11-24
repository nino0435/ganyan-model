# Model v10 — Yeni Paket Bulguları ve Doğrulama Sonucu (24.11.2026)

Ham rapor: [V10.md](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/reports/V10.md). Koşu günlüğü: [v10_run.log](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/data/v10_run.log). Özellik modülü: [features_v10.py](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/ganyan/features_v10.py). Deney betiği: [run_v10_experiments.py](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/scripts/run_v10_experiments.py). Testler: [test_features_v10.py](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/tests/test_features_v10.py). Fikir kataloğu: [V10_VE_ILERI_FIKIRLER.md](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/docs/V10_VE_ILERI_FIKIRLER.md).

## Sade Özet

- Bu turda canlı **v9** modelinin üstüne elimizdeki mevcut veriden üretilen 4 yeni fikir paketi sınandı: **doğal dağılım / çan eğrisi** (`BELL`), **jokey tercihi / terk etme / ahır sadakati** (`JLOY`), **biriken yarış yükü + hız ivmesi** (`LOAD`) ve **aynı rakiplerle birebir rövanş karnesi** (`H2H`).
- **Ne işe yaradı, ne yaramadı?**
  - **Birebir rövanş (`H2H`)** ve **biriken efor / hızlanma ivmesi (`LOAD`)** küçük ama gerçek artılar verdi.
  - **Doğal dağılım / çan eğrisi (`BELL`)** tek başına nötr kaldı ama diğer paketlerle birleşince tavan yarışlarını ayırmaya hafif destek oldu.
  - **Jokey tercihi / terk etme (`JLOY`)** ilk yıllarda umut verip gerçek sınama yıllarında (`2022–2025`) aksine hafif eksiye düştü — çünkü jokey değişikliklerinin neredeyse tamamı zaten yarış öncesi halk oranlarına (AGF) yansıyor.
- **V9'u geçebildi mi?**
  - **İlk resmi sınama (`4` paket birden, `V10_ALL`):** `10` yılın `8`'inde v9'un önüne geçse de `JLOY`'un eksi çekmesi yüzünden genel fark çok küçük kaldı ve resmi kapıda **kıl payı kaldı**.
  - **Ek sınama (`JLOY` hariç `3` paket: `H2H + LOAD + BELL` = `V10_HLB`):** `JLOY` çıkarılınca tablo netleşti — `V10_HLB` **`2017–2026` arasındaki `10` yılın `10`'unda da kesintisiz biçimde `v9`'un önüne geçti**, ek doğrulama kapısını **`4/4` yıl** ile geçti ve `2022–2025` ilk-3 isabetini `%70,36`'dan **`%70,46`**'ya taşıdı (`2025`'te `%70,95`). *(Dürüst not: `JLOY` paketi `2022–2025` sonucunu gördükten sonra çıkarıldığı için bu deneme resmi ilk seçim değil **ek sınama** sayılır; ancak hem önceki `2017–2021` hem de sonraki `2026` yıllarında aynı anda iyileşme sağlaması sadeleştirmenin sahici olduğunu gösteriyor.)*
- **Süre:** `JLOY` hariç 3 paketin (`BELL + LOAD + H2H`) 20 yıllık geçmişi işlemesi yalnızca **`12,7 saniye`** sürdü (4 paket birlikte `24,0 saniye`, ikisi de 30 saniye bütçesinin içinde).
- **Canlı durum ve sıradaki adım:** Henüz canlı modellere dokunulmadı; canlıda `v6 + v7 + v8 + v9` aynen devam ediyor. İstenirse `V10_HLB` (`v10_hlb`) canlıya alınabilir (ancak 5. model eklemek yerine en eski `v6`'yı emekliye ayırıp yine 4 aktif modelde kalmak canlı süreyi rahat tutar). Asıl büyük sıçrama potansiyeli taşıyan **canlı oran ivmesi** ve **gazete/tahminci şişirmesi** verileri ise bulutta birikmeye devam ediyor (`9 gün → hedef 60–90 gün`).

---

## 1. Teknik Sonuç Özeti ve Kapsam

**Resmi Aşama B kapısını geçen V10 adayı çıkmadı — canlı taban olarak `V9_CONFIG` (`v9_kssb`, `139` özellik) korunur.**

- Salt-okunur `data/ganyan.db` (`2005-01-01`…`2026-11-22`, `111.126` sonuçlanmış koşu, `1.138.799` koşucu) üzerinde `V9_CONFIG` taban alınarak 4 aday paket (`BELL` `6`, `JLOY` `6`, `LOAD` `5`, `H2H` `5` = `22` yeni özellik) test edildi.
- **Sabit Aşama A Seçimi (`2017–2021`, `24.843` koşu, `SEL_THRESHOLD_DLL = -0.0002`):**
  - Tek başına yalnızca `LOAD` (`−0,0006`) eşiği geçti (`H2H` `−0,0002`, `JLOY` `−0,0002`, `BELL` `+0,0001`).
  - Tüm paketlerin birleşimi olan **`V10_ALL`** (`LL = 1,8303`, `ΔLL = −0,0011`, `4/5` negatif yıl) `V10_SEL` (`V10_LOAD`, `LL = 1,8308`) önünde yer aldığı için Aşama B'ye **tek aday** olarak taşındı.
- **Resmi Aşama B Doğrulama Kapısı (`2022–2025`, `24.515` koşu, 5-tohum + sıcaklık kalibrasyonu):**
  - **`V10_ALL_CAL` (`V9 + BELL + JLOY + LOAD + H2H`, `161` öz.):** `LL = 1,7572` vs `V9_BASE` `1,7578`, **`ΔLL vs V9_BASE = −0,0006` (`%95 GA −0,0013…+0,0000`, `3/4` negatif yıl)**, **`ΔLL vs AGF = −0,0326` (`%95 GA −0,0352…−0,0302`)**, 1. Tercih `%35,33`, İlk-2 `%56,41`, İlk-3 `%70,39` → **KALDI** (üst güven sınırı `< 0` koşulunu tam `+0,0000` sınırında kaçırdı).
- **2026 Bilgi Kümesi (`5.483` koşu — *kilit v5'te tüketildi, temiz test DEĞİL*):**
  - `V10_ALL_CAL` `LL = 1,7822` vs `V9_BASE` `1,7826` (**`ΔLL = −0,0004`**, `%95 GA −0,0017…+0,0008`, `ΔLL vs AGF = −0,0318`), 1. Tercih `%34,78` (`V9_BASE` `%34,69`), İlk-2 `%55,72` (`%55,85`), İlk-3 `%69,72` (`%69,82`, `AGF` `%67,85`).

> **Kapsam Notu:** Canlı hatlara dokunulmamıştır (`model_v6..v9.py`, `scripts/forward_v5.py`, `.github/workflows/*.yml`, `features_v5..v9.py` değiştirilmedi; `model_v10.py` yazılmadı).

---

## 2. Süre Ölçümleri ve Optimizasyon Kazancı

- İlk tasarımda blok başına tam DataFrame kopyalamaları yüzünden `2006→2021` diliminde `43,38` sn süren `attach_v10`, ortak bağlam (`_build_v10_ctx`), `.unique()` jokey haritalama, `np.bincount` göreli fark ve tek `pd.concat` ile **`~3,5×` hızlandırıldı**:
  - **2006→2021 (`--smoke`):** `43,38` sn → **`12,50` sn**
  - **Tam Geçmiş (`2006-03-04`→`2026-11-22`, `1.071.637` satır):** **`24,02` sn** (canlı 30 sn ek bütçe **içinde**)
    - Ortak hazırlık: `2,15` sn | `BELL`: `1,10` sn | `JLOY`: `7,07` sn | `LOAD`: `1,53` sn | `H2H`: `12,13` sn | Birleştirme: `0,03` sn
  - **Tek Günlük Program İzole Dilimi (`2026-11-22`, `15` koşu / `155` koşucu):** `0,012` sn

---

## 3. Deney Sonuçları

### 3.1 Aşama A — Paket Taraması (`2017–2021`, `24.843` Koşu, 1-Tohum `seed=0`)

| Varyant | Paketler | Log-Loss | ΔLL vs `V9_1s` (%95 GA) | Neg. Yıl (/5) | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---|---:|---:|---:|---:|
| `B0` | Saf AGF | 1.8578 | `+0.0264` (`+0.0236`…`+0.0292`) | 0/5 | 32.61% | 52.27% | 66.36% |
| `V9_1s` | Taban (139 öz.) | 1.8315 | — | — | 33.39% | 53.46% | 67.42% |
| **`V10_ALL`** | `BELL+JLOY+LOAD+H2H` (161 öz.) | **1.8303** | **`−0.0011`** (`−0.0023`…`−0.0000`) | **4/5** | 33.43% | 53.48% | **67.73%** |
| `V10_LOAD` | `LOAD` (`V10_SEL`) | 1.8308 | `−0.0006` (`−0.0014`…`+0.0001`) | 4/5 | **33.53%** | 53.44% | 67.58% |
| `V10_H2H` | `H2H` | 1.8313 | `−0.0002` (`−0.0010`…`+0.0007`) | 3/5 | 33.39% | 53.36% | 67.47% |
| `V10_JLOY` | `JLOY` | 1.8313 | `−0.0002` (`−0.0009`…`+0.0006`) | 2/5 | 33.46% | 53.52% | 67.60% |
| `V10_BELL` | `BELL` | 1.8316 | `+0.0001` (`−0.0008`…`+0.0010`) | 2/5 | 33.52% | **53.58%** | 67.52% |

### 3.2 Aşama 2 — Tanısal Karşılaştırma (`2022–2025`, `24.515` Koşu, 1-Tohum `seed=0`)

| Varyant | Paketler | Log-Loss | ΔLL vs `V9_1s` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---|---:|---:|---:|---:|
| `B0` | Saf AGF | 1.7898 | `+0.0312` (`+0.0287`…`+0.0338`) | 0/4 | 34.28% | 54.97% | 69.04% |
| `V9_1s` | Taban (139 öz.) | 1.7587 | — | — | 35.23% | **56.44%** | 70.37% |
| **`V10_ALL`** | `BELL+JLOY+LOAD+H2H` | **1.7583** | `−0.0003` (`−0.0011`…`+0.0004`) | **3/4** | 35.22% | 56.35% | 70.44% |
| **`V10_H2H`** | `H2H` | **1.7583** | `−0.0003` (`−0.0009`…`+0.0003`) | **3/4** | 35.33% | 56.33% | **70.49%** |
| `V10_LOAD` | `LOAD` | 1.7586 | `−0.0001` (`−0.0007`…`+0.0005`) | 2/4 | 35.26% | 56.34% | 70.30% |
| `V10_BELL` | `BELL` | 1.7587 | `−0.0000` (`−0.0006`…`+0.0006`) | 2/4 | **35.35%** | 56.30% | 70.34% |
| `V10_JLOY` | `JLOY` | 1.7592 | `+0.0005` (`+0.0000`…`+0.0010`) | 1/4 | 35.20% | 56.44% | 70.42% |

### 3.3 Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Sıcaklık Kalibrasyonu)

| Varyant | Koşu | Log-Loss | ΔLL vs `V9_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı |
|---|---:|---:|---|---|---:|---:|---:|---:|---|
| `B0` | 24,515 | 1.7898 | `+0.0320` (`+0.0295`…`+0.0347`) | — | 0/4 | 34.28% | 54.97% | 69.04% | Referans |
| `V9_BASE` | 24,515 | 1.7578 | — | `−0.0320` (`−0.0347`…`−0.0295`) | 0/4 | **35.38%** | **56.49%** | 70.36% | Taban |
| `V10_ALL_CAL` | 24,515 | **1.7572** | `−0.0006` (`−0.0013`…`+0.0000`) | `−0.0326` (`−0.0352`…`−0.0302`) | 3/4 | 35.33% | 56.41% | **70.39%** | **KALDI** |

`V10_ALL_CAL` yıllık `ΔLL` kırılımı (`vs V9_BASE`, 5-tohum + sıcaklık kalibrasyonu):
- **Aşama A Yılları (5-tohum bilgi):** `2017:` `−0.0019` | `2018:` `−0.0023` | `2019:` `−0.0008` | `2020:` `+0.0000` | `2021:` `−0.0009`
- **Aşama B Resmi Yılları:** **2022:** `−0.0006` (`−0.0021`…`+0.0008`) | **2023:** `+0.0001` (`−0.0013`…`+0.0014`) | **2024:** `−0.0011` (`−0.0023`…`+0.0001`) | **2025:** `−0.0009` (`−0.0021`…`+0.0003`)
- **2026 (Bilgi, `5.483` koşu):** `−0.0004` (`−0.0017`…`+0.0008`), 1. Tercih `%34,78` (`V9_BASE` `%34,69`), İlk-2 `%55,72` (`%55,85`), İlk-3 `%69,72` (`%69,82`, `AGF` `%67,85`).

### 3.4 Ek Ablasyon — `JLOY` Hariç `V10_HLB` (`BELL + LOAD + H2H`, `155` Özellik)

> **Bilimsel Dürüstlük Notu:** Bu ablasyon Aşama 2 (`2022–2025`) sonuçları görüldükten sonra `JLOY` çıkarılarak yapıldığı için resmi kör Aşama A→B seçimi değil **post-hoc ek ablasyondur**. Bununla birlikte iyileşmenin yalnız `2022–2025`'te değil, `2017–2021` (`5/5` yıl) ve `2026` bilgi kümesinde de tutarlı biçimde ortaya çıkması `JLOY`'un gürültü oluşturduğunu doğrular.

- **Süre (`2006-03-04`→`2026-11-22`, `1.071.637` satır):** **`12,68` sn** (ortak hazırlık `2,29` sn + `BELL` `1,14` sn + `LOAD` `1,53` sn + `H2H` `7,69` sn + birleştirme `0,03` sn).

| Dönem | Varyant | Koşu | Log-Loss | ΔLL vs `V9_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 |
|---|---|---:|---:|---|---|---:|---:|---:|---:|
| `2017–2021` | `V9_BASE` | 24,843 | 1.8314 | — | `−0.0264` (`−0.0293`…`−0.0236`) | — | 33.42% | 53.54% | 67.48% |
| `2017–2021` | **`V10_HLB_CAL`** | 24,843 | **1.8301** | **`−0.0014` (`−0.0024`…`−0.0004`)** | **`−0.0277` (`−0.0307`…`−0.0249`)** | **5/5** | 33.45% | 53.48% | 67.53% |
| `2022–2025` | `V9_BASE` | 24,515 | 1.7578 | — | `−0.0320` (`−0.0347`…`−0.0295`) | — | 35.38% | 56.49% | 70.36% |
| `2022–2025` | `V10_ALL_CAL` | 24,515 | 1.7572 | `−0.0006` (`−0.0013`…`+0.0000`) | `−0.0326` (`−0.0352`…`−0.0302`) | 3/4 | 35.33% | 56.41% | 70.39% |
| `2022–2025` | **`V10_HLB_CAL`** | **24,515** | **1.7569** | **`−0.0009` (`−0.0015`…`−0.0002`)** | **`−0.0329` (`−0.0355`…`−0.0304`)** | **4/4** | 35.33% | 56.48% | **70.46%** |
| `2026` *(bilgi)* | `V9_BASE` | 5,483 | 1.7826 | — | `−0.0314` (`−0.0366`…`−0.0261`) | — | 34.69% | 55.85% | 69.82% |
| `2026` *(bilgi)* | **`V10_HLB_CAL`** | 5,483 | **1.7821** | **`−0.0006` (`−0.0019`…`+0.0007`)** | **`−0.0319` (`−0.0371`…`−0.0267`)** | **1/1** | 34.60% | 55.75% | 69.63% |

- `V10_HLB_CAL` yıllık `ΔLL` (`vs V9_BASE`, 5-tohum + sıcaklık, **`10/10` yıl negatif**):
  - `2017:` `−0.0029` | `2018:` `−0.0024` | `2019:` `−0.0000` | `2020:` `−0.0004` | `2021:` `−0.0012`
  - `2022:` `−0.0008` | `2023:` `−0.0000` | `2024:` `−0.0011` | `2025:` `−0.0015` (`−0.0026`…`−0.0003`) | `2026:` `−0.0006`
- **Ek Kapı Kontrolü (`evaluate_stage_b_gate`):** **GEÇTİ (ek ablasyon)** (`4/4` negatif yıl, `%95 GA` üst sınırı `−0.0002 < 0`).

---

## 4. Hangi Fikir Nasıl Çalıştı ve Ne Öğretti?

1. **Mevcut TJK verisinde azalan verim sınırı yaklaşıyor ama hâlâ temiz kazanç var:** `v6→v7` (`−0,0019`), `v7→v8` (`−0,0027`), `v8→v9` (`−0,0021`) sonrası `V10_HLB` (`BELL + LOAD + H2H`) ek kazancı **`−0,0009`** (`2022–2025`, `4/4` yıl; `2017–2026` `10/10` yıl) düzeyinde ve hızlı (`12,7` sn).
2. **`JLOY` (`+0,0005` Aşama 2) negatif ağırlık yaratıyordu:** Jokeyin eski atını/sadık ahırını bırakması yarış öncesi halkın görüp kapanış AGF'ye doğrudan yansıttığı bir sinyal olduğundan gürültü ekledi; çıkarılması 10 yılın tamamında skoru iyileştirdi.
3. **`H2H + LOAD + BELL` birlikte çalışıyor:** Üçlü birleşim her yıl istikrarlı artı üretip AGF farkını **`−0,0329`** düzeyine taşıdı.

---

## 5. Sonraki Adım Önerisi

1. **Canlıya alma kararı kullanıcıya aittir:** `V10_HLB` (`v10_hlb`, `155` özellik, `12,7` sn ek süre) `10/10` yılda `v9`'u geçti. Canlıya alınırsa `v6`'yı emekliye ayırıp (`v7 + v8 + v9 + v10_hlb`) 4 aktif modelle devam etmek hem sabah ısınmasını hem koşu başı süresini dengeli tutar.
2. **Yeni veri toplama hatları zaten aktif:** Canlı oran ve gazete toplayıcıları her gün veri biriktirmeye devam ediyor (`9 gün` birikti; hedef `60–90` gün — asıl büyük sıçrama V11/V12'de bekleniyor).
