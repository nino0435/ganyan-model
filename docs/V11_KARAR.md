# V11 (pist durumu + hava) — Karar: RAFA KALDIRILDI

**Tarih:** 25.11.2026 · **Karar:** V11 canlıya alınmaz. **V10 (`v10_hlb`) canlıda aynen kalır.** Kod, veri ve raporlar silinmeden rafa kaldırıldı.

> **Adlandırma notu:** Kod ve raporlardaki `V11` = **pist + hava** deneyi (`GOING`, `WX`, `GPREF`). `docs/V10_VE_ILERI_FIKIRLER.md` §2'deki "V11 = canlı oran ivmesi" fikri ayrıdır, sınanmadı ve bu kararla ilgisi yoktur; sınanırken yeni sürüm numarası alacak (`features_v11.py` ve `run_v11_experiments.py` pist+hava'ya ait).

## Ne sınandı

- V10'un 155 özelliğinin üstüne 16 özellik: `GOING` 5 (yüzeye göre pist sırası, ıslaklık bayrağı, çim ölçümü), `WX` 4 (sıcaklık, nem, yağışlı gökyüzü, rüzgâr), `GPREF` 7 (atın geçmişte ıslak ve kuru pistteki performans farkı, büzülmüş).
- Veri: TJK şehir-gün sayfalarından 8.689 gün (2015-01-01…2026-11-22) indirildi. `races.track_cond*` boş hücreleri doldu (57.317 satır), `day_cond` tablosu eklendi. Eğitim ve test aynı kaynaktan (TJK) beslendi; Open-Meteo yedeği bilerek kaldırıldı.
- Protokol V10'unkiyle aynı ve sonuca bakıp değiştirilmedi: Aşama A 2017–2021, 1 tohum, eşik ΔLL < −0,0002 (sıkı); geçen en fazla 1 aday Aşama B kapısına (`n_boot=2000, seed=0, min_neg_years=3`); 2026 yalnız bilgi.

## Sonuç (ΔLL, V10 tabanına göre; eksi = iyi)

| Dönem | GOING | WX | GPREF | ALL |
|---|---:|---:|---:|---:|
| **Aşama A 2017–2021 (karar dönemi)** | +0,0004 | +0,0004 | +0,0007 | +0,0007 |
| Aşama 2 2022–2025 (tanı) | −0,0000 | +0,0002 | +0,0004 | −0,0001 |
| 2026 (yalnız bilgi) | **−0,0012** | −0,0001 | −0,0002 | −0,0002 |

