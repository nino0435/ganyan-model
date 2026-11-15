"""probe_tips için çevrimdışı birim testleri (discover_links, detect_signals, çevrimdışı akış)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import probe_tips as pt


def test_discover_links_gazetevatan_and_milliyet():
    vatan_html = """
    <html><body>
      <a href="/sampiy10/at-yarisi/">At Yarışı</a>
      <a href="/sampiy10/sayfa-2">Sonraki Sayfa</a>
      <a href="/sampiy10/15-kasim-istanbul-at-yarisi-tahminleri-2198501">İstanbul Tahminleri</a>
      <a href="https://www.gazetevatan.com/sampiy10/15-kasim-istanbul-at-yarisi-tahminleri-2198501#yorumlar">Yorum</a>
      <a href="https://gazetevatan.com/sampiy10/ankara-altili-ganyan-kuponu-2198490/">Ankara Kuponu</a>
      <a href="https://twitter.com/intent/tweet?url=https://www.gazetevatan.com/sampiy10/dis-link-2199999">Paylaş</a>
      <a href="/sampiy10/gorsel-2198501.jpg">Görsel</a>
    </body></html>
    """
    vatan_links = pt.discover_links(
        vatan_html,
        "https://www.gazetevatan.com/sampiy10/at-yarisi/",
        pt.DISCOVERY_PATTERNS["gazetevatan"],
    )
    assert vatan_links == [
        "https://www.gazetevatan.com/sampiy10/15-kasim-istanbul-at-yarisi-tahminleri-2198501",
        "https://gazetevatan.com/sampiy10/ankara-altili-ganyan-kuponu-2198490/",
    ]

    milliyet_html = """
    <html><body>
      <a href="/skorer/afsin-yakuboglu/">Afşin Yakuboğlu</a>
      <a href="/skorer/afsin-yakuboglu/altili-ganyanda-bugun-15-kasim-7483921">Altılı ganyanda bugün (15 Kasım)</a>
      <a href="/skorer/afsin-yakuboglu/altili-ganyanda-bugun-5-mart-7410012">Altılı ganyanda bugün (5 Mart)</a>
      <a href="/skorer/futbol/galatasaray-haberi-7483999">Futbol Haberi</a>
    </body></html>
    """
    milliyet_links = pt.discover_links(
        milliyet_html,
        "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/",
        pt.DISCOVERY_PATTERNS["milliyet"],
    )
    assert milliyet_links == [
        "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/altili-ganyanda-bugun-15-kasim-7483921",
        "https://www.milliyet.com.tr/skorer/afsin-yakuboglu/altili-ganyanda-bugun-5-mart-7410012",
    ]


def test_discover_links_fanatik_and_sabah_tahmin_filters():
    fanatik_html = """
    <html><body>
      <nav>
        <a href="/tahminler">Tahminler</a>
        <a href="/iddaa/gunun-tahminleri-2561099">İddaa Tahminleri</a>
        <a href="/haberleri/at-yarisi-tahminleri">Etiket</a>
      </nav>
      <main>
        <a href="/at-yarisi/15-kasim-istanbul-at-yarisi-tahminleri-2561005">İstanbul Tahminleri</a>
        <a href="/hipodrom/izmir-altili-tahmin-kuponu-2561001">İzmir Kuponu</a>
        <a href="/at-yarisi/veliefendi-hipodromunda-kupa-heyecani-2561008">Genel Haber</a>
      </main>
    </body></html>
    """
    fanatik_links = pt.discover_links(
        fanatik_html,
        "https://www.fanatik.com.tr/at-yarisi",
        pt.DISCOVERY_PATTERNS["fanatik"],
    )
    assert fanatik_links == [
        "https://www.fanatik.com.tr/at-yarisi/15-kasim-istanbul-at-yarisi-tahminleri-2561005",
        "https://www.fanatik.com.tr/hipodrom/izmir-altili-tahmin-kuponu-2561001",
    ]

    sabah_html = """
    <html><body>
      <a href="/at-yarisi">At Yarışı</a>
      <a href="/spor/at-yarisi/2026/11/15/istanbul-altili-ganyan-tahminleri">15 Kasım Tahmin</a>
      <a href="/spor/at-yarisi/2026/11/14/tahminler">14 Kasım Tahminler</a>
      <a href="/spor/futbol/2026/11/15/milli-mac-kadrolari">Milli Maç</a>
    </body></html>
    """
    sabah_links = pt.discover_links(
        sabah_html,
        "https://www.sabah.com.tr/at-yarisi",
        pt.DISCOVERY_PATTERNS["sabah"],
    )
    assert sabah_links == [
        "https://www.sabah.com.tr/spor/at-yarisi/2026/11/15/istanbul-altili-ganyan-tahminleri",
        "https://www.sabah.com.tr/spor/at-yarisi/2026/11/14/tahminler",
    ]


def test_detect_signals_positive_coupons_and_banko():
    sporx_like_html = """
    <html>
      <head><title>At Yarışı Hazır Kuponlar</title></head>
      <body>
        <div class="kupon">
          <h3>Fenomen Tilki</h3>
          <p>1. Ayak: 3-5-7-11</p>
          <p>2. Ayak: 2/6/9</p>
          <p>3. Ayak: 4, 8, 12</p>
        </div>
        <footer>© 2026 Tüm hakları saklıdır</footer>
      </body>
    </html>
    """
    sig = pt.detect_signals(sporx_like_html)
    assert sig["has_picks_text"] is True
    assert sig["has_date_stamp"] is False
    assert sig["uses_js_only"] is False
    assert sig["paywall_hint"] is False
    assert sig["body_text_len"] > 40

    banko_html = """
    <html><body>
      <article><header><h1>Günün Yorumu</h1></header>
        <p>1. AYAK: 5 numaralı KARAYEL günün bankosu olarak tek yazılabilir.</p>
      </article>
    </body></html>
    """
    sig_banko = pt.detect_signals(banko_html)
    assert sig_banko["has_picks_text"] is True
    assert sig_banko["has_date_stamp"] is False


def test_detect_signals_negative_news_and_false_positive_guards():
    plain_news_html = """
    <html>
      <head>
        <meta property="article:published_time" content="">
        <meta itemprop="datePublished" content="">
      </head>
      <body>
        <nav><a href="/iddaa">İddaa Banko Kuponlar</a></nav>
        <header><a href="/giris">Üye Girişi</a></header>
        <article>
          <p>İstanbul Veliefendi Hipodromu'nda sonbahar sezonu kupalı koşularla devam ediyor.</p>
          <p>Turnuvanın 1. ayak mücadelesi 15/11/2026 tarihinde tamamlandı.</p>
        </article>
      </body>
    </html>
    """
    sig = pt.detect_signals(plain_news_html)
    assert sig["has_picks_text"] is False
    assert sig["has_date_stamp"] is False
    assert sig["uses_js_only"] is False
    assert sig["paywall_hint"] is False
    assert pt.detect_signals("") == {
        "has_picks_text": False,
        "has_date_stamp": False,
        "body_text_len": 0,
        "uses_js_only": False,
        "paywall_hint": False,
    }


def test_detect_signals_js_only_vs_ssr():
    spa_shell = """
    <html>
      <head>
        <title>Bülten Uygulaması</title>
        <script src="/static/runtime.js"></script>
        <script src="/static/vendors.js"></script>
        <script src="/static/main.js"></script>
        <script>window.__MOCK__ = "1. ayak 3-5-7 banko"; const x = item.datePublished;</script>
      </head>
      <body><div id="root">Yükleniyor...</div></body>
    </html>
    """
    sig_js = pt.detect_signals(spa_shell)
    assert sig_js["uses_js_only"] is True
    assert sig_js["has_picks_text"] is False
    assert sig_js["has_date_stamp"] is False
    assert sig_js["body_text_len"] < 500

    long_prose = "At yarışı bülteni ve koşu analizleri. " * 20
    ssr_html = f"""
    <html>
      <head>
        <script src="/a.js"></script>
        <script src="/b.js"></script>
        <script src="/c.js"></script>
      </head>
      <body><article>{long_prose}</article></body>
    </html>
    """
    sig_ssr = pt.detect_signals(ssr_html)
    assert sig_ssr["body_text_len"] >= 500
    assert sig_ssr["uses_js_only"] is False


def test_detect_signals_date_stamps_and_paywall_variants():
    meta_html = """
    <html>
      <head><meta content="2026-11-15T08:45:00+03:00" property="article:published_time"></head>
      <body><p>1. Ayak: 1–4–9</p></body>
    </html>
    """
    assert pt.detect_signals(meta_html)["has_date_stamp"] is True
    assert pt.detect_signals(meta_html)["has_picks_text"] is True

    jsonld_html = """
    <html>
      <head>
        <script type="application/ld+json">
          {"@type": "NewsArticle", "datePublished": "2026-11-15T09:00:00+03:00", "isAccessibleForFree": false}
        </script>
      </head>
      <body><p>VIP tahmin özeti.</p></body>
    </html>
    """
    sig_jl = pt.detect_signals(jsonld_html)
    assert sig_jl["has_date_stamp"] is True
    assert sig_jl["paywall_hint"] is True

    tr_label_html = """
    <html><body>
      <span>YAYINLANMA TARİHİ: 15 Kasım 2026</span>
      <div class="paywall-banner">Bu içeriği görüntülemek için üye olmanız gerekmektedir.</div>
    </body></html>
    """
    sig_tr = pt.detect_signals(tr_label_html)
    assert sig_tr["has_date_stamp"] is True
    assert sig_tr["paywall_hint"] is True


def test_offline_probe_truncation_article_cap_and_markdown(tmp_path):
    padding = "X" * 420_000
    big_coupon_html = (
        "<html><head><title>Hazır Kuponlar</title></head><body>"
        "<p>Fenomen Tilki kuponu: 1. Ayak: 2-5-8-11 / 2. Ayak: 4 BANKO / 3. Ayak: 1, 3, 7, 9 "
        + ("ek açıklama metni " * 25)
        + "</p>"
        f"<div>{padding}</div></body></html>"
    ).encode("utf-8")

    vatan_list_html = """
    <html><body>
      <a href="/sampiy10/eski-yazi-2198001">1</a>
      <a href="/sampiy10/orta-yazi-2198002">2</a>
      <a href="/sampiy10/yeni-yazi-2198005">5</a>
      <a href="/sampiy10/yeni-yazi-2198004">4</a>
      <a href="/sampiy10/yeni-yazi-2198003">3</a>
    </body></html>
    """.encode("utf-8")

    art_html = (
        '<html><head><meta property="article:published_time" content="2026-11-15T09:00:00+03:00"></head>'
        "<body><article>1. Ayak: 6-8-10 altılı tahmini.</article></body></html>"
    ).encode("utf-8")

    cf_403_html = b"<html><head><title>Attention Required! | Cloudflare</title></head><body>blocked</body></html>"

    def fake_fetch(url):
        if url == "https://www.sporx.com/at-yarisi-hazir-kuponlar":
            return 200, big_coupon_html, url, "text/html; charset=utf-8", None
        if url == "https://www.gazetevatan.com/sampiy10/at-yarisi/":
            return 200, vatan_list_html, url, "text/html; charset=utf-8", None
        if url.startswith("https://www.gazetevatan.com/sampiy10/") and url.endswith(("3", "4", "5")):
            return 200, art_html, url, "text/html; charset=utf-8", None
        if "liderform.com.tr" in url:
            return 403, cf_403_html, url, "text/html", "HTTP 403"
        return None, b"", url, "", "TimeoutError: timed out"

    out_dir = tmp_path / "raw_tips"
    probe_data = pt.run_probe(out_dir=str(out_dir), delay=0, fetch_fn=fake_fetch, sleep_fn=lambda _: None)

    # En çok 3 en yeni gazetevatan yazısı (2198005, 2198004, 2198003) indirilmeli
    assert probe_data["discovered"]["gazetevatan"]["fetched"] == [
        "https://www.gazetevatan.com/sampiy10/yeni-yazi-2198005",
        "https://www.gazetevatan.com/sampiy10/yeni-yazi-2198004",
        "https://www.gazetevatan.com/sampiy10/yeni-yazi-2198003",
    ]

    sporx_file = out_dir / "sporx__at-yarisi-hazir-kuponlar.html"
    assert sporx_file.exists()
    assert sporx_file.stat().st_size == pt.MAX_RAW_BYTES
    assert sporx_file.stat().st_size <= 400 * 1024

    for rec in probe_data["records"]:
        assert len(rec["snippet"]) <= 200

    md = pt.render_inventory_markdown(probe_data, measured_at="2026-11-15 14:45 +03")
    assert "| `sporx` | liste |" in md
    assert "Cloudflare engeli (HTTP 403)" in md
    assert "Hata/zaman aşımı" in md
