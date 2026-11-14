"""probe_sources için ağsız birim testleri (HTML sayaçları, toplam ayrıştırma, sayfalama, bütçe)."""
import datetime as dt
import gzip
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import probe_sources as ps


def test_parse_result_html_stats_agf_variants_and_fields():
    sample_html = """
    <html><body>
      <table class="tablesorter">
        <thead>
          <tr>
            <th class="gunluk-GunlukYarisSonuclari-AtAdi3">At İsmi</th>
            <th class="gunluk-GunlukYarisSonuclari-AGFORAN">AGF</th>
            <th class="gunluk-GunlukYarisSonuclari-Gny">Gny</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="gunluk-GunlukYarisSonuclari-AtAdi3"><a href="#">BOLD PILOT</a></td>
            <td class="gunluk-GunlukYarisSonuclari-AGFORAN">%28.45(1)</td>
            <td class="gunluk-GunlukYarisSonuclari-Gny">2,25</td>
            <td class="gunluk-GunlukYarisSonuclari-Fark"></td>
            <td class="gunluk-GunlukYarisSonuclari-GecCikis">-</td>
            <td class="gunluk-GunlukYarisSonuclari-Hc">72</td>
          </tr>
          <tr>
            <td class="gunluk-GunlukYarisSonuclari-AtAdi3">KARAYEL</td>
            <td class="gunluk-GunlukYarisSonuclari-AGFORAN"> % 14,10 (3) </td>
            <td class="gunluk-GunlukYarisSonuclari-Gny">5,40</td>
            <td class="gunluk-GunlukYarisSonuclari-Fark">1,5 Boy</td>
            <td class="gunluk-GunlukYarisSonuclari-GecCikis">2 Boy</td>
            <td class="gunluk-GunlukYarisSonuclari-Hc">-</td>
          </tr>
          <tr>
            <td class="gunluk-GunlukYarisSonuclari-AtAdi3">ESKİ AT</td>
            <td class="gunluk-GunlukYarisSonuclari-AGFORAN">-</td>
            <td class="gunluk-GunlukYarisSonuclari-Gny">-</td>
            <td class="gunluk-GunlukYarisSonuclari-Fark">Boyun</td>
            <td class="gunluk-GunlukYarisSonuclari-GecCikis"></td>
            <td class="gunluk-GunlukYarisSonuclari-Hc">&nbsp;</td>
          </tr>
          <tr>
            <td class="gunluk-GunlukYarisSonuclari-AtAdi3">BOŞ AGF AT</td>
            <td class="gunluk-GunlukYarisSonuclari-AGFORAN">&nbsp;</td>
            <td class="gunluk-GunlukYarisSonuclari-Gny"></td>
            <td class="gunluk-GunlukYarisSonuclari-Fark">-</td>
            <td class="gunluk-GunlukYarisSonuclari-GecCikis">3,5 Boy</td>
            <td class="gunluk-GunlukYarisSonuclari-Hc">54</td>
          </tr>
        </tbody>
      </table>
      <div class="kosu-alt">
        <strong>Son 800 :</strong>0.54.88-0.54.96
        <span>Son 800 : -</span>
        <span>Son 800 : 0.52.10</span>
      </div>
      <div class="bahisler">
        <p>GANYAN 15 2,25 ₺</p>
        <p>1. 6'LI GANYAN 9/5/10,11/4/5/15 1.741,48 ₺</p>
        <p>2. 6’LI GANYAN 1/2/3/4/5/6 842,50 ₺</p>
      </div>
      <div class="havuz">
        <h4>Dağıtılacak Tutarlar</h4>
        <table><tr><td>1. 6'LI GANYAN</td><td>4.500.000,00 ₺</td></tr></table>
      </div>
    </body></html>
    """
    st = ps.parse_result_html_stats(sample_html)
    assert st["runner_rows"] == 4
    assert st["agf_pct"] == 2
    assert st["gny"] == 2
    assert st["fark"] == 2
    assert st["gec_cikis"] == 2
    assert st["hc"] == 2
    assert st["son_800"] == 2
    assert st["altili"] == 2
    assert st["has_dagitilacak"] is True


def test_altili_apostrophe_and_entity_forms():
    html_snippet = """
    <div>
      <span>6&#39;LI GANYAN 3/4/1/2/8/9 120,00 TL</span>
      <span>6&rsquo;lı Ganyan 7/2/5/1/3/4 980,50 ₺</span>
      <span>1. 6’LI GANYAN DEVİR</span>
    </div>
    """
    st = ps.parse_result_html_stats(html_snippet)
    assert st["runner_rows"] == 0
    assert st["altili"] == 3
    assert st["has_dagitilacak"] is False


