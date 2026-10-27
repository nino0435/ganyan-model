> **Durum:** UYGULANDI (Claude, 27.10.2026, `3283d70` + `e9fa868`). Gerçek kurulum `scripts/daily_job.sh` ve `ops/` altında; bu belge yalnız tasarım gerekçesi için. Proje yolu sonradan `~/AndroidStudioProjects/ganyan` oldu.

# Ganyan — İleri test günlük otomasyonu (launchd) şartnamesi

Uygulayıcı: Gemini. İnceleyen: Claude. Proje: `ganyan_model` (derspilot ile İLGİSİZ — derspilot reposuna hiçbir şey yazma).
Tarih: 27.10.2026. Ön koşul: yol haritasının 11 dilimi + `fb6faba` pushlu, `git status` temiz.

## 0. Amaç ve başarı ölçütü

Her yarış günü, insan müdahalesi olmadan:
1. **Sabah (yarışlardan önce):** günün programı + canlı AGF çekilir, `forward_log` ile tahminler `predictions` tablosuna yazılır (`created_at < post_time`).
2. **Gece (yarışlardan sonra):** günün sonuçları çekilir, `reports/FORWARD.md` yeniden üretilir, günün JSON export'u yazılır.

Bitti sayılması için (§6'daki komutlarla kanıtla):
- `launchctl print gui/$(id -u)/com.ganyan.sabah` ve `.../com.ganyan.aksam` yüklü görünür.
- `launchctl kickstart` ile iki iş de elle tetiklenince log'da `OK` satırı çıkar, çıkış kodu 0.
- Sabah işi ikinci kez çalışınca `predictions` satır sayısı değişmez (idempotent; `INSERT OR IGNORE`).
- Yarış olmayan bir tarihte iş hata vermeden `yarış yok` yazıp 0 ile çıkar.

## 1. ADIM 1 — Projeyi Masaüstü'nden taşı (ZORUNLU)

**Neden:** (a) `~/Desktop` macOS TCC korumalı klasördür; launchd'nin başlattığı `/bin/bash`/python oraya erişince
`Operation not permitted` alır (Full Disk Access verilmeden). (b) Masaüstü iCloud'a eşitleniyor; dosyalar buluta
boşaltılıyor (`dataless`), venv'de yaşanan zaman aşımı bundandı. `~/ganyan_data` ve `~/ganyan_venv` zaten ev dizininde, sorun yok.

```bash
cd ~/Desktop/ganyan_model && git status -s            # boş olmalı; değilse DUR, kullanıcıya bildir
find ~/Desktop/ganyan_model -flags +dataless | wc -l   # 0 olmalı; değilse: brctl download ~/Desktop/ganyan_model ve tekrar say
mkdir -p ~/Projects && mv ~/Desktop/ganyan_model ~/Projects/ganyan_model
cd ~/Projects/ganyan_model && ls -l data venv          # mutlak hedefli bağlantılar: ~/ganyan_data, ~/ganyan_venv
venv/bin/python -m pytest -q                            # 15 passed
git remote -v && git status -s                          # remote aynı, durum temiz
```
Bundan sonra bu belgede proje kökü = `~/Projects/ganyan_model` (`$ROOT`).

## 2. Ön ölçüm (kodu yazmadan önce, "doğrula")

1. **Sabah saati:** Son 90 günün en erken yurt içi koşu saatini ölç:
   ```sql
   SELECT strftime('%w', date) AS gun, MIN(post_time) FROM races
   WHERE date >= date('now','-90 day') GROUP BY gun;
   ```
   Sabah işini **en erken `post_time` − 45 dk**'ya ayarla (aşağı yuvarla, :00/:15/:30/:45). Bulduğun saati rapora yaz.
   Beklenti 11:00–12:15 arası; dışında çıkarsa raporda belirt.
2. **Gece saati:** Son 90 günün en geç `post_time`'ı + 90 dk. Yaz gece yarışları 23:00'e kadar sürebilir; 00:00'ı geçerse
   gece işini **ertesi gün 00:30**'a koy ve o iş `--date` olarak **dünü** kullansın (wrapper'da `aksam` modu bunu hesaplar).
   Sabah işi zaten `update_daily` ile dünün sonuçlarını da çekiyor (d−1) — çifte güvence.
3. `scripts/forward_log.py`'nin CLI'ını oku (`--date` nasıl alınıyor, yarış yoksa ne yapıyor). Yarış olmayan bir günde
   (ör. TJK'nin boş günü) `forward_log` ve `update_daily` hata atıyorsa, **en küçük** düzeltmeyi yap: boşsa `yarış yok`
   yazdırıp 0 ile çık. Başka davranış değiştirme.
4. `post_time`'ı geçmiş koşular için `forward_log` tahmin yazıyor mu bak. Yazıyorsa: zararsız (rapor `created_at < post_time`
   ile süzüyor, `INSERT OR IGNORE` ilk kaydı koruyor) — **değiştirme**, yalnız raporda not et.

