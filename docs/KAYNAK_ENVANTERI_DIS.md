# Dış Veri Kaynakları Derinlik Envanteri (`liderform.com.tr`, `yenibeygir.com`)

- **Ölçüm tarihi:** 2026-11-14 23:04 +03
- **Toplam istek sayısı:** 26
- **Ham yanıt dizini:** `data/raw/probe`

## 1. Güncel Yol Yoklaması

| Site | Yol | HTTP | Boyut (B) | `<title>` | İlk 30 `<th>` | Tarih Bağlantı Kalıpları | Engel / Durum |
|---|---|---:|---:|---|---|---|---|
| `liderform` | `/sonuclar` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/program` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/program/galop` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/program/galop-bulten` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/program/performans` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/program/sprintler` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/program/kim-kimi-gecti` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/muhtemeller` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/kayitlar/galop` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/istatistik/at` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `liderform` | `/istatistik/jokey` | 403 | 4553 | Attention Required! \| Cloudflare | - | `-` | Cloudflare engeli (HTTP 403) |
| `yenibeygir` | `/` | 200 | 271670 | At Yarışı Bülteni \| yenibeygir.com | AGF, No, At İsmi, Yaş, Kilo, Jokey, Sahip/Antr., Klv, Son 10 Yarış, Hnd, G/S20, S | `/{DD-MM-YYYY}, /{DD-MM-YYYY}/ankara, /{DD-MM-YYYY}/izmir, /{DD-MM-YYYY}/diyarbakir/sonuclar, /{DD-MM-YYYY}/sanliurfa/8/sonuclar?kosu=149981&at=108033, /{DD-MM-YYYY}/diyarbakir/4/sonuclar?kosu=149981&at=108033` | Açık |
| `yenibeygir` | `/01-05-2026/istanbul/1/sonuclar` | 200 | 32427 | Cuma İstanbul 1. Koşu At Yarışı Sonuçları | Sıra, At İsmi, Yaş, Kilo, Jokey, Sahip/Antr., Klv, Derece, Hız, Gny, AGF, Fark, G. Ç, Hnd | `/{DD-MM-YYYY}/sonuclar, /{DD-MM-YYYY}/istanbul/sonuclar, /{DD-MM-YYYY}/istanbul/2/sonuclar?at=14558, /{DD-MM-YYYY}/istanbul/1/sonuclar/foto, /{DD-MM-YYYY}/istanbul#kosu_1` | Açık |
| `yenibeygir` | `/14-11-2026/diyarbakir/1/galoplar` | 200 | 81158 | Cumartesi Diyarbakır 1. Koşu Galoplar (14 Kasım 2026) | Tarih, Şehir, Kg, Galop Jokey, 400, 600, 800, 1000, 1200, 1400, Ç, Pist | `-` | Açık |

### Kullanılan Tarih Kalıpları

- liderform (sonuc) şablonu: `https://www.liderform.com.tr/sonuclar?tarih={YYYY}-{MM}-{DD}` (varsayılan sorgu kalıbı (?tarih=))
- liderform (galop) şablonu: `https://www.liderform.com.tr/program/galop?tarih={YYYY}-{MM}-{DD}` (varsayılan sorgu kalıbı (?tarih=))
- yenibeygir (sonuc) şablonu: `https://yenibeygir.com/{DD}-{MM}-{YYYY}/diyarbakir/sonuclar` (sayfa bağlantısından bulundu)
- yenibeygir (galop): tarih kalıbı bulunamadı

## 2. Tarihsel Derinlik Denemeleri (2024, 2020, 2015, 2010)

