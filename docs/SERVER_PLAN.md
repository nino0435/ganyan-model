# Ganyan — Sunucuya Taşıma Planı (8 haftalık ileri test)

Amaç: Mac'e bağımlı olmadan, kesintisiz çalışan günlük ileri test. Bu belge başka bir AI/kişi tarafından uygulanabilir olacak şekilde yazıldı.

## 1. Neden / neden değil
Mac'te şu an riskler: uyku/uyanma, caffeinate'in ~14:06'da bitmesi (İzmir 17:15 yarışı), Mac kapalıysa gün kaybı.
İleri test 8 hafta (~56 gün) sürecek; her kaybedilen gün örneklemden gider. Sunucu bu riski kaldırır.

## 2. Ölçülen kaynak ihtiyacı (29 Eki 2026, Mac'te)
- `forward_log`: ~36 sn CPU, **tepe RAM ≈ 0,93 GB**. Gün içi 12 tekrar + sabah 1 + akşam (update_daily ~15–35 dk, ağırlıklı TJK bekleme/DELAY 0,5 sn + export ~16 dk).
- Disk: data 217 MB (ham CSV 54 MB, hava 7 MB, html 9 MB, DB), venv 303 MB. Günlük artış ≈ 1–2 MB. 8 hafta sonunda < 1 GB.
- Python 3.14 (venv). Sunucuda aynı sürüm ya da uyumlu 3.12+ kurulmalı; önce testlerin geçtiğini doğrula.
- Gerekli: 2 vCPU, **4 GB RAM** (2 GB sınırda, takas gerekir), 20 GB disk.

## 3. Maliyet (yaklaşık, kurulumdan önce güncel fiyatı doğrula)
| Seçenek | Aylık | 8 hafta (~2 ay) | Not |
|---|---|---|---|
| Hetzner CX22 (2 vCPU/4 GB, AB) | ~4–5 € | ~9–11 € | En ucuz; TJK IP engeli riski aşağıda |
| DigitalOcean/Vultr 2 vCPU/4 GB | ~20–24 $ | ~40–48 $ | Daha pahalı, İstanbul'a yakın konum yok |
| Türk sağlayıcı VPS (ör. yerel hosting) | ~150–400 TL | ~300–800 TL | TR IP, TJK engel riski en düşük |
| Oracle Cloud Always-Free (ARM) | 0 | 0 | Bedava ama kapasite bulmak zor, hesap askıya alınabilir |
| Mac'te kalmak | 0 | 0 | Elektrik + uyanık tutma; güvenilirlik düşük |

Ek maliyet: yedek depolama (S3/R2 vb.) ihtiyaç yok — DB git dışı ama günlük `sqlite3 .backup` + rsync yeterli. Alan adı gerekmiyor. **Beklenen toplam: ~10 € (Hetzner) – ~800 TL (TR VPS).**
Çalışma emeği: ~2–3 saat kurulum + 1 hafta paralel doğrulama.

## 4. EN BÜYÜK RİSK: TJK, veri merkezi IP'lerini engelleyebilir
`tjk.org` yabancı/bulut IP'lerinden 403/zaman aşımı verebilir. **Karar kapısı (kurulumdan önce, 5 dk):**
sunucu kiralamadan, aynı sağlayıcının bir deneme makinesinde (saatlik faturalı) şunu çalıştır:
```
curl -sI "https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisSonuclari" | head -1
```
200 ve CSV indirmesi başarılıysa devam. 403/timeout ise Türkiye IP'li VPS'e geç.
AGF canlı verisi de aynı siteden geliyor; engel gelirse ileri test hiç çalışmaz.

