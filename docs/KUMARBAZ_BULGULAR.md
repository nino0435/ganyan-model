# Kumarbaz simülasyonu — Bulgular

**Tarih:** 25.11.2026 · **Durum:** Deney. Canlı hatta, modellere ve uygulamaya dokunmaz; karar vermek için değil, fikir toplamak için.

## Neden

İleride uygulamaya "oyun modları" (cesur, temkinli, bitik, mantıklı, stratejik …) konabilir. Önce her oyun tarzının geçmişte gerçek ödemelerle ne kazandırdığı ve neyi tutturduğu görülsün. Tür adlarını ve kuralları Claude belirledi (kullanıcı "isimlere takılma, sen belirle" dedi). Modlar ürün kararı değildir; burada yalnızca simülasyon karakterleri var.

## Ne yapıldı

7 sanal kumarbaz, 2022-01 … 2026-11 (1.770 yarış günü, 31.544 koşu), her gün oynar. Kasa 10.000 TL, bahis 50 TL, kasa 10 TL altına inerse iflas. Ödeme `runners.ganyan` (nihai oran, 1 TL'ye brüt dönüş). Model türleri V10 `HLB_CAL` yıllık dışarıdan tahminini kullanır (model o yılı hiç görmeden üretir). Ayrıntılı kartlar ve tüm tablolar: `reports/KUMARBAZ.md`.

| Kumarbaz | Fikir karşılığı | Kural |
|---|---|---|
| Temkinli Tarık | temkinli | Günün en güçlü 4 favorisine oynar |
| Cesur Cemal | cesur | Kalabalık sahada oranı 10 ve üstü en kısa oranlı ata oynar |
| Bitik Bilal | bitik | İlk 6 koşuda favori; kaybedince bahsi ikiye katlar |
| Mantıklı Mehmet | mantıklı | Modelin en emin olduğu 4 koşuda modelin 1. tercihi |
| Stratejik Selin | stratejik | Değerci'nin atları, çeyrek Kelly bahis, günlük sınır |
| Değerci Deniz | (ek) | Modelin ihtimali AGF payının 1,5 katı ve %8 üstü olan atlar |
| Rastgele Remzi | (kontrol) | Rastgele koşu, rastgele at |

## Sonuç (300 günlük oyun)

| Kumarbaz | İsabet | Tutan atın oranı | Bahis başına getiri [%95 aralık] | Kasa sonu (medyan) | İflas |
|---|---:|---:|---|---:|---|
| Temkinli Tarık | %49,5 | 1,4 | −%30,5 [−32,2; −28,9] | 0 | %100 (163. gün) |
| Cesur Cemal | %5,1 | 12,0 | −%39,5 [−45,9; −33,1] | 0 | %100 (126. gün) |
| Bitik Bilal | %36,3 | 1,9 | −%30,6 [−32,5; −28,8] | 0 | %100 (10. gün) |
| Mantıklı Mehmet | %50,9 | 1,5 | −%23,3 [−25,1; −21,5] | 0 | %100 (216. gün) |
| Değerci Deniz | %16,0 | 6,8 | **+%9,0 [−0,2; +18,2]** | 13.319 | %0 |
| Stratejik Selin | %16,0 | 6,8 | +%9,0 [−0,2; +18,2] (para ağırlıklı +%11,6) | 14.308 | %0 |
| Rastgele Remzi | %11,7 | 5,0 | −%42,0 [−47,2; −36,0] | 0 | %100 (113. gün) |

Çıta (1 TL'lik bahis, bütün koşular): rastgele at −%38,9, favori −%31,4, modelin 1. tercihi −%23,7.

## Ne anlıyoruz

1. Klasik türlerin hiçbiri (favori, uzun oran, kayıp kovalama, modelin 1. tercihi) komisyonu yenemiyor: 4–9 ayda iflas, Bitik 10 günde.
2. Model tek başına işe yarıyor ama yetmiyor: modelin 1. tercihi favoriden 7,7 puan, rastgeleden 15,2 puan iyi, yine de −%23,7.
3. Yalnız model ile AGF ayrıştığında oynayan türler ayakta (+%9). **Bu kanıt değil, ipucu:** %95 aralık sıfırı kapsıyor, eşikler (p ≥ %8, model/AGF ≥ 1,5) tanı aşamasında aynı veride görüldü. Yıllara göre +%4,6 / −%11,8 / +%26,4 / +%13,4 / +%14,3 (2022…2026).
4. Kesinti belirleyici. Koşunun Σ(1/ganyan) değeri 1,40 altındayken (kesinti yaklaşık %26 ve altı) Değerci +%33,4 (1.116 bahis), üstündeyken +%0,4 (3.170 bahis). Diğer türler düşük kesintide de negatif (Mantıklı −%21,0, Temkinli −%24,0). Alt grup ayrımı sonradan yapıldı, bu da bir ipucu.
5. Tutturdukları: Değerci favori değil, medyan 5,9 kat oranlı atları tutturuyor (100 bahsin 16'sı). Temkinli neredeyse her ikinci bahsi tutturuyor ama 1,4 kat ödeme alıyor.

## Uyarılar

- **Kapanış oranı ve AGF:** Kumarbaz kapanışta oynayan, kapanış AGF'sini ve oranını gören kişi gibi modellenir. Canlıda erken alınan AGF daha az bilgi taşır (`reports/V10.md` Uyarı 1); bahsin oranı etkilemediği de varsayıldı. Canlı sonuç daha kötü beklenmeli.
- **Seçimde nihai oran sızıntısı:** Seçimi p × nihai oran ≥ 1,10 ile yapınca bahis başına getiri +%19 çıkıyor. Bu, bahis anında bilinmeyen bilgiyi kullanmak, yani yapay. Model türleri bu yüzden seçimde oranı değil AGF'yi kullanır; ödeme nihai orandan.
- **Kesinti dönemleri veriden çıkarım:** Aylık medyan Σ(1/ganyan)'dan kesinti yaklaşık %26 ile %55 arasında oynuyor (tablo `reports/KUMARBAZ.md` içinde). 2023 Temmuz–Eylül'deki %55 bütün hipodromlarda aynı anda görünüyor, nedeni bilinmiyor. 2024 Kasım tutarsız (eş oranlı atlar Σ'yı şişirir).
- **Yol örneklemesi:** "Kârda bitenler" ve "iflas" yüzdeleri 5 yıllık günlerin rastgele karışımıdır; bahis başına getirinin belirsizliğini yansıtmaz, o %95 aralık sütununda.

## Yeniden üret

```bash
venv/bin/python scripts/run_kumarbaz_sim.py
```

Yaklaşık 5 sn sürer ve `reports/KUMARBAZ.md` dosyasını yazar. Girdi git dışıdır: `data/ganyan.db` ve her yıl için tam bir `data/v10_cache/pred_V10_HLB_CAL_*_<yıl>.pkl`. Testler: `tests/test_kumarbaz_sim.py` (sentetik veri, DB gerekmez).

## Kapsam dışı ve sonra

- **Altılı kuponcusu yok.** Altılı birim fiyatı yalnız 2026 için kesin (`ganyan/backtest.py` `UNIT_TL_TABLE`); kupon dağıtıcı `ganyan/allocator.py` hazır.
- **İkili, üçlü, plase gibi diğer bahisler yok.** Ödemeleri `bets` tablosunda var.
- **Değerci için gerçek kanıt** önceden yazılmış bir protokol ve canlı, erken AGF ile ileri test ister; bu simülasyon onun yerine geçmez.
