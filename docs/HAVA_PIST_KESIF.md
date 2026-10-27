# Ganyan — Pist Durumu ve Hava Verisi Kaynak Keşfi (§1, §3.3)

## 1. CSV Dosyalarında Pist Durumu Taraması (§1.1)

`tools/probe_track_cond.py` betiğiyle `data/raw/results/` altındaki **1.525** sonuç CSV dosyasındaki **12.797** koşu başlık satırı ve `data/raw/program/` altındaki **1.529** program CSV dosyasındaki **12.849** koşu başlık satırı `;` ayracıyla bölünerek pist türünden (`Çim`, `Kum`, `Sentetik`) sonraki tüm alanlar taranmıştır:

- **Sonuç CSV'leri (`data/raw/results/`):**
  - 6. alan (`0-index 5`, pist türü): `Kum` (`7.700`), `Çim` (`3.171`), `Sentetik` (`1.926`).
  - 7., 8. ve 9. alanlar (`0-index 6, 7, 8`): `12.797` satırın **tamamında boş** (`""`).
  - 10. alan (`0-index 9`): Yalnızca `Rekor Derece :...` (`12.404` dolu, `393` boş).
  - Koşucu satırları dışındaki satırlarda (`Islak`, `Ağır`, `Yumuşak`, `Normal`, `Nemli`, `Sulu` vb.) yalnız koşu sınıfı adı (`Normal` kelimesi geçen koşu şartları) bulunmuş, pist durumu bilgisine rastlanmamıştır.
- **Program CSV'leri (`data/raw/program/`):**
  - 6. alan (`0-index 5`, pist türü): `Kum` (`7.727`), `Çim` (`3.196`), `Sentetik` (`1.926`).
  - 7. alan ve sonrası: Yalnızca `İkramiye` ve `Prim` alanları yer almakta, pist durumu yer almamaktadır.

**Sonuç (§1.1):** TJK'nin sonuç ve program CSV dosyalarında pist durumu (`Normal`, `Yumuşak`, `Islak`, `Ağır`, `Nemli`, `Sulu` veya sayısal çim ölçümü) **yoktur**.

---

## 2. TJK HTML Sayfalarında Pist Durumu Keşfi ve Karar Dalı (§1.2, §1.3)

`data/raw/html_probe/` altına indirilen TJK günlük sonuç ve program şehir sayfalarında (`https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukYarisSonuclari?SehirId=...&QueryParameter_Tarih=...&SehirAdi=...`, `X-Requested-With: XMLHttpRequest` başlığıyla) `<div class="conditions-race">` bloğu içinde pist durumu ve hava bilgisinin açıkça yer aldığı doğrulanmıştır:

```html
<div class="conditions-race">
    <span class="raceWeatherGreen">Çim: Yumuşak 3,7</span>
    <span class="raceWeatherBrown">Kum: Normal</span>
    Hava: 17 C , AZ BULUTLU , NEM %66
</div>
```

- **Karar Dalı (§1.3):** **(b) Yalnız HTML'de var.**
- **İstek Sayısı ve Süre:** Veritabanındaki `status = 'result'` olan benzersiz `(date, city)` çifti sayısı **1.525**'tir. `Accept-Encoding: gzip` ve `DELAY = 1.5 sn` ile tahmini süre ~45 dakika (`<= 3 saat`) olduğundan `tools/fetch_track_html.py` ile devam ettirilebilir (resumable) şekilde `data/raw/html_cond/{date}_{city}.html` altına **1.525 / 1.525** şehir-gün bloğunun tamamı indirilmiştir (`0` eksik dosya).
- **Koşu Öncesi İlan Durumu (§4.1):** Geçmiş günlerin hem `GunlukYarisProgrami` hem `GunlukYarisSonuclari` HTML sayfalarında aynı `<div class="conditions-race">` bloğu yer almaktadır. Ancak yarış sabahı erken saatte (`06:40`) henüz pist ölçümü ilan edilmeden çekilen canlı gelecek program sayfasında bu blok boş (`[]`) geldiği için, pist durumunun bahis anından önce bilindiği **varsayım** olarak işaretlenmiştir.
- **Sentetik Pist Notu:** TJK HTML sayfalarında yalnız `Çim:` ve `Kum:` span'ları yayınlanmaktadır (`Sentetik:` span'ı yoktur; Sentetik koşularda `track_cond_raw = NULL` → `track_cond = 'bilinmiyor'` olarak atanmaktadır).

### Ham Pist Durumu Değerleri (Normalleştirmeden Önce İlk 30 Farklı Değer, §1.3)

İndirilen `1.525` şehir-gün HTML dosyasındaki tüm `<span class="raceWeather...">` ham metinlerinin ve `12.797` sonuçlanmış koşuya karşılık gelen ham değerlerin normalleştirme öncesi dağılımı (ilk 30 farklı değer):

