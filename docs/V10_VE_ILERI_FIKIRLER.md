# Ganyan Model — V10 ve İleri Sürüm Fikir Kataloğu (Yol Haritası)

Bu belge, yarış psikolojisi/ilişki ağları ve matematiksel yaklaşımlardan türetilen tüm tahmin, kupon kurgusu ve bütçe fikirlerini kalıcı olarak kaydetmek; hangisinin ne işe yarayacağını, hangi veriyi gerektirdiğini ve ne zaman devreye alınacağını izlemek için oluşturulmuştur.

---

## 1. Hemen Sınanacak V10 Fikirleri *(Eldeki 20 Yıllık Veri Hazır — Ek Toplayıcı Gerekmez)*

Bu 4 paket, mevcut veritabanındaki (`2005–2026`, `111.000+` koşu) TJK yarış ve Yenibeygir hız/AGF kayıtlarıyla doğrudan üretilebilmektedir ve şu an bulut günlük güncellemesi (`daily_v5_update.py`) sayesinde canlıda her gün otomatik akmaktadır.

| Kod | Fikir / Yaklaşım | Ne İşe Yarar? (Yarış Mantığı) | Modelde Ölçülen Sinyaller |
|---|---|---|---|
| **`BELL`** | **Doğal Dağılım (Çan Eğrisi)** | Her at aynı istikrarda koşmaz. Dar çan eğrili at güvenli ama tavanı sınırlıdır; geniş çan eğrili "patlayıcı" at ise iyi gününde kendinden güçlü favorileri geçebilir. | Son 8 yarıştaki hız/derece oynaklığı, iyi gün (%90 tavan) hızı, tavanın en güçlü rakibin ortalamasından farkı ve çan eğrisi üzerinden en güçlü rakibi geçme olasılığı. |
| **`JLOY`** | **Jokey Tercihi, Sadakat ve Terk Etme ("Dostluk/Seçim")** | Jokey önceki bindiği atı ya da yıllardır çalıştığı sadık ahırı bırakıp başka ata biniyorsa, içeriden gelen güçlü bir "bugün hedef bu at" işareti verir. Tersi durumda antrenörün normalden daha başarılı bir jokey çağırması da niyet göstergesidir. | Jokeyin önceki atını rakipte bırakması, iki atın halk şansı farkı, jokeyin son 1 yılda çok daha sadık çalıştığı antrenörü bu koşuda bırakması, antrenöre göre jokey kalitesi yükselişi. |
| **`LOAD`** | **Biriken Efor (İntegral) ve Form İvmesi (Türev)** | Tek yarış değil, üst üste biriken yarış yükü atı yorar. Aynı şekilde sadece son derece değil, derecenin zaman içindeki yükselme/düşme hızı (türev) ve ivmesi (ikinci türev) form patlamasını ya da düşüşünü erken yakalar. | Son 60 ve 180 gün toplam yarış mesafesi, 30 günlük yarılanmalı birikmiş efor yükü, son iki yarış arası hızlanma hızı ve son 3 yarıştaki hız ivmesi. |
| **`H2H`** | **Birebir Karşılaşma ("Derbi / Rövanş")** | Genel güç puanları yakın olsa bile bazı atlar aynı rakiplere karşı sürekli üstünlük kurar veya daha zorlu rakiplerle çarpışmış olur. | Son 2 yılda bugünkü gerçek rakiplerle kaç kez karşılaştığı, kaçını geçtiği, koşudaki diğer atlara kıyasla rövanş üstünlüğü ve koşunun favori rakibine karşı birebir karnesi. |

---

## 2. Yeni Veri Birikince Sınanacak V11+ Fikirleri *(Toplayıcılar Şu An Bulutta Aktif)*

> **Numara notu (25.11.2026):** `V11` etiketi sonradan pist + hava deneyi için kullanıldı ve rafa kaldırıldı (`docs/V11_KARAR.md`; `features_v11.py` ve `run_v11_experiments.py` ona ait). Aşağıdaki tabloda `V11` yazan "Canlı Oran İvmesi" fikri sınanmadı; sınanırken yeni sürüm numarası alacak.

