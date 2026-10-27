# GANYAN — Mobil uygulamadan önceki yol haritası (uygulama şartnamesi)

> **Kime:** Bu planı kodlayacak ajan (Gemini / Antigravity).
> **Hazırlayan:** Claude, 26.10.2026. **Repo:** `~/AndroidStudioProjects/ganyan` → `github.com/nino0435/ganyan-model` (private, `main`).
> Kararlar verildi (§1); tartışma yok, tahmin yürütme yok. Belirsiz olan her şey §10 "Doğrula"da; orada yazanı
> **ölçerek** çöz, uydurma. Bu proje **derspilot ile ilgisiz**: derspilot reposuna dokunma.

---

## 0. Nereden geliyoruz, ne kuruyoruz

**Bilinenler (ölçüldü, 26.10.2026):**
- 26.10.2024–25.10.2026 arası 728 yarış günü / 12.781 koşu / 123.847 at-koşu kaydı indirildi (`hist/`).
- Basit model tek başına AGF favorisini **yenemiyor** (1. tercih isabeti %27 vs %33). AGF eklenince kazanan bulmada
  **eşit**, olasılık kalitesinde çok az iyi (log-loss 1,8347 vs 1,8409).
- Umut veren tek sinyal: **aynı maliyetle kupon sıralaması**. Her ayağa 3 at → 6/6 tutan: Model+AGF 66/743, AGF 53/743.
  Anlamlılık testi yok; iki test dönemi iç içeydi (bağımsız değil). → Bu planın Faz 2'si bunu düzgün ölçer.
- Koşu öncesi veri var: TJK **program CSV'si** (geçmiş ve gelecek günler) ve gün içinde güncellenen **AGF**.

**Mobil uygulamadan önce kurulacak şey:** Python ile bir "veri + değerlendirme + öneri motoru".
Mobil uygulama sonra bunun ürettiği JSON'ları okuyacak (Faz 4). Sunucu yok, deploy yok.

| Faz | Çıktı | Kapı (geçmeden sonraki faza "iddia" taşınmaz) |
|---|---|---|
| 1 | Paket + SQLite veritabanı + program/sonuç ayrıştırıcıları + günlük güncelleme + testler | `pytest` yeşil, sayım ve çapraz kontroller tutuyor |
| 2 | Sızıntı testi, aylık ileri-yürüyen test, ikramiye tahmini, **kupon dağıtıcı** ve backtest raporu | §3.6 go/no-go |
| 3 | Her yarış günü koşudan önce tahmin kaydı (ileri test) | Kayıt aksamadan birikiyor |
| 4 | Uygulamanın okuyacağı JSON sözleşmesi + dışa aktarıcı | JSON şema testleri yeşil |

---

## 1. Kesin kararlar (değiştirme)

- **K1 Ortam:** Python 3.14 + mevcut `venv/`. Bağımlılıklar yalnız `numpy pandas scikit-learn pytest`
  (`venv/bin/pip install -q pytest`). LightGBM, veritabanı sunucusu, web çatısı **yok**.
- **K2 Depolama:** Tek dosya SQLite: `data/ganyan.db` (standart `sqlite3`). Ham dosyalar `data/raw/results/` ve
  `data/raw/program/` altında. `data/` gitignore'da. Mevcut `hist/` içeriği `data/raw/results/`'a **taşınır**
  (yeniden indirme yok).
- **K3 Paket yapısı:**
  ```
  ganyan/            tjk.py  parse_results.py  parse_program.py  db.py  features.py  model.py
                     payout.py  allocator.py  backtest.py  export.py
  scripts/           backfill.py  update_daily.py  snapshot_agf.py  run_backtest.py  forward_log.py  forward_report.py  export_day.py
  tests/             fixtures/  test_parse_results.py  test_parse_program.py  test_leakage.py  test_allocator.py  test_payout.py  test_export.py
  reports/           BACKTEST.md  FORWARD.md   (üretilen raporlar; commit edilir)
  ```
  `tools/` altındaki eski betikler **silinmez**; kodları pakete taşınır, `tools/` olduğu gibi kalır (geçmiş ölçüm için).
- **K4 At kimliği:** `horse_key = baba|anne|doğum_yılı` (doğum yılı = yarış yılı − yaş). Görünen ad için takı kodları
  temizlenmiş `name` ayrıca saklanır (§2.2).
