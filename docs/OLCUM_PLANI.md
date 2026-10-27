# GANYAN — "Basit bir model AGF favorisini yenebilir mi?" ölçüm planı

> **Kime:** Bu planı uygulayacak yapay zekâ ajanı (Gemini / Antigravity).
> **Hazırlayan:** Claude, 26.10.2026. Kod ve veri hazır; senin işin **indirmeyi tamamlamak, çalıştırmak,
> sağlık kontrollerini yapmak ve sonucu raporlamak.** Yeni model icat etme; aşağıdaki sırayı izle.

---

## 0. Amaç ve başarı ölçütü

**Soru:** TJK'nin resmi sonuç CSV'lerinden kurulan basit bir model, bir koşunun kazananını **AGF
favorisinden** (Altılı Ganyan Favorisi = oyuncuların en çok oynadığı at) daha iyi tahmin edebiliyor mu?

İki model var:
- **Model (AGF'siz):** Yalnız atın/jokeyin/antrenörün geçmişi ve koşu koşulları. Bağımsız tahmin gücünü ölçer.
- **Model + AGF:** Aynı özellikler + o koşunun AGF payı. "Kalabalığın görüşüne ek bilgi katabiliyor muyuz?" sorusunu ölçer.

**"Yendi" sayılması için ŞARTLARIN İKİSİ BİRDEN:**
1. Test dönemindeki "1. tercih kazandı" oranı farkı (model − AGF favorisi) **%95 güven aralığının alt
   sınırı > 0** (betik bootstrap ile hesaplar).
2. Modelin **log-loss'u AGF'ninkinden düşük** (betik yazar; düşük = daha iyi olasılık).

Yalnızca biri sağlanırsa "kısmen", hiçbiri sağlanmazsa "yenemedi" yaz. ROI satırları **bilgi amaçlıdır**,
başarı ölçütü değildir (gerekçe §6/T9).

---

## 1. Klasör ve mevcut durum

```
~/AndroidStudioProjects/ganyan/
  tools/download_hist.py   # TJK gün sayfası → yerli hipodromlar → sonuç CSV'leri (kaldığı yerden devam eder)
  tools/parse_hist.py      # CSV'ler → her satırı bir at-koşu kaydı olan tablo (pickle)
  tools/model.py           # sızıntısız özellikler + 2 model + kıyas + altılı simülasyonu
  hist/                    # indirilmiş CSV'ler: 26.10.2024–20.11.2024 arası + 24–25.10.2026 (60 dosya)
```

- **Uçtan uca duman testi yapıldı** (49 dosyayla): ayrıştırma → özellik → eğitim → rapor hatasız çalıştı.
  O testteki sayılar **anlamsızdır** (çok az veri); referans alma.
- İndirme **21.11.2024'ten devam etmeli**; betik var olan dosyaları atlar, baştan başlatmak güvenlidir.
- Bu klasör **derspilot reposunun parçası değil.** derspilot'a dosya ekleme, commit atma.

---

## 2. Ortam kurulumu (bir kez)

```bash
cd ~/AndroidStudioProjects/ganyan
python3 -m venv venv
venv/bin/pip install -q numpy pandas scikit-learn
venv/bin/python -c "import numpy, pandas, sklearn; print(numpy.__version__, pandas.__version__, sklearn.__version__)"
```
Bu makinede çalışan sürümler: Python 3.14.6, numpy 2.5.4, pandas 3.1.0, scikit-learn 1.9.1.
`download_hist.py` yalnız standart kütüphane kullanır (venv gerekmez).

---

## 3. Adım 1 — İndirmeyi tamamla (~30–40 dk, arka planda)

```bash
cd ~/AndroidStudioProjects/ganyan
nohup python3 -I tools/download_hist.py hist 2024-10-26 2026-10-25 > download.out 2>&1 &
```

- İstekler **tek akışta, aralarında 0,5 sn beklemeyle** yapılır. **Paralel çalıştırma, beklemeyi düşürme**
  (TJK sunucusunu yormayalım; engellenme riski).
- İlerleme: `tail -3 hist/_log.txt` (her gün için `YYYY-MM-DD day=200 cities=N` satırı yazılır).
- Bitiş işareti: `hist/_log.txt` son satırı **`DONE`**.
- **Sağlık kontrolü (bitince):**
  ```bash
  ls hist/*.csv | wc -l                         # beklenen: ~1300–1700 dosya (2 yıl × günde 1–3 hipodrom)
  grep -E ' (404|None) ' hist/_log.txt | wc -l  # başarısız CSV sayısı; birkaç tane olabilir, yüzlerce olmamalı
  grep -E 'day=None' hist/_log.txt              # gün sayfası alınamayan günler → bu tarihlerle betiği tekrar çalıştır
  ```
  Başarısız gün/dosya varsa aynı komutu **o tarih aralığıyla** yeniden çalıştır (var olanı atlar).

---

## 4. Adım 2 — Ayrıştır

```bash
venv/bin/python -I tools/parse_hist.py hist runs.pkl
```
Beklenen çıktı ve kabul ölçütleri:
- `range=2024-10-26..2026-10-25`
- `missing agf %` **< 3**; `missing ganyan %` **< 1**; `missing time %` birkaç % olabilir (derecesiz atlar).
- Son satır (`winners per race`): büyük çoğunluk `1`. `0` kazananlı koşular **iptal edilen koşulardır**
  (ör. 22.10.2026 Ankara/İzmir/Bursa); model bunları zaten dışarıda bırakır. `2` = ölü yarış, yine dışarıda.

---

## 5. Adım 3 — Modeli çalıştır

```bash
venv/bin/python -I tools/model.py runs.pkl hist 2026-04-01 | tee sonuc_2026-04.txt
```
- Eğitim: 01.01.2025–31.03.2026. Test: 01.04.2026–25.10.2026 (model bu dönemi hiç görmez).
- 26.10.2024–31.12.2024 yalnız **geçmiş üretmek** için kullanılır (eğitime girmez).
- Süre: birkaç dakika (pandas `transform(lambda…)` satırları en yavaş kısım; normal).

**Sağlamlık için ikinci kesit (zorunlu):**
```bash
venv/bin/python -I tools/model.py runs.pkl hist 2026-07-01 | tee sonuc_2026-07.txt
```
İki kesitte sonuç yön değiştiriyorsa (birinde yeniyor, diğerinde yenemiyor) raporda **"tutarsız"** yaz.

Çıktı bölümleri: (1) yöntem tablosu: 1. tercih / ilk2 / ilk3 / ilk4 / log-loss / ganyan ROI;
(2) bootstrap fark + %95 GA; (3) ırka göre (Arap/İngiliz) isabet; (4) değer bahsi; (5) altılı simülasyonu.

---

## 6. Tuzaklar — bunları BOZMA (her biri gerçek veri özelliğinden)

- **T1. CSV'nin ilk sütunu ("At No") program numarası DEĞİL, varış sırasıdır.** Program numarası yalnız
  `GANYAN(n)` satırında ve HTML'de var. Kod atları **ad yerine `baba|anne|doğum yılı`** ile tanır (`horse` sütunu).
- **T2. At adı takı kodları içerir** (`OĞUZHANTAY KG DB SK`) ve koşmayan at `(Koşmaz)` ile işaretlidir.
  Adla eşleştirme yapma; `horse` anahtarını kullan.
- **T3. Kilo `57 +0.70` gibi gelebilir** (fazla kilo) → toplanır. **Kulvar `10 - DS`** → ilk sayı. **AGF `%2.99(6)`** →
  yüzde 2.99, sıra 6. Bu ayrıştırmalar `parse_hist.py`'de; değiştirirsen duman testini tekrarla.
- **T4. Sızıntı yasağı:** Bir koşunun özelliği **yalnız önceki günlerin** verisinden gelir. Atın o günkü
  derecesi/varışı/`beaten`/`fpct` **asla** özellik olmaz. Jokey/antrenör oranları **aynı günü hariç tutar**
  (kodda `day - day_now`). Hız puanı medyanları **yalnız test öncesi** veriden hesaplanır. Yeni özellik
  eklersen bu üç kurala uymayanı ekleme.
- **T5. AGF ve ganyan oranı CSV'de "kapanış" değerleridir.** AGF, koşu başlamadan bilinir → "Model + AGF"de
  kullanmak meşru. Ganyan oranı **özellik değildir**, yalnız kıyas (ganyan favorisi) ve ROI için kullanılır.
  Atın **geçmiş** koşularındaki oranlar (`h_logodds_*`) özellik olabilir.
- **T6. Altılı sonuç satırı `2,3,7,10/4/...`** gibi çoklu numara içerebilir (koşmayan at favoriye sayılır);
  simülasyon bunu kullanmaz, her koşunun gerçek kazananına bakar. Ölü yarışlı/iptal koşulu altılılar atlanır.
- **T7. Şehir adları Türkçe karakterlidir** (`İzmir`, `Şanlıurfa`, `Elazığ`); dosya adında ve URL'de öyle kalır
  (URL'de yüzde-kodlanır). Yabancı hipodromlar gün sayfasında `Y.G.` içermez ve indirilmez — doğru davranış.
- **T8. Model koşu içinde normalize edilir** (olasılıklar koşu başına toplam 1). Bu adımı kaldırma.
- **T9. ROI satırları iyimserdir:** kapanış oranı bahis anında bilinmez; ayrıca bizim bahsimiz oranı düşürür.
  Altılı ROI'si **birim 1,25 TL** ve **ikramiye birim başına** varsayımıyla hesaplanır (bkz. §9). Bu yüzden
  ROI başarı ölçütü değildir.
- **T10. `TEST_START` değiştirirsen** eğitim penceresi otomatik kayar; `TRAIN_START` (2025-01-01) sabit kalsın.

---

## 7. Rapor — `~/AndroidStudioProjects/ganyan/SONUC.md` dosyasına Türkçe yaz

Aşağıdaki şablonu doldur (sayıları çıktılardan kopyala, yorum katma):

```
# Sonuç: Model AGF favorisini [yendi / kısmen / yenemedi]

Veri: <ilk tarih>–<son tarih>, <N> koşu. Test 1: 01.04–25.10.2026 (<n> koşu). Test 2: 01.07–25.10.2026 (<n> koşu).

| Yöntem | 1. tercih kazandı | İlk 3'te | Log-loss | Ganyan ROI |
|---|---|---|---|---|
| AGF favorisi | | | | |
| Ganyan favorisi | | | | |
| Model (AGF'siz) | | | | |
| Model + AGF | | | | |

Fark (Model+AGF − AGF): <x> (%95 GA <a> … <b>)   | Test 2: <...>
Fark (Model − AGF): <x> (%95 GA <a> … <b>)        | Test 2: <...>
Irka göre: Arap <...>, İngiliz <...>
Altılı (k=3, her ayak 3 at): AGF <tutan/toplam>, Model+AGF <tutan/toplam>
Başarı ölçütü §0: şart1 [sağlandı/sağlanmadı], şart2 [sağlandı/sağlanmadı]
Uyarılar: <başarısız indirmeler, tutarsızlık, beklenmedik durumlar>
```

---

## 8. Yapılmayacaklar

- Bahis yatırma, herhangi bir bahis sitesine giriş, hesap açma — **yok**.
- TJK'ye paralel/yoğun istek, bekleme süresini düşürme — **yok**.
- WhatsApp'tan gelen bülten fotoğraflarını veri olarak kullanma — **yok** (okunabilirlik zayıf, telif başkasının).
- derspilot reposuna dosya/commit — **yok**.
- Hiperparametre avı yapıp en iyi test sonucunu seçmek — **yok** (test setine uydurma olur). Ayarlar sabit.

---

## 9. Doğrulanmamış bilgiler (raporda "varsayım" diye an)

- **Altılı birim fiyatı 1,25 TL (2026):** tek bir haber kaynağından (24 Saat). TJK/United Racing resmi duyurusu bulunmadı.
- **İkramiyenin "birim başına" yazıldığı** varsayımı: TJK CSV'sindeki `6'LI GANYAN(...) :X TL` değerinin
  1 birim için olduğu varsayıldı; doğrulanmadı.
- **2024 verisinin tamlığı:** arşivin 2023'e kadar gittiği görüldü (örnek dosyalar açıldı), her günün eksiksiz
  olduğu doğrulanmadı → §3 sağlık kontrolü bunu ölçer.

---

## 10. Bitince kullanıcıya söylenecek tek paragraf

"İndirme tamamlandı (<N> dosya, <başarısız> başarısız). <test dönemi>'nde model AGF favorisini
[yendi/yenemedi]: 1. tercih isabeti model <x>, AGF <y> (fark %95 GA <a>…<b>); log-loss model <..>, AGF <..>.
Ayrıntı: ~/AndroidStudioProjects/ganyan/SONUC.md."