Bu fikirler için ham veri toplama hatları **15 Kasım 2026**'dan beri bulutta otomatik olarak çalışmaktadır. Güvenilir test yapabilmek için geçmiş sonuçlanmış koşu arşivinin **en az 60–90 gün** (`~1.000–1.500+` koşu) birikmesi hedeflenmektedir.

| Aşama | Fikir / Yaklaşım | Ne İşe Yarar? (Yarış Mantığı) | Aktif Veri Kaynağı ve Güncel Durum *(24.11.2026)* | Hedef Veri Eşiği |
|---|---|---|---|---|
| **`V11`** | **Canlı Oran İvmesi (Zamana Göre Türev / "Akıllı Para")** | Sabah %5–6 görünen bir atın yarışa son 15–30 dakika kala oranının aniden düşmesi (hızlı para girişi) çoğu zaman ahırdan çıkan ciddi bir hazırlık sinyalidir. | `nino0435/tjk-canli-oran` (`veri` dalı) — Cloud Scheduler ile her gün `09:55` ve `15:25`'te koşu başına yaklaşık 25 dk aralıklı kayıt alır. **Şu an: 9 gün, 245+ dosya.** *(V11 öncesinde son dakikalarda daha sık örnekleme eklemek sinyali keskinleştirir.)* | En az `60–90` gün (~`1.000+` koşu) |
| **`V12`** | **Kalabalık Şişirmesi ve Gazete Karşıt Sinyali (Oyun Teorisi)** | Gazete, bülten ve yaygın tahmincilerin ortaklaştığı atlara halk aşırı yüklenir ve ganyan düşer. Tahmincilerin abarttığı favorileri ölçüp gerçek pist verisiyle çarpıştırarak yapay şişirmeyi yakalamak amaçlanır. | `nino0435/ganyan-tahmin-veri` (`tahmin-veri` dalı) — Sporx, Milliyet ve Hipodrom.com kupon/yorumlarını saatlik (`07:30–17:30`) toplar. **Şu an: 9 gün (Sporx `344` tahmin satırı + Milliyet + Hipodrom kupon/yorum arşivi).** | En az `60–90` gün (`1.000+` koşu) |

---

## 3. Kupon ve Bütçe Katmanı *(Tahmin Sonrası Karar Sistemi)*

Model olasılıkları yeterince güçlendikten sonra kazancı asıl büyütecek katman "hangi ata ne kadar ve nasıl oynanır?" sorusunu çözer:

1. **Oyun Teorisi ile Akıllı Altılı Ganyan Kurgusu:**
   - Amaç yalnız en muhtemel atları yazmak değil, *"gerçek kazanma ihtimali, halkın kuponuna yazma oranından yüksek"* olan atları öne çıkarmaktır.
   - Böylece herkesin tuttuğu 6 favorili düşük ikramiyeli kurgular yerine, bütçe içinde beklenen ikramiyeyi maksimize eden kupon kombinasyonları kurulur.
2. **Bütçe Matematiği (Kelly Yaklaşımı):**
   - Modelin avantaj gördüğü fırsat yarışlarında daha cesur, halkla birebir aynı gördüğü yarışlarda ise daha temkinli/pas geçerek uzun vadeli sermayeyi koruma ve büyütme kuralı.
   - Ön koşul: Önce birkaç yüz canlı ileri-test koşusunda modelin oran avantajının gerçek sahada korunduğunun doğrulanması.

---

## 4. Bilinçli Olarak Elenen veya Şimdilik Bekletilen Fikirler

- **İki jokey veya antrenör arasında "kişisel düşmanlık / derbi":** Aynı iki kişinin benzer güçteki atlarla başa baş kalma sayısı veride çok azdır; gürültüye ezber riski yüksek olduğu için alınmadı.
- **Soy ağacı (baba / anne hattı) özellikleri:** `v3` serisinde test edilip katkı sağlamadığı için elendi (`reports/SOY.md`).
- **Galop binicisi ve gün içi kulvar eğilimi:** `v9` serisinde test edilip katkı vermediği/canlı bütçeyi aştığı için elendi (`reports/V9.md`).
- **Eski `fark` (burun/boy) ve `son800` sütunları:** Veritabanında `2025` sonrası düzenli dolmadığı için canlı modele alınmadı (`docs/V6_BULGULAR.md`).
