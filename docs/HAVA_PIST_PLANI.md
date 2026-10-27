# Ganyan — Hava + pist durumu özellikleri şartnamesi

Uygulayıcı: Gemini. İnceleyen: Claude. Tarih: 27.10.2026.
Proje kökü: `~/AndroidStudioProjects/ganyan` (Masaüstü'ndeki eski kopya BOZUK, kullanma). Python: `venv/bin/python`.
İşe başlarken: `git pull`, `git status -s` boş olmalı.

## 0. Amaç ve karar ölçütü

Soru: **Pist durumu ve hava, `v1_agf` modelinin üzerine ölçülebilir bilgi katıyor mu?**
Yöntem: mevcut aylık ileri-yürüyen test (`ganyan/backtest.py`, 2025-07 … 2026-10), aynı aylar, aynı bölme.

- Taban: `v1_agf` (mevcut). Aday: `v2_agf_hava` = `v1_agf` özellikleri + bu belgedeki yeni özellikler.
- Birincil ölçü: koşu başına kazananın log-loss'u; **eşleştirilmiş bootstrap** (koşu bazında, 2000 tekrar) ile
  `ll(v2) − ll(v1)` farkının %95 GA'sı.
- **GEÇTİ:** GA üst sınırı < 0 (v2 anlamlı olarak daha iyi). Ayrıca 1. tercih isabetini raporla (karar ölçütü değil).
- Alt küme raporu (karar değil, açıklama): "ıslak" koşular (§2.4 tanımı) ve "kuru" koşular ayrı ayrı.
- Sonuç ne çıkarsa çıksın dürüstçe yaz; GEÇMEDİ de geçerli bir sonuçtur. Kâr iddiası YOK.

**Önemli:** Günlük ileri test `v1_agf` ile çalışıyor. **`scripts/forward_log.py`'ye, `scripts/daily_job.sh`'ye, launchd'ye
DOKUNMA.** v2 geçse bile ileri teste eklemek kullanıcı kararıdır (§8).

## 1. Keşif (kod yazmadan önce) → `docs/HAVA_PIST_KESIF.md`

### 1.1 Pist durumu CSV'de var mı?
Sonuç CSV'lerinde koşu başlık satırı şöyle: `1. Kosu :   13.00;Maiden/Dişi; 2 Yaşlı İngilizler; 57.00kg; 1400m; Çim;;;;Rekor Derece :1.21.74`.
Pist türünden (`Çim`) sonra boş alanlar var. **`data/raw/results/` altındaki tüm CSV'lerde** (cp1254 / utf-8-sig, mevcut
ayrıştırıcının okuma yolunu kullan) başlık satırını `;` ile böl, 6. alandan sonraki her alanın **farklı değerlerini ve
sayılarını** yaz. Aynısını `data/raw/program/` için yap. Pist durumu (ör. `Islak`, `Ağır`, `Yumuşak`, `Normal`, `Nemli`,
`Sulu`, sayısal çim ölçümü) herhangi bir alanda çıkıyor mu?

### 1.2 CSV'de yoksa TJK HTML'inde var mı?
`ganyan/tjk.py`'deki gün sayfası (`/TR/YarisSever/Info/Page/GunlukYarisSonuclari?QueryParameter_Tarih=`) ve şehir sayfası
(`X-Requested-With: XMLHttpRequest` başlığıyla) **tek bir geçmiş gün için** indir, ham HTML'i `data/raw/html_probe/`
altına kaydet ve koşu başlıklarının çevresinde pist durumu metnini ara (`Pist`, `Islak`, `Ağır`, `Yumuşak`, `Normal`...).
Program sayfasına da bak (pist durumu çoğu zaman yarış sabahı ilan edilir).
`www.tjk.org` yavaş/zaman aşımlı olabilir: tek istek, `timeout=30`, en fazla 3 deneme. Bulamazsan 3 farklı tarih + 2 şehir dene, dur.