def test_parse_total_count_variants():
    assert ps.parse_total_count("<div>Toplam 230 sonuçtan 50 tanesi gösteriliyor</div>") == 230
    assert ps.parse_total_count("<span>Toplam 4.512 sonuçtan 50 tanesi gösteriliyor.</span>") == 4512
    assert ps.parse_total_count("<p>Toplam 18</p>") == 18
    assert ps.parse_total_count("<div>Toplam 0 sonuçtan 0 tanesi gösteriliyor</div>") == 0
    assert ps.parse_total_count("<div>Aradığınız kriterlere uygun kayıt bulunamadı.</div>") == 0
    assert ps.parse_total_count("") == 0


def test_parse_domestic_cities_filters_foreign_tracks():
    day_html = """
    <div class="gunluk-tabs">
      <a id="İstanbul" data-sehir-id="3" href="#">İstanbul (32. Y.G.)</a>
      <a data-sehir-id="1" id="Adana" href="#"><span>Adana (18. Y.G.)</span></a>
      <a id="Gulfstream Park ABD" data-sehir-id="45" href="#">Gulfstream Park ABD</a>
      <a id="İstanbul" data-sehir-id="3" href="#">İstanbul (32. Y.G.)</a>
    </div>
    """
    assert ps.parse_domestic_cities(day_html) == [("İstanbul", "3"), ("Adana", "1")]
    assert ps.parse_domestic_cities("<div>Bugün yarış yok</div>") == []


def test_extract_galop_pagination_and_komiser_pdfs():
    js_html = """
    <script>
      function loadMoreRows(p) {
        var u = '/TR/YarisSever/Query/DataRows/IdmanIstatistikleri?QueryParameter_IDMANTARIH=15%2F06%2F2022&amp;PageNumber=' + p;
        $.get(u);
      }
    </script>
    """
    pg = ps.extract_galop_pagination_info(js_html)
    assert pg["param_name"] == "PageNumber"
    assert pg["candidate_params"][0] == "PageNumber"

    komiser_html = """
    <div>
      <a href="https://medya-cdn.tjk.org/raporftp/YarisBilgileri/2015/201506141.pdf">İndir</a>
      <a href="https://medya-cdn.tjk.org/raporftp/YarisBilgileri/2015/201506141.pdf">Tekrar</a>
      <a href="/raporftp/YarisBilgileri/2015/201506142.pdf">Rapor 2</a>
    </div>
    """
    pdfs = ps.parse_komiser_pdfs(komiser_html)
    assert pdfs == [
        "https://medya-cdn.tjk.org/raporftp/YarisBilgileri/2015/201506141.pdf",
        "https://www.tjk.org/raporftp/YarisBilgileri/2015/201506142.pdf",
    ]
    assert ps.mid_june_sunday(2015) == dt.date(2015, 6, 14)


def test_analyze_external_html_and_cloudflare_detection():
    ext_html = """
    <html>
      <head><title>Yeni Beygir - Yarış Sonuçları</title></head>
      <body>
        <script src="/static/app.2026-01-01.js"></script>
        <a href="/01-05-2026/istanbul/1/sonuclar">1. Koşu</a>
        <a href="/sonuclar?tarih=2026-11-14">Sonuçlar</a>
        <table><thead><tr><th>Sıra</th><th>At Adı</th><th>Derece</th></tr></thead></table>
      </body>
    </html>
    """
    info = ps.analyze_external_html(ext_html, 200)
    assert info["title"] == "Yeni Beygir - Yarış Sonuçları"
    assert info["th_headers"] == ["Sıra", "At Adı", "Derece"]
    assert "/{DD-MM-YYYY}/istanbul/1/sonuclar" in info["date_patterns"]
    assert "/sonuclar?tarih={YYYY-MM-DD}" in info["date_patterns"]
    assert info["blocked"] is None

    cf_html = "<html><head><title>Just a moment...</title></head><body>__cf_chl_opt</body></html>"
    cf_info = ps.analyze_external_html(cf_html, 403)
    assert cf_info["blocked"] is not None
    assert "Cloudflare" in cf_info["blocked"]


def test_probe_client_saves_gzip_and_stops_at_max_requests(tmp_path):
    payload = "<html><body>Merhaba TJK</body></html>".encode("utf-8")
    calls = []

    def fake_fetch(url, extra_headers):
        calls.append((url, extra_headers))
        return 200, payload

    client = ps.ProbeClient(
        raw_dir=str(tmp_path),
        max_requests=2,
        fetch_fn=fake_fetch,
        sleep_fn=lambda _: None,
    )
    st1, b1, p1 = client.fetch("https://www.tjk.org/a", "tjk", "ornek_1", extra_headers=ps.XHR_HEADERS)
    assert st1 == 200 and b1 == payload
    assert p1 is not None and p1.endswith(".html.gz")
    with gzip.open(p1, "rb") as gz:
        assert gz.read() == payload

    client.fetch("https://www.tjk.org/b", "tjk", "ornek_2")
    assert client.request_count == 2

    with pytest.raises(ps.MaxRequestsReached):
        client.fetch("https://www.tjk.org/c", "tjk", "ornek_3")
    assert client.stopped_by_limit is True
    assert len(calls) == 2
