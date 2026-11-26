# İki Aşamalı Model (Bill Benter: `P_temel` + `AGF`) — Bulgular

**Tarih:** 26.11.2026 · **Durum:** Deney tamamlandı (canlı hatta dokunulmadı) · **Kapı Sonucu:** **KALDI (Canlıda `V10_HLB_CAL` korunur)** — Kapanış AGF altında tek aşamalı `V10` geçilemedi; ancak `FUND_06` saf güç modeli sabah/erken AGF ve uygulama açıklanabilirliği için doğrudan değer üretiyor.

Tam tablolar: [BENTER.md](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/reports/BENTER.md) · Model modülü: [model_benter.py](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/ganyan/model_benter.py) · Deney betiği: [run_benter_experiments.py](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/scripts/run_benter_experiments.py) · Testler: [test_model_benter.py](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/tests/test_model_benter.py)

## 1. Ne Sınandı?

- `V10` (`155` özellik) içindeki **bugünün AGF'sine dokunan 8 sütun** (`agf_share`, `log_agf`, `own_is_sub_agf`, `own_mate_agf`, `trn_is_sub_agf`, `agf_surge_ratio`, `sleep_wakeup_flag`, `h2h_vs_fav_margin`) tamamen çıkarılarak **147 özellikli saf temel model (`P_temel`)** kuruldu.
- `P_temel` AGF gerektirmediği için `2006–2014` arasındaki AGF'siz 9 yıllık geçmiş de eğitime açıldı (`FUND_06`: 20 yıllık eğitim vs `FUND_15`: 2015→ eğitim). Ayrıca geçmiş oran/AGF kalıntılarını da çıkaran `137` özellikli `SPORT_15` ölçüldü.
- `V10_1s` tabanına karşı 5 iki-aşamalı mimari (`B2P_15`, `B2P_06`, `BRICH_06`, `BSTACK_HGB`, `BBLEND_V10`) standart `Aşama A (2017–2021)` → `Aşama B (2022–2025)` protokolüyle sınandı.

## 2. Temel Sonuçlar

1. **Hiç AGF görmeyen Saf Güç (`FUND_06`) tek başına çok güçlü ve 20 yıllık eğitimden net kazanç alıyor:** `2022–2025` döneminde hiç AGF görmeden 1. tercih isabeti **`32.37%`**, İlk-3 isabeti **`66.90%`** (kapanış AGF `B0`: `34.28%` / `69.04%`; `FUND_15` LL `1.8316` → `FUND_06` LL **`1.8342`**).
2. **Kapanış AGF altında tek aşamalı `V10` vs iki aşamalı adaylar:** `B2P_15` (Aşama A `+0.0163`, Aşama 2 `+0.0208`), `B2P_06` (Aşama A `+0.0164`, Aşama 2 `+0.0227`), `BRICH_06` (Aşama A `+0.0142`, Aşama 2 `+0.0208`), `BSTACK_HGB` (Aşama A `-0.0025`, Aşama 2 `-0.0009`), `BBLEND_V10` (Aşama A `+0.0015`, Aşama 2 `+0.0002`).
4. **Sabah / Erken Gürültülü AGF Avantajı (`2025` tanı):** Erken sabah gürültüsünde (`σ=0.30`) tek aşamalı `V10_1s` log-loss'u `1.7919`'e bozulurken gürültüye uyumlu iki aşamalı `B2P_06` **`1.7979`** veriyor; sabah 07:00'de AGF henüz hiç yokken `V10_1s` `2.1019`'e çökerken `FUND_06` **`1.8424`** ile sağlam kalıyor.
5. **Değer Bahsi (`p >= %8, p/AGF >= 1.5`, `2022–2025`):** `V10_1s` `+7.0%` (`3969` bahis, GA `[-2.5%, +17.0%]`); `FUND_06` `-19.4%` (`8645` bahis, GA `[-26.1%, -12.6%]`); `B2P_06` `-14.2%` (`971` bahis, GA `[-31.5%, +5.6%]`); `BRICH_06` `-18.9%` (`1620` bahis, GA `[-31.3%, -6.5%]`); `BSTACK_HGB` `+5.9%` (`5564` bahis, GA `[-2.9%, +14.4%]`); `BBLEND_V10` `+8.2%` (`3820` bahis, GA `[-1.1%, +18.2%]`).

## 3. Uygulama ve Eğitim İçin Çıkarım

- **Uygulama kartı:** `FUND_06` (`P_temel`) ile `AGF`'yi ekranda iki bağımsız sütun olarak göstermek matematiksel olarak doğrulandı — `FUND_06` AGF'den sıfır kopya çekerek neredeyse halk kadar isabetli tahmin üretiyor.
- **Sabah vs Kapanış:** Kapanışa yakın saatlerde `V10_HLB_CAL` (veya kazanan iki aşamalı model), sabah AGF henüz sığ/yokken ise `FUND_06` / gürültü-uyumlu `B2P_06` çok daha güvenli.