### 1.3 Karar dalları (keşif raporuna hangisi olduğunu yaz)
- **(a) CSV'de var** → §2.1 yalnız ayrıştırıcı + yeniden yükleme (indirme yok).
- **(b) Yalnız HTML'de var** → toplam istek sayısını hesapla (gün × şehir). Mevcut `DELAY` ile süreyi tahmin et ve yaz.
  ≤ 3 saat ise arka planda, sırayla, devam ettirilebilir (zaten indirilen HTML'i atla) şekilde backfill yap.
  > 3 saat ise **dur ve kullanıcıya sor**.
- **(c) Hiçbir yerde yok** → Parça A'yı atla; pist ıslaklığını yalnız hava (§2.4 yağış özellikleri) temsil eder.
  Keşif raporunda açıkça "pist durumu verisi bulunamadı" yaz.

Ham değerleri **normalleştirmeden önce** raporda listele (ilk 30 farklı değer + sayıları).

## 2. Parça A — Pist durumu (yalnız 1.3 (a) veya (b) ise)

### 2.1 Şema
`races` tablosuna `track_cond_raw TEXT` ve `track_cond TEXT` kolonları (`ALTER TABLE ... ADD COLUMN`, idempotent: kolon
varsa atla). `ganyan/db.py` upsert'lerine `COALESCE(excluded.x, races.x)` kalıbıyla ekle (mevcut `surface` gibi).

### 2.2 Normalleştirme
`track_cond` ∈ {`kuru`, `normal`, `nemli`, `islak`, `agir`, `yumusak`, `bilinmiyor`} — eşleme tablosunu
`ganyan/track.py` içinde tek sözlük olarak yaz, 1.3'teki ham değerlerin **tamamını** kapsasın; eşleşmeyen değer test
kırmızısı olsun. Kum ve çim için aynı kelime farklı anlam taşıyabilir — `surface`'i de anahtar yap.

### 2.3 Test
`tests/test_track.py`: (1) bir fixture başlık satırından/HTML parçasından ham değerin doğru okunması,
(2) veritabanındaki her `track_cond_raw` değerinin eşlemede olması.

## 3. Parça B — Hava (Open-Meteo)

### 3.1 Hipodrom koordinatları → `ganyan/tracks.py`
`SELECT DISTINCT city FROM races` ile şehir listesini al. Her şehir için hipodromun enlem/boylamını **kaynak göstererek**
yaz (OpenStreetMap veya Wikipedia; her satırda yorum olarak kaynak URL'si). Koordinat uydurma. 3 km hassasiyet yeter
(Open-Meteo ızgarası ~10 km). Testte DB'deki her şehrin sözlükte olduğu doğrulanır.

### 3.2 İndirme → `scripts/fetch_weather.py`
Uç nokta (geçmiş, reanaliz):
```
https://archive-api.open-meteo.com/v1/archive?latitude=..&longitude=..
  &start_date=2024-10-01&end_date=<bugün-6 gün>
  &hourly=precipitation,temperature_2m,relative_humidity_2m,wind_speed_10m
  &timezone=Europe/Istanbul
```
- Şehir başına **tek istek** (2 yıl saatlik veri tek yanıtta gelir), şehirler arası 2 sn bekle, paralel yok.
- Ham JSON'u `data/raw/weather/<city>.json` olarak sakla; dosya varsa yeniden indirme (`--refresh` bayrağı hariç).
- Tablo `weather_hourly(city TEXT, ts TEXT, precip_mm REAL, temp_c REAL, rh REAL, wind_kmh REAL, src TEXT,
  PRIMARY KEY(city, ts))`; `ts` İstanbul yerel saati `YYYY-MM-DDTHH:00`; `src='archive'`.
- Arşivin son ~5 günü boştur/eksiktir (reanaliz gecikmesi) — `end_date = bugün − 6 gün`.

### 3.3 Canlı kullanım notu (bu işte KODLAMA, yalnız belgele)
İleri testte/uygulamada arşiv gecikmeli olduğundan forecast uç noktası (`https://api.open-meteo.com/v1/forecast`,
`past_days=3`) kullanılmak zorunda; bu, eğitimdeki reanaliz verisinden farklı bir kaynak (eğitim/kullanım farkı).
Keşif raporuna 1 paragraf yaz: son 30 gün için iki kaynağın yağış toplamlarını 2–3 şehirde karşılaştır (korelasyon).

**Lisans:** Open-Meteo ücretsiz API'si **ticari olmayan** kullanım içindir. Araştırma için sorun yok; uygulamada
kullanılacaksa ücretli plan/kendi barındırma gerekir — raporda "kullanıcı kararı" olarak işaretle.

## 4. Özellikler → `ganyan/features.py` (mevcut yapıya ekle, mevcut özellikleri değiştirme)

Sızıntı kuralı (mevcut kuralla aynı): bir koşunun özelliği yalnız **`post_time`'dan önce** bilinen veriden üretilir.
Atın geçmiş performansından türeyen özellikler yalnız **o koşudan önceki** koşulardan (`< ref_ts`).

### 4.1 Koşu düzeyi
- `rain_24h`, `rain_72h`: `post_time`'dan önceki 24/72 saatin yağış toplamı (post_time saati dahil DEĞİL).
- `temp_post`, `wind_post`: `post_time`'dan önceki son tam saatin değerleri.
- `track_cond` (Parça A varsa): one-hot, `surface` ile etkileşimli (ör. `kum_islak`). Pist durumu yarıştan önce
  ilan edildiği varsayımıdır — keşifte program sayfasında görüldüyse "doğrulandı", yoksa raporda "varsayım" yaz.

### 4.2 "Islak" tanımı (§2.4 ve alt küme raporu için tek yer)
`wet = (track_cond in {nemli, islak, agir, yumusak})` Parça A varsa; yoksa `wet = rain_72h >= 5.0` (mm).
Eşik sabit; raporda kaç koşunun ıslak sayıldığını yaz.

### 4.3 At düzeyi (asıl beklenen kazanç burada)
- `horse_wet_delta`: atın geçmiş **ıslak** koşulardaki ortalama normalize derecesi − **kuru** koşulardaki ortalama
  (normalize derece: mevcut özellik modülündeki derece normalizasyonunu kullan). Az örneğe karşı büzme:
  `delta_shrunk = delta · n_wet / (n_wet + 5)`; ıslak geçmişi yoksa 0, ayrıca `horse_n_wet` kolonu.
- `sire_wet_delta`: aynı hesap babanın tüm yavruları üzerinden (yalnız `< ref_ts`), büzme sabiti 20.
- Bu iki özellik yalnız o koşu ıslaksa anlamlıdır → modele `wet · horse_wet_delta` ve `wet · sire_wet_delta`
  etkileşimlerini de ver.

### 4.4 Testler → `tests/test_leakage.py`'ye ekle
1. `post_time`'dan sonraki bir saatte yapay 50 mm yağış eklenince `rain_24h` değişmemeli.
2. Atın **gelecekteki** bir ıslak koşusu `horse_wet_delta`'yı değiştirmemeli.
3. Şehir/saat verisi eksikse özellik `NaN` olmalı (model bunu kaldırabiliyor — HistGradientBoosting), hata değil.

## 5. Değerlendirme → `scripts/run_hava_backtest.py` → `reports/HAVA_PIST.md`

- Mevcut walk-forward fonksiyonunu kullan; yalnız özellik setini değiştir. Hiperparametreler `v1_agf` ile aynı.
- Tablo: ay ay `v1_agf` / `v2_agf_hava` 1. tercih ve log-loss; toplamda eşleştirilmiş bootstrap farkı + %95 GA.
- Alt kümeler: ıslak / kuru koşular (koşu sayısıyla).
- Özellik önemi: permutation importance (test ayları üzerinde), yeni özelliklerin sırası.
- Karar satırı: §0 ölçütüne göre **GEÇTİ / GEÇMEDİ**, tek cümle gerekçe.
- Kupon backtest'ini (bütçeli) bu işte ÇALIŞTIRMA — önce olasılık kalitesi ölçülür.

## 6. Tuzaklar

1. **Günlük işlerle çakışma:** launchd işleri `data/.lock` ile korunuyor. Uzun indirme/yazma işlerini **10:30–14:30 ve
   00:30–01:30** arasında çalıştırma. `data/.lock`'u kendin OLUŞTURMA (günlük iş atlanır). SQLite bağlantılarında
   `timeout=30`.
2. **Saat dilimi:** Open-Meteo'ya `timezone=Europe/Istanbul` ver; `post_time` zaten yerel. Yaz/kış saati 2016'dan beri
   Türkiye'de yok (sabit +03) — yine de `ts` eşleşmesini testle.
3. **Şehir adları:** DB'deki şehir yazımı (`İstanbul`, `Şanlıurfa` vb.) ile `tracks.py` anahtarları birebir aynı olsun.
4. **Gece yarışları:** yaz aylarında 23:30'a kadar koşu var; "son tam saat" hesabını gün sınırında test et.
5. **Çok kolon = gürültü:** yeni özellikleri §4'teki listeyle sınırla; ek hava değişkeni (basınç, nem türevleri) ekleme.
6. TJK'ye nazik ol: paralel istek yok, mevcut `DELAY`.

## 7. Commit dilimleri (her biri `pytest -q` yeşil + `git push origin main`; `git add` yalnız açık yollar)

1. `docs(kesif): pist durumu ve hava kaynak keşfi` — `docs/HAVA_PIST_KESIF.md` (+ gerekiyorsa küçük keşif betiği `tools/`)
2. `feat(hava): hipodrom koordinatları + Open-Meteo arşiv indirme + weather_hourly` — `ganyan/tracks.py`,
   `scripts/fetch_weather.py`, `ganyan/db.py`, testler
3. `feat(pist): pist durumu ayrıştırma + normalleştirme` — yalnız 1.3 (a)/(b) ise
4. `feat(model): hava/pist özellikleri + sızıntı testleri` — `ganyan/features.py`, `tests/test_leakage.py`
5. `docs(rapor): hava/pist özellikleri ileri-yürüyen test sonucu` — `scripts/run_hava_backtest.py`, `reports/HAVA_PIST.md`

`data/` git'e girmez. `git add -A` / `git add .` YOK.

## 8. Yapılmayacaklar / kullanıcı kararı

- `forward_log.py`, `daily_job.sh`, `ops/`, launchd: dokunma. v2'yi ileri teste eklemek (ayrı `model_version` olarak
  paralel kayıt) **kullanıcı onayıyla** ayrı iş.
- Open-Meteo'nun uygulamada (ticari) kullanımı: kullanıcı kararı.
- Bahis yok; derspilot reposuna yazma; bülten fotoğraflarını veri olarak kullanma.

## 9. Final rapor (Gemini → kullanıcı, tek mesaj)

- Keşif sonucu: 1.3'te hangi dal, ham pist değerleri tablosu (ilk 30).
- Şehir sayısı, koordinat kaynakları, indirilen saat sayısı, eksik saat oranı.
- `reports/HAVA_PIST.md`'den: toplam log-loss farkı + %95 GA, 1. tercih farkı, ıslak/kuru alt kümeleri, karar satırı.
- `git log --oneline -6`, `git status -s` (boş).