## 5. Mimari
- Linux (Ubuntu 24.04 LTS), saat dilimi `Europe/Istanbul` (scriptler `TZ=Europe/Istanbul` kullanıyor ama sistem TZ'yi de ayarla).
- launchd yerine **systemd timer** (ya da cron). Mevcut işler:
  - `sabah`: ilk yarış −45 dk (haftanın gününe göre değişen saat; bkz. `ops/launchd/com.ganyan.sabah.plist`). Sunucuda daha basit: günlük 10:30'da çalıştır (her günün ilk yarışı daha geç).
  - `tekrar`: 11:30–17:00 her 30 dk, `daily_job.sh tekrar`.
  - `aksam`: 00:45, dünü işler.
  - `uyanik` (caffeinate) sunucuda gereksiz.
- Aynı `scripts/daily_job.sh` kullanılır (bash; `stat -f %z`/`date -v` BSD komutları **GNU'da farklı** → Linux için uyarlanmalı: `stat -c %s`, `date -d 'yesterday'`, `find -mmin`). Bu, portlamanın tek kod değişikliği.
- Bildirim: `osascript` yerine e-posta/ntfy/Telegram (basit curl). Hata olursa mesaj.
- Veri taşıma: `data/ganyan.db` + `data/raw/` rsync ile kopyala (≈ 220 MB). Repo `git clone` (private; deploy key).
- Mac'teki işleri sunucu kanıtlanana kadar **kapatma, 1 hafta paralel çalıştır** (aşağıda tuzak).

## 6. Paralel çalışma tuzağı (çok önemli)
`predictions` birincil anahtarı `(race_id, prog_no, model_version)` + INSERT OR IGNORE: **ilk yazan kazanır**. İki makine aynı DB'ye değil kendi DB'sine yazar; karşılaştırma için çıktıları (p_win) karşılaştır, sonra **tek kaynak** seç.
Tek kaynak = sunucu. Mac'i geçiş gününde durdur (`launchctl bootout`), geçmiş predictions'ı sunucuya **tek seferde** kopyala (Mac'in 28–29 Eki kayıtları kaybolmasın).

## 7. Adımlar (her adımın doğrulaması)
1. IP erişim testi (bölüm 4) → 200/CSV indirilebiliyor.
2. VPS kur, Python + `pip install -r requirements.txt`; `pytest -q` → 23 passed.
3. Repo clone + `data/` rsync; `sqlite3 data/ganyan.db "pragma integrity_check"` → ok.
4. `daily_job.sh`'yi GNU uyumlu yap; `tekrar` modunu elle çalıştır → "Logged N" log'da.
5. systemd timer'lar (sabah/tekrar/aksam); `systemctl list-timers` → 3 satır.
6. Hata bildirimi: bilerek hatalı çalıştır → mesaj gelsin.
7. 7 gün paralel çalıştır; her sabah sunucu vs Mac `predictions` farkı (p_win fark < 1e-6 beklenir; farklıysa veri farkı vardır, araştır).
8. Geçiş: Mac işlerini kapat, predictions kopyala, sunucu tek kaynak.
9. Günlük yedek: `sqlite3 data/ganyan.db ".backup /var/backups/ganyan-$(date +%F).db"` + son 7'yi tut; haftada bir Mac'e rsync.
10. 8. hafta sonu: `reports/FORWARD.md` değerlendirmesi, sunucuyu kapat (faturalama biter).

## 8. Güvenlik / gizlilik
- Repo private; sunucuda yalnız deploy key, parola girişi kapalı (SSH anahtarı), ufw (22 açık, gerisi kapalı).
- Bültenler (data/bulten/) fotoğrafları da ileride sunucuya kopyalanacaksa gitignored kalır, repoya girmez.
- TJK veri lisansı kullanım koşulları gelir planı varsa ayrıca sorulmalı (açık madde).

## 9. Karar
- Mevcut Mac sorunsuz uyanıyorsa 8 hafta için **sunucu zorunlu değil**; tek gerçek açık İzmir 17:15 / uyku. `caffeinate` süresini 17:00'a uzatmak 0 maliyet.
- Gün kaybı sıfır olsun isteniyorsa: önce TR IP'li ya da test edilmiş AB VPS, ~10 € – ~800 TL.