## 3. ADIM 2 — Wrapper betiği `scripts/daily_job.sh`

Tek giriş noktası; launchd yalnız bunu çağırır. Gereksinimler:

- Kullanım: `scripts/daily_job.sh sabah|aksam [YYYY-MM-DD]` (tarih verilmezse hesaplanır).
- `set -u -o pipefail`; `cd` betiğin bir üst klasörüne (`$(dirname "$0")/..`) — mutlak yol yazma.
- Python: `"$ROOT/venv/bin/python"` (launchd PATH'i minimaldir; `python3` çağırma). Elle çalışan komutların **aynısını**
  kullan (`-I` vb. bayraklar dahil) — betik içinde yeni import düzeni icat etme.
- Tarih Türkiye saatiyle: `TZ=Europe/Istanbul date +%F`. `aksam` modu: saat < 06:00 ise dünün tarihi.
- **Kilit:** `mkdir "$ROOT/data/.lock"` başarısızsa `kilit var, çıkılıyor` yaz ve 0 ile çık; `trap 'rmdir ...' EXIT`.
  (macOS'ta `flock` yok.) Kilit 6 saatten eskiyse (yarım kalmış iş) sil ve devam et.
- Adımlar:
  - `sabah`: `update_daily.py --date D` → `forward_log.py --date D`
  - `aksam`: `update_daily.py --date D` → `forward_report.py` → `export_day.py --date D`
  - Her adım ayrı çalışır; biri düşerse sonrakiler yine denenir, en sonda genel çıkış kodu ≠0.
- **Log:** her satır `2026-10-27T11:15:02+03:00 [sabah] <adım> OK|HATA(kod)` biçiminde; komut çıktısı da aynı dosyaya.
  Dosya: `~/Library/Logs/ganyan-daily.log`. Başta boyut > 5 MB ise `ganyan-daily.log.1`'e taşı (tek yedek).
- **Hata bildirimi:** genel çıkış ≠0 ise
  `osascript -e 'display notification "<mod> adımı başarısız, log: ~/Library/Logs/ganyan-daily.log" with title "Ganyan"'`.
  osascript başarısız olursa yok say (`|| true`).
- **Git'e dokunma:** betik commit/push yapmaz. `reports/FORWARD.md` her gün değişecek; commit'i insan/ajan elle yapar.

## 4. ADIM 3 — launchd plist'leri `ops/launchd/`

İki dosya: `com.ganyan.sabah.plist`, `com.ganyan.aksam.plist`. Etiket öneki **`com.ganyan.`** (asla `com.derspilot.`).
Şablon (mevcut `~/Library/LaunchAgents/com.derspilot.meb-dbf-izle.plist` ile aynı yapı):

```xml
<key>Label</key><string>com.ganyan.sabah</string>
<key>ProgramArguments</key><array>
  <string>/bin/bash</string>
  <string>/Users/berhantekdemir/Projects/ganyan_model/scripts/daily_job.sh</string>
  <string>sabah</string>
</array>
<key>StartCalendarInterval</key><dict><key>Hour</key><integer>HH</integer><key>Minute</key><integer>MM</integer></dict>
<key>RunAtLoad</key><false/>
<key>StandardOutPath</key><string>/Users/berhantekdemir/Library/Logs/ganyan-daily.log</string>
<key>StandardErrorPath</key><string>/Users/berhantekdemir/Library/Logs/ganyan-daily.log</string>
<key>EnvironmentVariables</key><dict><key>LANG</key><string>en_US.UTF-8</string></dict>
```
- Saatler §2.1/§2.2 ölçümünden. Her gün çalışır (Weekday yok) — yarış yoksa betik zaten boş geçer.
- **`RunAtLoad` false** (kurulumda tetiklenmesin; testi `kickstart` ile yap).
- Plist'lerde `/Users/berhantekdemir` mutlak yolu kabul (launchd `~` açmaz); şablona değil gerçek dosyaya yaz.

Kurulum betiği `ops/install_launchd.sh` (idempotent):
```bash
for n in sabah aksam; do
  dst=~/Library/LaunchAgents/com.ganyan.$n.plist
  launchctl bootout gui/$(id -u)/com.ganyan.$n 2>/dev/null || true
  cp "ops/launchd/com.ganyan.$n.plist" "$dst"
  plutil -lint "$dst"
  launchctl bootstrap gui/$(id -u) "$dst"
done
```
Kaldırma için `ops/uninstall_launchd.sh` (bootout + rm). `launchctl load/unload` (eski API) kullanma.

## 5. Tuzaklar (her biri gerçek bir risk)

1. **TCC / Masaüstü:** Adım 1 yapılmadan launchd işi sessizce `Operation not permitted` ile düşer. Atlanamaz.
2. **Uyku:** Mac uykudaysa `StartCalendarInterval` işi uyanınca **bir kez** çalıştırır (kaçırılanlar birleştirilir).
   Sabah işi yarıştan sonra çalışırsa tahminler `created_at > post_time` olur → rapor onları zaten saymaz. Bu kabul edilen
   davranış. Mac kapalıysa hiç çalışmaz. **`sudo pmset repeat wake ...` ÇALIŞTIRMA** — kullanıcı kararı (aşağı bak).
3. **TJK'ye nazik ol:** tek kilit + mevcut `DELAY`; paralel istek yok, ek yeniden deneme döngüsü ekleme (`tjk.get` zaten 3 kez dener).
4. **Homebrew Python güncellemesi:** `~/ganyan_venv` `/opt/homebrew` python'una bağlı; `brew upgrade` sürüm atlatırsa venv
   kırılır → bildirim gelir. README'ye "venv'i yeniden kur" iki satırı ekle (`python3 -m venv ~/ganyan_venv && pip install ...`).
5. **Saat dilimi:** `created_at` İstanbul saatiyle yazılıyor (`IST_TZ`); wrapper tarihi de `TZ=Europe/Istanbul` ile hesaplar.
   Mac'in kendi saat dilimine güvenme.
6. **`INSERT OR IGNORE`:** ilk tahmin kalıcıdır. Sabah işini daha erken bir saate alıp "sonra tekrar çalıştırırım" yaklaşımı
   işe yaramaz — ilk kayıt kazanır. Bu yüzden sabah saati yarışa yakın (−45 dk) seçiliyor.
7. **Log'da sır yok:** URL/başlık dışında bir şey loglama; zaten kimlik bilgisi yok, öyle kalsın.

## 6. Doğrulama (sırayla, çıktıları rapora koy)

```bash
cd ~/Projects/ganyan_model
bash -n scripts/daily_job.sh && shellcheck scripts/daily_job.sh || true      # shellcheck yoksa geç
scripts/daily_job.sh sabah                         # bugün; log'da [sabah] ... OK
sqlite3 data/ganyan.db "SELECT COUNT(*) FROM predictions"                     # N
scripts/daily_job.sh sabah                         # tekrar
sqlite3 data/ganyan.db "SELECT COUNT(*) FROM predictions"                     # yine N (idempotent)
scripts/daily_job.sh sabah <yarış olmayan bir tarih>                          # 'yarış yok', çıkış 0
mkdir data/.lock && scripts/daily_job.sh sabah; rmdir data/.lock              # 'kilit var', çıkış 0
bash ops/install_launchd.sh
launchctl print gui/$(id -u)/com.ganyan.sabah | grep -E "state|path|calendar" -A3
launchctl kickstart -k gui/$(id -u)/com.ganyan.aksam && sleep 60 && tail -20 ~/Library/Logs/ganyan-daily.log
venv/bin/python -m pytest -q                        # 15 passed (hiç kırılmadı)
```
`kickstart` ile çalışan iş TCC hatası verirse Adım 1 eksik demektir — Full Disk Access verme önerme, taşımayı kontrol et.

## 7. Commit dilimi

Tek commit (taşıma git'e yansımaz):
```bash
git add -- scripts/daily_job.sh ops/launchd/com.ganyan.sabah.plist ops/launchd/com.ganyan.aksam.plist \
  ops/install_launchd.sh ops/uninstall_launchd.sh README.md [§2.3'te dokunduysan: scripts/forward_log.py scripts/update_daily.py]
git commit -m "feat(ops): ileri test için günlük launchd işleri (sabah tahmin, gece sonuç+rapor)"
git push origin main
```
`git add -A` / `git add .` YOK. `reports/FORWARD.md` bu commit'e girmez (otomatik değişen dosya).

## 8. Yapılmayacaklar

- Bahis/kupon oynama, TJK dışı bir yere veri gönderme.
- Otomatik git commit/push (betikten).
- `sudo` gerektiren her şey (`pmset`, sistem ayarı, Full Disk Access).
- `com.derspilot.*` plist'lerine dokunma; derspilot reposuna yazma.
- Model/özellik/rapor mantığını değiştirme (yalnız §2.3'teki "yarış yok" düzeltmesi serbest).

## 9. Kullanıcı kararı bekleyenler (Gemini sormadan uygulamaz)

- **Mac'in sabah kendiliğinden uyanması:** `sudo pmset repeat wake MTWRFSU HH:MM:00` (sabah işinden 5 dk önce).
  Mac kapalı/uykuda kalan günler ileri testten düşer. Kararı ve komutu kullanıcı verir/çalıştırır.
- **FORWARD.md commit sıklığı:** öneri haftada bir elle commit.

## 10. Final rapor formatı (Gemini → kullanıcı)

- Yeni proje yolu, `git log -1 --oneline`, push durumu.
- Ölçülen en erken / en geç `post_time` ve seçilen iki saat.
- §6 komutlarının çıktıları (kısaltılmış), `predictions` N değerleri, log'dan son 10 satır.
- §2.3/§2.4 bulguları (dokunulduysa diff özeti).
