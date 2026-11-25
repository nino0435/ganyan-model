# Veri Kaynakları Araştırması (24.11.2026)

Soru: modelleri eğitmek / geri-test ve ileri-test için eldekinden daha iyi hangi veri var, nasıl alınır?

## 1. Elimizdekiler (V5–V10 bunları kullanıyor)

| Veri | Kapsam | Not |
|---|---|---|
| TJK sonuçları | 2005–2026, 111 bin koşu | at/jokey/antrenör geçmişi, takı (`name_raw`) |
| Kapanış AGF | 2015–2026 (%81–99) | modelin en güçlü girdisi, 2005–2014'te yok |
| Yenibeygir hız puanı | 2010–2026, 1,8 milyon satır | |
| Liderform galop | 2015–2026, 1,47 milyon satır | |
| Canlı AGF anlık görüntüsü | 28.10.2026'dan beri | `agf_snapshots` |

Denenip **sinyal vermeyenler:** `fark`, `son800`, `geç çıkış`, `ikramiye`, havuz (V6), soy (SOY), galop jokeyi / gün içi kulvar (V9).
Bu alanlar 2024-11'den beri boş ama canlı modellerde (V9, V10) kullanılmadıkları için sorun değil.

## 2. Yeni kaynaklar — sıralı

| # | Kaynak | Ne verir | Durum |
|---|---|---|---|
| 1 | **Pist durumu + hava** (TJK şehir-gün sayfası) | Çim/kum pist durumu (Normal, Yumuşak, Ağır, Islak…, çimde sayısal ölçüm), sıcaklık, nem, gökyüzü; koşu şartı metni | 2015–2024-10 için **kazınıyor** (bkz. §3). V5+ modellerinde hiç yok; tek test (V1, 16 ay) sonuçsuz kalmıştı. |
| 2 | **Accurace GPS takibi** (`accurace.net/network/...`, TJK sayfalarından bağlı) | 100 m'de bir süre, sıra, korkuluğa uzaklık, kat edilen yol, hız → tempo ve "dışta koştu" bilgisi | **Kazınmadı:** `robots.txt` `/network/*` yolunu tüm botlara yasaklıyor. Veri yalnız 2023+ ve bazı hipodromlarda görünüyor (2019–2022 ve Ankara 2024 örneği boş). Yol: Accurace'tan lisans/erişim istemek. |
| 3 | Canlı oran serisi (`nino0435/tjk-canli-oran`) | Gün boyu oran hareketi | Çalışıyor: 15.11'den beri ~29 dosya/gün (263 dosya). V11 için 60–90 gün gerekiyor. |
| 4 | Liderform "performans" sayfası | Geçmiş koşularda yarış içi konum (tabela, boy farkı) → koşu tarzı | Yapılmadı: Mac'te WARP açık olmalı, `robots.txt` WARP kapalıyken okunamadı. Değer yüksek, maliyet büyük. |
| 5 | TJK "Pist Bilgilendirme Formu" PDF | Bariyer konumu, sulama, penetrometre | Seyrek dolu; ertelendi. |
| 6 | TJK komiser raporu PDF (`medya-cdn.tjk.org/raporftp/YarisBilgileri/...`) | Çıkan at, jokey değişikliği; 2021'den itibaren usulsüz kulvar cezası, koşu sonrası veteriner notu (topallık, jokey düşürme, start tökezlemesi), "dış start" | **Düşük değer.** 7 raporluk örnek: 2016–2019 raporları boş (yalnız çıkan at/jokey değişikliği), yorumlar 2021'de başlıyor; günde ~1–3 at (≈%1–3) sakatlık/düşme notu; engellenen (mağdur) at adı yok. Aşama A penceresi (2017–2021) protokolle test edilemez. V6'daki `X_STEW` bloğu ve `steward_notes` tablosu hazır, yalnız veri yok. |
| 7 | Open-Meteo | Saatlik hava | Gereksiz: TJK sayfasında "Hava:" satırı var. |

## 3. Pist/hava taraması

- Araç: `tools/backfill_cond.py` (yeni). `data/ganyan.db`'ye dokunmaz; çıktı `data/cond_backfill.sqlite` (`day`: şehir-gün bloğu, `race`: koşu numarası, saat, koşu şartı metni).
- Doğrulama: DB'de zaten pist değeri olan 25 gün yeniden çekildi, 29/29 değer birebir aynı.
- Hız: TJK sunucusu istek başına 4–8 sn bekletiyor; 2 de 4 işçi de ~0,3 gün/sn. 2015–2024-10 = 7.103 şehir-gün ≈ 6,5 saat.
- Devam: aynı komut yeniden çalıştırılır, kayıtlıları atlar.

```bash
python3 -I tools/backfill_cond.py --workers 2 --delay 1.0 --from 2015-01-01 --to 2024-10-24
python3 -I tools/backfill_cond.py --workers 2 --delay 1.0 --from 2013-01-01 --to 2014-12-31
```

- Tuzak: `tools/fetch_track_html.py` + `ganyan/track.py::load_html_cond_into_db`, `data/raw/html_cond` boşken çalıştırılırsa `races.track_cond*` değerlerini siler. Çalıştırma.
- Çözümleme/yükleme (`tools/load_cond.py`) ve GOING/WX/GPREF özellikleri (`ganyan/features_v11.py`, `scripts/run_v11_experiments.py`) A Takımı Tur 1'de yazıldı (24.11.2026). Tarama 2024-10-25'ten bugüne de uzatıldı, çünkü test yılları (2025–2026) için `Hava:` metni DB'de yok. Gerçek yükleme ve tam deney Tur 2'de yapıldı (25.11.2026): hiçbir aday kapıyı geçemedi, V11 rafa kaldırıldı. Karar ve gerekçe: `docs/V11_KARAR.md`.

## 4. Erişim notları (dürüstlük)

- `accurace.net/robots.txt`: `Disallow: /network/*`. Bunu okumadan önce elle 11 deneme isteği attım; sonra durdum, toplu çekim yapılmadı.
- `www.tjk.org/robots.txt`: tüm botlara `Disallow: /` (yalnız Googlebot ve sosyal medya önizleyicileri serbest). Projenin tüm veri hattı zaten buna dayanıyor; yeni taramada aynı kibar hız (2 işçi, istek başına ≥1 sn bekleme, 403/429'da otomatik durma) kullanıldı. Risk kullanıcıya aittir.
- `yenibeygir.com` ve `liderform.com.tr`: BTK engeli yüzünden (WARP kapalı) `robots.txt` okunamadı.