| Site | Tür | Yıl | Tarih | URL | HTTP | Boyut (B) | `<title>` | `<th>` Sayısı | Örnek Satır | Engel / Durum |
|---|---|---:|---|---|---:|---:|---|---:|---:|---|
| `liderform` | `sonuc` | 2024 | 2024-10-06 | `https://www.liderform.com.tr/sonuclar?tarih=2024-10-06` | 403 | 4553 | Attention Required! \| Cloudflare | 0 | 0 | Cloudflare engeli (HTTP 403) |
| `liderform` | `sonuc` | 2020 | 2020-10-04 | `https://www.liderform.com.tr/sonuclar?tarih=2020-10-04` | 403 | 4553 | Attention Required! \| Cloudflare | 0 | 0 | Cloudflare engeli (HTTP 403) |
| `liderform` | `sonuc` | 2015 | 2015-10-04 | `https://www.liderform.com.tr/sonuclar?tarih=2015-10-04` | 403 | 4553 | Attention Required! \| Cloudflare | 0 | 0 | Cloudflare engeli (HTTP 403) |
| `liderform` | `sonuc` | 2010 | 2010-10-03 | `https://www.liderform.com.tr/sonuclar?tarih=2010-10-03` | 403 | 4553 | Attention Required! \| Cloudflare | 0 | 0 | Cloudflare engeli (HTTP 403) |
| `liderform` | `galop` | 2024 | 2024-10-06 | `https://www.liderform.com.tr/program/galop?tarih=2024-10-06` | 403 | 4553 | Attention Required! \| Cloudflare | 0 | 0 | Cloudflare engeli (HTTP 403) |
| `liderform` | `galop` | 2020 | 2020-10-04 | `https://www.liderform.com.tr/program/galop?tarih=2020-10-04` | 403 | 4553 | Attention Required! \| Cloudflare | 0 | 0 | Cloudflare engeli (HTTP 403) |
| `liderform` | `galop` | 2015 | 2015-10-04 | `https://www.liderform.com.tr/program/galop?tarih=2015-10-04` | 403 | 4553 | Attention Required! \| Cloudflare | 0 | 0 | Cloudflare engeli (HTTP 403) |
| `liderform` | `galop` | 2010 | 2010-10-03 | `https://www.liderform.com.tr/program/galop?tarih=2010-10-03` | 403 | 4553 | Attention Required! \| Cloudflare | 0 | 0 | Cloudflare engeli (HTTP 403) |
| `yenibeygir` | `sonuc` | 2024 | 2024-10-06 | `https://yenibeygir.com/06-10-2024/diyarbakir/sonuclar` | 200 | 219437 | Pazar At Yarışı Sonuçları | 14 | 5 | Açık |
| `yenibeygir` | `sonuc` | 2020 | 2020-10-04 | `https://yenibeygir.com/04-10-2020/diyarbakir/sonuclar` | 200 | 160913 | Pazar Diyarbakır At Yarışı Sonuçları | 14 | 5 | Açık |
| `yenibeygir` | `sonuc` | 2015 | 2015-10-04 | `https://yenibeygir.com/04-10-2015/diyarbakir/sonuclar` | 200 | 162830 | Pazar At Yarışı Sonuçları | 15 | 5 | Açık |
| `yenibeygir` | `sonuc` | 2010 | 2010-10-03 | `https://yenibeygir.com/03-10-2010/diyarbakir/sonuclar` | 200 | 185269 | Pazar At Yarışı Sonuçları | 14 | 5 | Açık |

## Ham Örnekler

Toplam **26** dosya kaydedildi:

| # | Kaynak | Dosya | HTTP | Ham Boyut (B) | Disk Boyutu (B) |
|---:|---|---|---:|---:|---:|
| 1 | `liderform` | `data/raw/probe/liderform_sonuclar.html.gz` | 403 | 4553 | 1773 |
| 2 | `liderform` | `data/raw/probe/liderform_program.html.gz` | 403 | 4553 | 1772 |
| 3 | `liderform` | `data/raw/probe/liderform_program_galop.html.gz` | 403 | 4553 | 1778 |
| 4 | `liderform` | `data/raw/probe/liderform_program_galop-bulten.html.gz` | 403 | 4553 | 1785 |
| 5 | `liderform` | `data/raw/probe/liderform_program_performans.html.gz` | 403 | 4553 | 1785 |
| 6 | `liderform` | `data/raw/probe/liderform_program_sprintler.html.gz` | 403 | 4553 | 1781 |
| 7 | `liderform` | `data/raw/probe/liderform_program_kim-kimi-gecti.html.gz` | 403 | 4553 | 1786 |
| 8 | `liderform` | `data/raw/probe/liderform_muhtemeller.html.gz` | 403 | 4553 | 1775 |
| 9 | `liderform` | `data/raw/probe/liderform_kayitlar_galop.html.gz` | 403 | 4553 | 1779 |
| 10 | `liderform` | `data/raw/probe/liderform_istatistik_at.html.gz` | 403 | 4553 | 1777 |
| 11 | `liderform` | `data/raw/probe/liderform_istatistik_jokey.html.gz` | 403 | 4553 | 1780 |
| 12 | `yenibeygir` | `data/raw/probe/yenibeygir_home.html.gz` | 200 | 271670 | 33498 |
| 13 | `yenibeygir` | `data/raw/probe/yenibeygir_01-05-2026_istanbul_1_sonuclar.html.gz` | 200 | 32427 | 6812 |
| 14 | `yenibeygir` | `data/raw/probe/yenibeygir_kesif__14-11-2026_diyarbakir_1_galoplar.html.gz` | 200 | 81158 | 6581 |
| 15 | `liderform_sonuc_hist` | `data/raw/probe/liderform_sonuc_hist_2024-10-06.html.gz` | 403 | 4553 | 1786 |
| 16 | `liderform_sonuc_hist` | `data/raw/probe/liderform_sonuc_hist_2020-10-04.html.gz` | 403 | 4553 | 1786 |
| 17 | `liderform_sonuc_hist` | `data/raw/probe/liderform_sonuc_hist_2015-10-04.html.gz` | 403 | 4553 | 1785 |
| 18 | `liderform_sonuc_hist` | `data/raw/probe/liderform_sonuc_hist_2010-10-03.html.gz` | 403 | 4553 | 1785 |
| 19 | `liderform_galop_hist` | `data/raw/probe/liderform_galop_hist_2024-10-06.html.gz` | 403 | 4553 | 1785 |
| 20 | `liderform_galop_hist` | `data/raw/probe/liderform_galop_hist_2020-10-04.html.gz` | 403 | 4553 | 1785 |
| 21 | `liderform_galop_hist` | `data/raw/probe/liderform_galop_hist_2015-10-04.html.gz` | 403 | 4553 | 1785 |
| 22 | `liderform_galop_hist` | `data/raw/probe/liderform_galop_hist_2010-10-03.html.gz` | 403 | 4553 | 1785 |
| 23 | `yenibeygir_sonuc_hist` | `data/raw/probe/yenibeygir_sonuc_hist_2024-10-06.html.gz` | 200 | 219437 | 27480 |
| 24 | `yenibeygir_sonuc_hist` | `data/raw/probe/yenibeygir_sonuc_hist_2020-10-04.html.gz` | 200 | 160913 | 19304 |
| 25 | `yenibeygir_sonuc_hist` | `data/raw/probe/yenibeygir_sonuc_hist_2015-10-04.html.gz` | 200 | 162830 | 21045 |
| 26 | `yenibeygir_sonuc_hist` | `data/raw/probe/yenibeygir_sonuc_hist_2010-10-03.html.gz` | 200 | 185269 | 23035 |

## 3. Mac + Cloudflare WARP ile ek ölçüm (14.11.2026, Claude, elle)

Actions IP'si Cloudflare'e takılıyor; Mac'te WARP açıkken liderform ve yenibeygir açılıyor (BTK engeli aşılıyor).

| Sayfa | Derinlik | İçerik (sayfadaki `__NEXT_DATA__` JSON, `props.pageProps.raceData[]`) |
|---|---|---|
| liderform `/program/galop/<yyyy-aa-gg>/<şehir>/<koşu>` | 2015-10-04 ✔, 2019 ✔, 2021 ✔, 2024 ✔ | at başına `workouts[]` (en çok 10): tarih, hipodrom, tür (GALLOP/SPRINT), jokey+kg, 1600…400 ara dereceler (`graph`), `effort` (çaba), `going`, `inner_outer`; at: `foaling_year`, `sire_name`, `dam_name`, `dam_sire_name` (2015'te boş, 2024'te dolu) |
| liderform `/program/performans/<yyyy-aa-gg>/<şehir>/<koşu>` | 2015 ✔, 2024 ✔ | at başına geçmiş koşular; sayfa sütunları: tarih, şehir, şart, pist, P.D, kg, jokey, S, S/K, takı, derece, D/800, **tabela & boy farkları** (yarış içi konum), G.Ç, AGF, GNY, HP, ikramiye |
| liderform `/sonuclar/<yyyy-aa-gg>`, `/muhtemeller/<yyyy-aa-gg>/<şehir>/<koşu>` | 2010 / 2023 sayfa açılıyor | tablo verisi sayfada YOK; tarayıcıda `services-lf.liderform.com.tr` API'sinden yükleniyor (JS'e gömülü Bearer anahtarıyla) → **kullanıcı açık izni olmadan kullanılmaz** |

**Sızıntı tuzağı:** geçmiş tarihli sayfada `races[]`, `ranks`, `handicap.now` sayfa çekildiği GÜNÜN durumunu gösterir
(2015 koşusunun sayfasında 2016 koşuları var). Yalnız `meeting_date < koşu tarihi` olan galoplar özellik olabilir;
`races[]` girdileri yalnız anlattıkları koşunun kendi olgusu olarak (o koşuya bağlanarak) kullanılabilir.