- **K5 Program numarası (`prog_no`):** yalnız **program CSV'sinin ilk sütunundan** (= program sayfasındaki `SiraId`).
  Sonuç CSV'sinin ilk sütunu **varış sırasıdır**, program numarası değildir.
- **K6 Nezaket:** TJK'ye tek akış, istekler arası 0,5 sn; `www.tjk.org` cevap vermezse `medya-cdn.tjk.org`'a düş
  (mevcut `download_hist.py`'deki mantık). Paralel istek yok.
- **K7 Model:** `tools/model.py`'deki HistGradientBoosting ayarları ve özellik listesi **v1** olarak sabit. Hiperparametre
  avı yok. Yeni özellik yalnız §3.1 sızıntı testinden geçerse eklenir.
- **K8 Para birimi:** Altılı birim fiyatı tablosu `{"2026-01-01": 1.25}`. Bilinmeyen dönemde para hesabı
  **yapılmaz** (yalnız isabet). İkramiye CSV'deki değer = **1 birim başına** (varsayım, §10).
- **K9 Saat dilimi:** Europe/Istanbul. Veritabanında tarih ISO (`2026-10-24`), saat `HH:MM`.

---

## 2. Faz 1 — Veri katmanı

### 2.1 Şema (`ganyan/db.py`, `init_db(path)` idempotent)
```sql
races(race_id TEXT PRIMARY KEY,          -- '2026-10-24_Ankara_3'
      date TEXT, city TEXT, race_no INT, post_time TEXT, yg_no INT,
      cls TEXT, breed TEXT, distance INT, surface TEXT, status TEXT)  -- status: 'scheduled'|'result'|'cancelled'
runners(race_id TEXT, prog_no INT, horse_key TEXT, name TEXT, name_raw TEXT, age INT, sex TEXT,
        sire TEXT, dam TEXT, weight REAL, jockey TEXT, owner TEXT, trainer TEXT, gate INT, hp REAL,
        son6 TEXT, kgs INT, s20 INT, best_time_s REAL,                -- programdan
        finish INT, time_s REAL, ganyan REAL, agf_close REAL, agf_close_rank INT, scratched INT,  -- sonuçtan
        PRIMARY KEY(race_id, horse_key))
altili(date TEXT, city TEXT, which INT, start_race INT, end_race INT, legs TEXT, payout REAL,
       PRIMARY KEY(date, city, which))   -- legs: JSON [[5],[8],[6],[2],[10],[7]]
bets(race_id TEXT, bet TEXT, combo TEXT, payout REAL)          -- GANYAN, İKİLİ, ÜÇLÜ BAHİS, ...
agf_snapshots(race_id TEXT, prog_no INT, captured_at TEXT, agf_pct REAL, agf_rank INT, ganyan_live REAL)
predictions(race_id TEXT, prog_no INT, model_version TEXT, created_at TEXT, p_win REAL, agf_used REAL,
            PRIMARY KEY(race_id, prog_no, model_version))
```
Upsert: program ve sonuç **ayrı geldiği** için `runners` satırı `(race_id, horse_key)` ile birleşir; sonuç gelince
sonuç sütunları güncellenir, program sütunları korunur (ve tersi).

### 2.2 Sonuç ayrıştırıcı (`ganyan/parse_results.py`)
`tools/parse_hist.py::parse_file` mantığını taşı, şunları ekle:
- Başlık satırından `yg_no` (`Ankara;(77. Yarış Günü);24/10/2026` → 77) ve koşu saati (`1. Kosu :   13.00;...` → `13:00`;
  isimli koşu: `4. Kosu :  ÖMER KAYA KOŞUSU 14.30;...` → `14:30`).
- Bahis satırlarından `bets` ve `altili`: `GANYAN(n)`, `1. 6'LI GANYAN(a/b/c/d/e/f) :X TL`, `2. 6'LI ...`.
  6'lı satırının geçtiği koşu = bitiş koşusu; başlangıç = bitiş − 5. Bir ayakta virgüllü numaralar (`2,3,7,10`) olabilir → liste.
  Satır başında eküri metni olabilir: `[(2)LOVE SEA,(6)JAN AQUA,] eküridir.GANYAN(8) :2,90 TL` → GANYAN = 8.
  `5'Lİ/4'LÜ/3'LÜ GANYAN` ve `ÇİFTE` satırlarını GANYAN sanma (önündeki `'L` veya sayı+nokta kontrolü).
- Görünen ad: sondaki takı kodlarını sil. Kod kümesini veriden çıkar: tüm adlarda **son token**, uzunluğu ≤ 3, ve
  ≥ 300 farklı atta son token olarak geçiyorsa kod say. Kümeyi `EQUIP_CODES` sabiti olarak koda yaz, testle sabitle.
  `(Koşmaz)` her zaman silinir.
- Kazananı olmayan koşu (`winners == 0`) → `status='cancelled'` (ör. 22.10.2026 Ankara/İzmir/Bursa).

### 2.3 Program ayrıştırıcı (`ganyan/parse_program.py`) — YENİ
Dosya: `https://medya-cdn.tjk.org/raporftp/TJKPDF/{YYYY}/{YYYY-MM-DD}/CSV/GunlukYarisProgrami/{DD.MM.YYYY}-{Şehir}-GunlukYarisProgrami-TR.csv`
(şehir Türkçe karakterli, URL'de yüzde-kodlanır). Biçim (gerçek örnek, 27.10.2026 Adana):
```
Adana;(21. Yarış Günü);27/10/2026
1. Kosu :   14.30;Handikap 15 /H2; 2 Yaşlı İngilizler; kg; 1200m; Sentetik;;;;Rekor Derece :1.13.39
İkramiye;;;;;Yetiştirici Primi;;;;
1.)490.000 TL;...
At No;At İsmi;Yaş;Orijin(Baba);Orijin(Anne);Kilo;Jokey Adı;Sahip Adı;Antrenör Adı;St;AGF;H;Son 6 Yarış;KGS;s20;EnİyiDerece
1;ETIQUETTE KG K DB;2y d  e;AMERİKALI;LASER GIRL;58,5;Ö.YILDIRIM;KENAN ÖZDEMİR;E.KOÇAK;1;;56;K2K1Ç9K6K1K6;21;19;
```
- `At No` = `prog_no`. `AGF` koşudan önce boş olabilir; gün içinde `%2.84(9)` biçiminde dolar.
- `Son 6 Yarış`: (pist harfi + derece) dizisi; harfler `K`=kum, `Ç`=çim, `S`=sentetik; derece 1–2 hane olabilir
  (`Ç10`), `0` görüldü (`K0`) → anlamı §10'da doğrulanacak; o zamana dek `0` = "ilk 9 dışı / tamamlamadı" say.
  Ayrıştırma: `re.findall(r'([KÇS])(\d{1,2})', s)` → `[('K',2),('K',1),('Ç',9),...]`. Ham metin de saklanır.
- `KGS`, `s20`: int (boş → NULL). `EnİyiDerece`: `1:27.57` → saniye.
- `St` `9 - DS` → 9. `Kilo` `57 +0.70` → 57.7 (sonuçtaki gibi).

### 2.4 İndirme ve backfill (`ganyan/tjk.py`, `scripts/backfill.py`)
- `tjk.py`: `get(url)` (mevcut yeniden deneme + CDN düşüşü), `results_csv_url(date, city)`, `program_csv_url(date, city)`,
  `domestic_cities(date)` (gün sayfası; yoksa 10 yerli şehir listesi: İstanbul, İzmir, Adana, Bursa, Ankara, Antalya,
  Şanlıurfa, Elazığ, Kocaeli, Diyarbakır).
- `backfill.py --start 2024-10-26 --end 2026-10-25`: (1) `hist/` CSV'lerini `data/raw/results/`'a taşı (git mv değil,
  `hist/` gitignore'da; düz taşıma), (2) **aynı tarih+şehirler için program CSV'lerini indir** (~1.500 dosya, ~25 dk,
  arka planda), (3) hepsini DB'ye yükle. Var olan dosyayı yeniden indirme.

### 2.5 Günlük güncelleme (`scripts/update_daily.py --date YYYY-MM-DD`)
- `date+1` (yarın) program CSV'leri → `races.status='scheduled'` + runners program sütunları.
- `date` ve `date-1` sonuç CSV'leri → sonuç sütunları, `bets`, `altili`, `status`.
- İdempotent: iki kez çalıştırınca DB değişmez (test et). **Zamanlayıcı kurma** (cron/launchd = kullanıcı kararı, §9).

### 2.6 Canlı AGF anlık görüntüsü (`scripts/snapshot_agf.py --date YYYY-MM-DD`)
- O günün program CSV'sini **önbelleği atlatarak** yeniden indir (`?t=<unix>` sorgu parametresi ekle) → her koşucu için
  `agf_pct`, `agf_rank` → `agf_snapshots` (captured_at = şimdi, ISO, Europe/Istanbul).
- Yedek kaynak: program sayfası HTML'i (`/TR/YarisSever/Info/Sehir/GunlukYarisProgrami?SehirId=..&QueryParameter_Tarih=..&SehirAdi=..&Era=today`,
  **`X-Requested-With: XMLHttpRequest` başlığı şart**). Hücre sınıfları: `gunluk-GunlukYarisProgrami-SiraId` (= prog_no),
  `-AGFORAN` (`%15(3)`, **tam sayıya yuvarlı**), `-Gny` (canlı ganyan oranı, `31,90`). Adın yanındaki `(8)` program
  numarası **değil** (doğrulandı: `ARES GOLD (8)` → CSV'de At No 1, SiraId 1).

### 2.7 Testler (Faz 1)
Fixture'lar repoda hazır: `tests/fixtures/results_2026-10-24_Ankara.csv`, `tests/fixtures/program_2026-10-27_Adana.csv`.
`test_parse_results.py` — **birebir beklenen değerler:**
- yg_no 77; koşu sayısı 10; 1. koşu `13:00`, `Maiden/Dişi`, İngiliz, 1400, Çim, 10 koşucu.
- 1. koşu kazananı `IMPERIAL GLOIRE`: finish 1, agf_close 2.99, agf_close_rank 6, ganyan 17.0, time_s 86.56, gate 5.
- `QUEEN OF UNION`: weight 57.7, gate 10. 3. koşuda `ELYSIUM` scratched=1. 2. koşu GANYAN = 8 (eküri satırı).
- altili: which=1 → start 1, end 6, legs `[[5],[8],[6],[2],[10],[7]]`, payout 292238.81;
  which=2 → start 5, end 10, legs `[[10],[7],[4],[5],[1],[5]]`, payout 141503.56.
`test_parse_program.py`:
- 1. koşu `14:30`, `Handikap 15 /H2`, İngiliz, 1200, Sentetik. prog 1 `ETIQUETTE`: weight 58.5, jockey `Ö.YILDIRIM`,
  gate 1, hp 56, agf NULL, son6 `[('K',2),('K',1),('Ç',9),('K',6),('K',1),('K',6)]`, kgs 21, s20 19, best_time NULL.
- prog 2 `ROSE WARRIOR` son6 5 elemanlı (`Ç1Ç6Ç2S1K4`). prog 3 `KING OF LINGO`: gate 8, hp 53, kgs 34, s20 18.
**Çapraz kontrol (backfill sonrası, script olarak):** her sonuçlanmış koşuda kazananın `horse_key`'i programdaki
`prog_no` ile eşleştirilince `GANYAN(n)` ile **aynı** olmalı. Uyuşmazlık oranını yaz; %1'in üstündeyse dur, nedenini bul.
**Kabul:** `pytest -q` yeşil; DB'de ≈12.781 koşu / ≈123.847 koşucu (iptaller hariç sayım farkı açıklanmış).

---

## 3. Faz 2 — Değerlendirme motoru

### 3.1 Özellikler + sızıntı testi (`ganyan/features.py`, `tests/test_leakage.py`)
- `tools/model.py`'deki özellik kodunu fonksiyonlara taşı: `build_features(runners_df) -> df`.
- Program kaynaklı yeni özellikler (koşudan önce bilinir): `son6` türevleri (son derece, ortalama derece, aynı pistteki
  oran), `kgs`, `best_time_s` (aynı mesafe/pist medyanına göre), `s20`.
- **Sızıntı testi (zorunlu, kritik):** Bir D günü seç (ör. 2026-06-14). (a) tüm veriyle özellik üret; (b) D'den sonraki
  tüm satırları sil, D günündeki satırların `finish, time_s, ganyan, agf_close` sütunlarını NaN yap, yeniden üret.
  D günü satırlarının (AGF hariç tüm) özellikleri **birebir eşit** olmalı. Hız puanı medyanları sabit bir referans
  döneminden hesaplanır (parametre), testte aynı referans verilir.

### 3.2 Aylık ileri-yürüyen test (`ganyan/backtest.py::walk_forward`)
- Her ay M (2025-07 … 2026-10) için: eğitim = 2025-01-01 ≤ tarih < M'nin ilk günü; tahmin = M ayı. Aylar **örtüşmez**.
- İki model: `v1_noagf` (AGF'siz), `v1_agf` (+ kapanış AGF payı). Olasılıklar koşu içinde normalize.
- Çıktı: her koşucu için `p` → `reports/` için tablo: ay ay 1. tercih isabeti (model / AGF favorisi / ganyan favorisi),
  log-loss; tüm dönem için koşu-eşli bootstrap (2000 örnek) %95 GA.
- **Uyarı (rapora yaz):** tarihsel AGF kapanış değeri; canlıda koşudan önce alınan AGF daha az bilgi içerir → canlı
  performans biraz düşük beklenir. Bunu Faz 3 ölçecek.

### 3.3 İkramiye tahmini (`ganyan/payout.py`)
- Her tarihsel altılı için `x = Σ_j log(kazananın kapanış AGF payı_j)` (pay = agf / koşudaki agf toplamı), `y = log(ikramiye)`.
- Model: `y = a_şehir + b·x` (şehir başına sabit, ortak eğim). Eğitim/test ileri-yürüyen (aynı aylık düzen).
- Rapor: test R², medyan mutlak % hata. Kullanım: herhangi 6 kazanan kombinasyonu için tahmini ikramiye
  `exp(a_şehir + b·Σ log pay)`. `b < 0` beklenir (az oynanan kazanan → büyük ikramiye); değilse dur ve raporla.
- `tests/test_payout.py`: yapay veride (bilinen a, b) parametreleri ±%5 içinde geri bulur.

### 3.4 Kupon dağıtıcı (`ganyan/allocator.py`) — ana ürün özelliği
Girdi: 6 ayak, her ayakta `[(prog_no, p, agf_pay)]` (p koşu içinde toplam 1), `budget_tl`, `unit_tl`.
Kısıt: `maliyet = unit_tl × Π k_j ≤ budget_tl`, her ayakta k_j ≥ 1.

**Amaç A — isabet:** `Π_j P_j` en büyük, `P_j = Σ_{seçilen} p`.
Açgözlü algoritma (deterministik):
1. Her ayakta en yüksek p'li atı seç (k_j = 1). Maliyet bütçeyi aşıyorsa boş kupon döndür.
2. Döngü: her ayak j için sıradaki en iyi atı eklemenin kazancı `g_j = log(P_j + p_next) − log(P_j)`, maliyet çarpanı
   `c_j = log((k_j+1)/k_j)`; yeni maliyet bütçeyi aşmayanlar arasında `g_j / c_j` en büyük olanı ekle
   (eşitlikte küçük ayak indeksi). Eklenecek aday kalmayınca dur.
**Amaç B — beklenen değer:** §3.3 modeliyle tutan kombinasyonun ikramiyesi `e^{a} Π pay_j^{b}` olduğundan beklenen
dönüş çarpanlara ayrılır: `E = e^{a} Π_j V_j`, `V_j = Σ_{seçilen} p_i · pay_i^{b}`. Aynı açgözlü döngü, kazanç
`log(V_j + v_next) − log(V_j)` ile; ayrıca her adımda `E − maliyet` düşüyorsa durma seçeneği. (Atlar ayak içinde
`p·pay^b`'ye göre sıralanır.)
**Kıyas yöntemleri (aynı bütçe):** (i) sabit k: bütçeye sığan en büyük `k^6` (ör. 1.000 TL → k=3, 729 komb.);
(ii) AGF sırasıyla Amaç A; (iii) model (v1_agf) ile Amaç A; (iv) model ile Amaç B.
**`tests/test_allocator.py`:** bütçe hiç aşılmaz; bütçe artınca P (A) azalmaz; tek ayakta tek atlık p=1 ise o ayak hep
k=1 kalır; elle hesaplanmış küçük örnek (2 ayak, 3'er at, bütçe 4 birim) beklenen seçimi verir.

### 3.5 Kupon backtest'i (`scripts/run_backtest.py` → `reports/BACKTEST.md`)
- §3.2'nin ileri-yürüyen tahminleriyle, her test altılısı için 4 yöntem × bütçeler {250, 500, 1.000, 2.500, 5.000 TL}.
- Tutma: seçilen prog_no'lardan biri **resmi ayak kümesinde** (altili.legs) ise ayak tuttu (koşmayan at kuralı böylece
  doğru işler). 6/6 → ikramiye = `altili.payout` (birim başına, K8).
- Para hesabı **yalnız 2026** altılılarında (birim 1,25 TL). Öncesinde yalnız isabet.
- Rapor tabloları: yöntem × bütçe → 6/6 oranı, ortalama ayak, toplam maliyet, toplam dönüş, ROI, aylık ROI std;
  sabit-k'ya karşı altılı-eşli bootstrap fark ve %95 GA.

### 3.6 Go / no-go kapısı (rapora açıkça yaz)
- **"Akıllı kupon" iddiası** ancak: 5 bütçenin **en az 3'ünde** (iii) Amaç A'nın 6/6 oranı (i) sabit-k'dan yüksek **ve**
  %95 GA alt sınırı > 0. Sağlanmazsa uygulamada özellik "maliyet + olasılık hesaplayıcı" olarak konumlanır.
- **ROI iddiası** (kâr) hiçbir koşulda bu planla verilmez; yalnız raporlanır.

---

## 4. Faz 3 — İleri test kaydı (kanıtlanabilir geçmiş)
- `scripts/forward_log.py --date YYYY-MM-DD`: (1) `snapshot_agf` çalıştır, (2) dünkü veriye kadar eğitilmiş v1_agf ile
  o günün tüm koşuları için `p` üret, (3) `predictions`'a `created_at` ile yaz. **Koşu başladıktan sonra yazılan tahmin
  geçersiz:** `created_at < post_time` olmayan satırlar raporda sayılmaz.
- İlk koşudan en geç 30 dk önce çalıştırılmalı. Gece koşulu hipodromlar için (Şanlıurfa/Diyarbakır/Elazığ ~18:00 sonrası)
  gün içinde ikinci kez çalıştırılabilir (aynı model_version için üzerine yazmaz, **ilk kayıt** geçerlidir).
- `scripts/forward_report.py` → `reports/FORWARD.md`: kayıt başlangıcından bugüne 1. tercih isabeti, log-loss,
  AGF-anlık favorisine karşı fark, altılı sabit-k vs Amaç A (yalnız kayıtlı tahminlerle).
- Zamanlama (cron/launchd) **kurulmaz**; komutu README'ye yaz, kullanıcı karar verir.

---

## 5. Faz 4 — Uygulama veri sözleşmesi (JSON, sunucusuz)
`scripts/export_day.py --date YYYY-MM-DD` → `data/export/YYYY-MM-DD/`:
- `index.json`: `{"date","generated_at","model_version","cities":[{"city","yg_no","races":[{"race_id","race_no","post_time","cls","breed","distance","surface","field_size","status"}],"altili":[{"which","races":[...]}]}]}`
- `race_<race_id>.json`: `{"race":{...},"runners":[{"prog_no","name","age","sex","jockey","trainer","weight","gate","hp","son6":[["K",2],...],"kgs","best_time_s","agf_live","agf_live_rank","p_model","form":{"starts","wins","last_finish"}}]}`
  — sonuçlandıysa `finish`, `ganyan` da eklenir.
- `payout_model.json`: `{"a_by_city":{...},"b":...,"trained_through":"YYYY-MM-DD"}` — uygulama kuponu **cihazda**
  hesaplar (§3.4 Amaç A/B aynı algoritma, Dart'a taşınacak). Bu yüzden algoritma deterministik ve testli olmalı.
- `tests/test_export.py`: her dosya geçerli JSON, zorunlu alanlar var, `p_model` koşu içinde toplam 1 (±1e-6).
- Gösterim kuralları uygulamanın işi; JSON'da tarih ISO kalır.

---

## 6. Commit dilimleri (her biri ayrı commit + `git push origin main`)
1. `feat(veri): paket iskeleti, SQLite şeması, sonuç ayrıştırıcı + testler`
2. `feat(veri): program ayrıştırıcı + testler`
3. `feat(veri): backfill (program CSV'leri) + günlük güncelleme + çapraz kontrol`
4. `feat(veri): canlı AGF anlık görüntüsü`
5. `feat(model): özellik modülü + sızıntı testi`
6. `feat(model): aylık ileri-yürüyen test`
7. `feat(model): ikramiye tahmini + testler`
8. `feat(kupon): kupon dağıtıcı (Amaç A/B) + testler`
9. `docs(rapor): kupon backtest raporu (reports/BACKTEST.md)`
10. `feat(ileri-test): tahmin kaydı + rapor`
11. `feat(export): uygulama JSON sözleşmesi + testler`
Her committen önce `venv/bin/python -m pytest -q` yeşil olmalı. `git add -A` / `git add .` kullanma; dosya yollarını tek tek ver.

---

## 7. Tuzaklar (her biri bu veride gerçekten görüldü)
1. Sonuç CSV'sinde `At No` = **varış sırası**; program CSV'sinde `At No` = **program numarası**.
2. At adında takı kodları (`OĞUZHANTAY KG DB SK`) ve `(Koşmaz)`; adla eşleştirme yapma, `horse_key` kullan.
3. `Kilo` `57 +0.70` (topla), `St` `10 - DS` (ilk sayı), AGF sonuçta ondalıklı `%2.99(6)`, canlı HTML'de tam sayı `%15(3)`.
4. 6'lı ayağında çoklu numara (`2,3,7,10`) = koşmayan atlar favoriye sayılmış; tutma kontrolü bu kümeyle yapılır.
5. Ölü yarış (aynı koşuda iki `finish=1`) ve iptal koşular (kazanansız) değerlendirmeden çıkar; altılısı da.
6. Şehir adları Türkçe karakterli (URL'de yüzde-kodla). Yabancı/“Karma” hipodromlarda `Y.G.` yok → alınmaz.
7. `www.tjk.org` zaman zaman zaman aşımı veriyor → CDN düşüşü; şehir HTML'i `X-Requested-With` başlığı ister.
8. CDN önbelleği: canlı AGF için sorgu parametresiyle önbellek atlat; iki indirme arasında değer değişiyor mu kontrol et.
9. Tarihsel AGF/ganyan **kapanış** değeri; özellik olarak yalnız `v1_agf`'de ve yalnız AGF; ganyan kapanışı asla özellik değil.
10. Değer bahsi / altılı ROI'si birkaç büyük ikramiyeyle sallanıyor (önceki ölçüm: +%60 → −%25). Tek dönemden sonuç çıkarma.
11. 22.10.2026 gibi iptal günleri: sonuç CSV'si var ama kazanan yok.

## 8. Yapılmayacaklar
Mobil uygulama kodu; Firebase/sunucu/deploy; bahis sitesi entegrasyonu, hesap açma, bahis; bülten fotoğrafları ve bülten
tahminlerinin veri olarak kullanımı (telif); paralel/yoğun istek; test dönemine göre ayar avı; cron/launchd kurulumu;
derspilot reposuna herhangi bir değişiklik.

## 9. Kullanıcı kararı bekleyenler (Gemini sormaz, beklemez; plan bunlarsız ilerler)
TJK verisinin ticari kullanım izni; şirket ve ayrı geliştirici hesabı; marka adı; gelir modeli; günlük işlerin otomatik
zamanlanması (hangi makinede, hangi saatte).

## 10. Doğrula (ölçerek çöz, rapora yaz)
- `Son 6 Yarış` içindeki `0` derecenin anlamı (10+ mı, tamamlamadı mı): 20 örneği sonuç tablosundaki gerçek derecelerle karşılaştır.
- `KGS` = son koşudan beri gün mü? (`date − önceki yarış tarihi` ile karşılaştır.) `s20` anlamı (20 üzerinden form puanı?).
- Program CSV'sindeki AGF'nin gün içinde ne sıklıkla güncellendiği ve CDN önbelleğinin buna izin verip vermediği.
- Geçmiş program CSV'lerindeki AGF'nin kapanış değeriyle aynı olup olmadığı (sonuç CSV'siyle karşılaştır).
- Altılı ikramiyesinin 1 birim başına yazıldığı ve 2026 birim fiyatının 1,25 TL olduğu (tek haber kaynağı) — TJK/United Racing
  sayfalarında resmi ifade bulunursa linkini rapora ekle; bulunamazsa "varsayım" diye bırak.

## 11. Bitince kullanıcıya rapor (tek mesaj)
- Faz 1: DB sayıları, çapraz kontrol uyuşmazlık oranı, test sayısı.
- Faz 2: ileri-yürüyen sonuç (model vs AGF, GA'lı), ikramiye modeli R² ve hata, **go/no-go kararı** (hangi bütçelerde geçti).
- Faz 3: kayıt başladığı tarih ve şimdiye kadarki kayıt sayısı.
- Faz 4: örnek bir günün export klasörü.
- Açık kalan "Doğrula" maddeleri.
