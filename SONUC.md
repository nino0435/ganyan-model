# Sonuç: Model AGF favorisini kısmen (Model + AGF için; AGF'siz model yenemedi)

Veri: 26.10.2024–25.10.2026, 12781 koşu (1523 CSV dosyası, 728 yarış günü, 123847 koşan at kaydı). Test 1: 01.04–25.10.2026 (3664 koşu). Test 2: 01.07–25.10.2026 (2078 koşu).

## Test 1 (01.04.2026–25.10.2026, 3664 koşu / 37192 at; Eğitim: 01.01.2025–31.03.2026, 7633 koşu)

| Yöntem | 1. tercih kazandı | İlk 3'te | Log-loss | Ganyan ROI |
|---|---|---|---|---|
| AGF favorisi | 33.4% | 66.8% | 1.8409 | -28.8% |
| Ganyan favorisi | 34.4% | 67.0% | 1.8652 | -29.3% |
| Model (AGF'siz) | 27.2% | 61.2% | 1.9668 | -29.3% |
| Model + AGF | 34.0% | 67.7% | 1.8347 | -25.9% |

## Test 2 (01.07.2026–25.10.2026, 2078 koşu / 21050 at; Eğitim: 01.01.2025–30.06.2026, 9219 koşu)

| Yöntem | 1. tercih kazandı | İlk 3'te | Log-loss | Ganyan ROI |
|---|---|---|---|---|
| AGF favorisi | 32.8% | 65.6% | 1.8524 | -28.6% |
| Ganyan favorisi | 34.0% | 65.4% | 1.8786 | -28.3% |
| Model (AGF'siz) | 27.6% | 60.5% | 1.9781 | -26.2% |
| Model + AGF | 32.8% | 66.2% | 1.8432 | -26.9% |

Fark (Model+AGF − AGF): +0.6% (%95 GA -0.2% … +1.4%)   | Test 2: +0.0% (%95 GA -1.0% … +1.0%)
Fark (Model − AGF): -6.1% (%95 GA -7.5% … -4.6%)        | Test 2: -5.2% (%95 GA -7.0% … -3.3%)
Irka göre (Test 1): Arap (1635 koşu): AGF 30.9%, Ganyan 31.4%, Model (AGF'siz) 24.2%, Model+AGF 32.1%, İngiliz (2029 koşu): AGF 35.3%, Ganyan 36.9%, Model (AGF'siz) 29.7%, Model+AGF 35.5%
Irka göre (Test 2): Arap (922 koşu): AGF 31.5%, Ganyan 32.0%, Model (AGF'siz) 26.9%, Model+AGF 32.4%, İngiliz (1156 koşu): AGF 33.9%, Ganyan 35.6%, Model (AGF'siz) 28.2%, Model+AGF 33.1%
Altılı (k=3, her ayak 3 at): Test 1: AGF 53/743 (7.1%), Model+AGF 66/743 (8.9%), Model (AGF'siz) 35/743 (4.7%) | Test 2: AGF 22/414 (5.3%), Model+AGF 35/414 (8.5%), Model (AGF'siz) 25/414 (6.0%)
Başarı ölçütü §0:
- Model (AGF'siz): şart1 sağlanmadı (-6.1%, %95 GA -7.5% … -4.6%), şart2 sağlanmadı (log-loss 1.9668 > 1.8409) → **yenemedi**
- Model + AGF: şart1 sağlanmadı (+0.6%, %95 GA alt sınırı -0.2% ≤ 0), şart2 sağlandı (log-loss Test 1: 1.8347 < 1.8409, Test 2: 1.8432 < 1.8524) → **kısmen**
Uyarılar:
- İndirme sırasında `www.tjk.org` gün sayfası zaman aşımına düştüğü/engellendiği için kalan günler doğrudan `medya-cdn.tjk.org` üzerinden 10 yerli hipodrom taranarak eksiksiz tamamlandı (toplam 1523 CSV dosyası, 0 başarısız dosya).
- Doğrulanmamış varsayımlar (§9): Altılı birim fiyatının 1,25 TL olduğu (tek haber kaynağından) ve TJK CSV'sindeki `6'LI GANYAN(...) :X TL` ikramiye tutarının 1 birim başına yazıldığı varsayılmıştır. ROI ve değer bahsi satırları kapanış oranlarını kullandığı için iyimserdir.