Aşama A'da güven aralıklarının hepsi 0'ı kapsıyor ya da 0'a dayanıyor (`GPREF` alt sınırı −0,0000) ve hiçbir aday −0,0002 eşiğine yaklaşmadı. Aşama B kapısı hiç çalışmadı. Taban `V10_1s` Aşama A'da log-loss 1,8303 (AGF'ye göre −0,0275). Ayrıntı: `reports/V11.md`, `docs/V11_BULGULAR.md`.

## Neden bu karar

1. **Kural:** Önceden yazılmış protokolün kapısı geçilmedi. Sonuç ne çıkarsa çıksın protokol değiştirilmeyecekti (şartname T2-5).
2. **Ölçülebilir kazanç yok.** Dört adayın hepsi Aşama A'da V10'dan hafif kötü (+0,0004…+0,0007), 2022–2025'te fark sıfır civarı. Pist ve hava eklemek V10'u iyileştirmedi.
3. **Olası nedenler (çıkarım, bu deneyle ayrıştırılmadı):** (a) AGF baskın özellik; halkın tahmini pist durumunu zaten içeriyor olabilir, aynı yarışta tüm atlar aynı pisti yaşar. (b) Ata özel ıslak/kuru tercihi için veri az: ıslak koşu yıllara göre yalnız %11–20. (c) 155 özellikli modele 16 özellik daha eklemek gürültü getirmiş olabilir.
4. **Backtest zaten iyimserdi.** Eğitimde ve testte pist/hava gün SONU değeri kullanıldı; canlıda koşu anındaki değer görülecek. İyimser koşulda bile geçmediği için canlıda daha iyi olması beklenmez.
5. **Maliyet:** Geçse bile canlı hatta koşu anı pist/hava çekimi gerekecekti (günlük hat şu an çekmiyor). Kazanç göstermeyen bir özellik için bu iş yapılmaz.
6. **Aynı yönde önceki test:** V1 `v2_agf_hava` (16 ay) da geçmemişti (+0,00055, güven aralığı 0'ı kapsıyor; `reports/HAVA_PIST.md`). Şimdi 12 yıllık veriyle aynı sonuç.

## Dikkat çeken tek şey ve neden karara girmedi

`V11_GOING` 2026'da −0,0012 verdi (güven aralığı −0,0018…−0,0006). ΔLL zamanla iyileşiyor: +0,0004 → −0,0000 → −0,0012. Eğitim 2015'te başlıyor; test yılı 2017'de modelin 2 yıllık, 2021'de 6 yıllık, 2026'da 11 yıllık eğitim verisi var. Yeni özellikler az veriyle öğrenilemiyor olabilir (çıkarım). Ama: (a) 2026 v5'te tüketildi, seçimde kullanılamaz; (b) 4 aday arasından en iyisine bakmak çoklu karşılaştırmadır; (c) neden kanıtlanmadı. Karara girmez; yeniden açma gerekçesidir.

## Yeniden açma koşulu (öneri; biri yeter)

- 2027'de en az bir tam yıl ileri veri birikince **yalnız `GOING`**, tek aday, yeni ve önceden yazılmış bir protokolle (test = o ileri veri, eşik −0,0002, aynı Aşama B kapısı) bir kez sınanır. Aşama A (2017–2021) tekrar koşulmaz, aynı sonucu verir.
- Ya da canlı hatta koşu anı pist/hava çekimi başlarsa (eğitim-test uyumsuzluğu kalkar): `GOING` gölge model olarak ileri teste girer, canlıya doğrudan alınmaz.

## Rafta ne var (silinmedi)

- **Kod:** `tools/backfill_cond.py` (tarayıcı, kaldığı yerden devam eder), `tools/load_cond.py` (çözümle/yükle; varsayılan `--dry-run`, kapsama <%99,5 ise `--apply` reddeder), `ganyan/features_v11.py`, `scripts/run_v11_experiments.py`, testler `tests/test_load_cond.py` ve `tests/test_features_v11.py` (tam paket 240 test).
- **Rapor:** `reports/V11.md`, `docs/V11_BULGULAR.md`, kaynak araştırması `docs/VERI_KAYNAKLARI_ARASTIRMA.md`.
- **Veri (yerel, git dışı):** `data/cond_backfill.sqlite` (8.689 gün ham blok + 70.130 koşunun şartname ve açıklama metni), `data/ganyan.db` (`day_cond` + dolu `track_cond*`), yükleme öncesi yedek `data/ganyan.db.bak_pist` (1,3 GB, gerekmeyince silinebilir), `data/v11_cache`.
- **Canlı:** Dokunulmadı. Aktif modeller `v7_tcjp`, `v8_an`, `v9_kssb`, `v10_hlb`.
- **Tuzak:** `tools/fetch_track_html.py` ve `ganyan/track.py::load_html_cond_into_db` ÇALIŞTIRILMAZ (`data/raw/html_cond` boşken `track_cond*` değerlerini siler).

## Denetim (Claude, 25.11.2026) — Gemini'nin işi KABUL

- **Git:** izlenen hiçbir dosya değişmedi, `HEAD` aynı (`2c01d42`); canlı dosyalara (`forward_v5.py`, workflow'lar, `model_v10.py`) dokunulmadı.
- **Yedek ↔ güncel DB (salt okunur kıyas):** tek yeni tablo `day_cond` (8.689 satır); 15 tablonun satır sayıları aynı; `races`'te `track_cond*` dışı sütunlarda fark 0; 57.317 satırda `track_cond*` değişti; eskiden dolu hücrelerden değişen 0.
- **Yükleme:** kapsama %100, tarama ile DB'deki dolu hücreler 10.854'te birebir aynı, yüklemeden sonra dry-run 0 güncelleme.
- **Taban yeniden üretildi:** `V10_1s` Aşama A log-loss 1,8303 (24.843 koşu), `reports/V10.md`'deki V10 tabanıyla aynı; yeni veri tabanı etkilemedi.
- **Protokol:** eşik −0,0002 (sıkı `<`), kapı çağrısı ve taban `v10_hlb` koşudan önce denetlendi; dosyaların tarih damgası koşudan öncesi, yani koşu sırasında değişmedi.
- **Testler:** tam paket 240 geçti (Gemini 75 sn'de, Claude bağımsız olarak 81 sn'de).