| Sıra | Ham Pist Durumu Metni (`track_cond_raw`) | Şehir-Gün Sayısı (`/ 1.525`) | Koşu Sayısı (`/ 12.797`) | Normalleştirilmiş (`track_cond`) |
|---:|---|---:|---:|---|
| 1 | `Kum: Normal` | 1.331 | 6.469 | `normal` |
| 2 | `Çim: Normal 3,3` | 458 | 2.551 | `normal` |
| 3 | `Kum: Nemli` | 83 | 561 | `nemli` |
| 4 | `Kum: Islak` | 55 | 412 | `islak` |
| 5 | `Kum: Sulu` | 37 | 242 | `islak` |
| 6 | `Çim: Biraz Yumuşak 3,4` | 27 | 159 | `yumusak` |
| 7 | `Çim: Çok Yumuşak 4` | 11 | 58 | `yumusak` |
| 8 | `Çim: Çok Ağır 5,3` | 11 | 20 | `agir` |
| 9 | `Çim: Çok Ağır 5,2` | 9 | 4 | `agir` |
| 10 | `Çim: Yumuşak 3,7` | 9 | 48 | `yumusak` |
| 11 | `Çim: Yumuşak 3,5` | 9 | 53 | `yumusak` |
| 12 | `Çim: Yumuşak 3,6` | 8 | 47 | `yumusak` |
| 13 | `Çim: Çok Ağır 5,8` | 6 | 1 | `agir` |
| 14 | `Çim: Çok Yumuşak 3,9` | 5 | 26 | `yumusak` |
| 15 | `Çim: Çok Yumuşak 4,3` | 5 | 34 | `yumusak` |
| 16 | `Çim: Çok Yumuşak 4,2` | 5 | 32 | `yumusak` |
| 17 | `Çim: Çok Yumuşak 4,1` | 4 | 26 | `yumusak` |
| 18 | `Çim: Çok Ağır 5,5` | 4 | 6 | `agir` |
| 19 | `Çim: Çok Ağır 5,4` | 4 | 4 | `agir` |
| 20 | `Çim: Ağır 4,7` | 4 | 25 | `agir` |
| 21 | `Çim: Çok Yumuşak 3,8` | 3 | 13 | `yumusak` |
| 22 | `Çim: Çok Ağır 5,9` | 3 | 2 | `agir` |
| 23 | `Çim: Normal 3,2` | 2 | 11 | `normal` |
| 24 | `Çim: Çok Ağır 5,1` | 2 | 1 | `agir` |
| 25 | `Çim: Ağır 4,6` | 2 | 11 | `agir` |
| 26 | `Çim: Ağır 4,9` | 2 | 13 | `agir` |
| 27 | `Çim: Çok Ağır 5,6` | 2 | 1 | `agir` |
| 28 | `Çim: Çok Ağır 6` | 2 | 0 | `agir` |
| 29 | `Çim: Ağır 4,5` | 2 | 7 | `agir` |
| 30 | `Çim: Biraz Ağır 4,4` | 2 | 14 | `agir` |

*(Not: İlk 30 dışında kalan 5 nadir çim ölçümü — `Çim: Normal 0`, `Çim: Çok Ağır 5,7`, `Çim: Yumuşak`, `Çim: Çok Ağır 6,3`, `Çim: Çok Ağır 6,5` — da `ganyan/track.py` içindeki `TRACK_COND_MAP` sözlüğü tarafından eksiksiz kapsanmaktadır; eşleşmeyen ham değer sayısı `0`'dır.)*

---

## 3. Open-Meteo Arşiv vs Forecast Kaynak Karşılaştırması ve Canlı Kullanım Notu (§3.3)

Eğitim ve geri testte Open-Meteo'nun tarihsel reanaliz uç noktası (`https://archive-api.open-meteo.com/v1/archive`, `2024-10-01` … `2026-10-21`, 10 şehir × `18.024` saat = `180.240` saatlik kayıt, `%0,00` eksik veri) kullanılmıştır. Ancak reanaliz arşivinde ~5 günlük gecikme bulunduğundan, canlı ileri testte veya uygulamada tahmin uç noktasının (`https://api.open-meteo.com/v1/forecast?past_days=3`) kullanılması gerekir. Eğitim (reanaliz) ile canlı kullanım (forecast modeli) arasındaki uyumu ölçmek için son 30 gün (`2026-09-22` … `2026-10-21`) boyunca 3 büyük hipodrom şehrinde günlük yağış toplamları karşılaştırılmıştır:

- **İstanbul (Veliefendi):** 30 günlük toplam yağış Arşiv = `213,4 mm`, Forecast = `143,4 mm`, günlük yağış korelasyonu **`r = 0,9786`**.
- **Ankara (75. Yıl):** 30 günlük toplam yağış Arşiv = `85,2 mm`, Forecast = `78,8 mm`, günlük yağış korelasyonu **`r = 0,9313`**.
- **İzmir (Şirinyer):** 30 günlük toplam yağış Arşiv = `40,0 mm`, Forecast = `32,0 mm`, günlük yağış korelasyonu **`r = 0,8758`**.

İki kaynak arasındaki günlük yağış korelasyonu yüksek (`0,88–0,98`) olmakla birlikte mutlak yağış miktarlarında reanaliz/forecast farkı mevcuttur. Ayrıca **Open-Meteo ücretsiz API'si yalnızca ticari olmayan (araştırma) kullanım içindir**; mobil uygulamada ticari kullanım için ücretli API aboneliği veya kendi barındırma çözümü **kullanıcı kararıdır**.
