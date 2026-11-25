"""Kumarbaz simülasyonu: bahis büyüklüğü, iflas, seçim kuralları (sentetik veri, DB gerekmez)."""
import numpy as np
import pandas as pd
import pytest

from scripts import run_kumarbaz_sim as ks


def bet(odds, win, p=0.1, agfp=0.1, rid="r"):
    return ks.Bet(odds, win, p, agfp, rid)


def race(rid, odds, win=None, p=None, agfp=None):
    odds = np.array(odds, float)
    n = len(odds)
    win = np.zeros(n, int) if win is None else np.array(win)
    p = np.full(n, 1.0 / n) if p is None else np.array(p, float)
    agfp = np.full(n, 1.0 / n) if agfp is None else np.array(agfp, float)
    return ks.Race(rid, odds, win, p, agfp)


def test_flat_win_loss_accounting():
    """50 TL kaybeder, sonra 50 TL yatırıp 3,0 oranla 150 TL alır."""
    r = ks.simulate([[bet(3.0, 0)], [bet(3.0, 1)]], "flat")
    assert r["final"] == pytest.approx(10_000 - 50 + (-50 + 150))
    assert (r["n"], r["hits"], r["bust"]) == (2, 1, None)
    assert r["staked"] == pytest.approx(100)
    assert r["ret"] == pytest.approx(150)


def test_flat_bust_plays_the_remainder_then_stops(monkeypatch):
    """Kasa 120 TL: 50, 50, sonra kalan 20 TL'yi basıp iflas eder; sonraki günler oynanmaz."""
    monkeypatch.setattr(ks, "BANK0", 120.0)
    r = ks.simulate([[bet(2.0, 0)]] * 5, "flat")
    assert r["bust"] == 2
    assert r["n"] == 3
    assert r["staked"] == pytest.approx(120)
    assert r["final"] == pytest.approx(0)


def test_bitik_doubles_after_loss_and_resets_after_win():
    plans = [[bet(2.0, 0), bet(2.0, 0), bet(2.0, 0), bet(2.0, 1)], [bet(2.0, 0)]]
    r = ks.simulate(plans, "bitik")
    # 50 + 100 + 200 + 400 (tutar, 800 döner) ve ertesi gün tekrar 50
    assert r["staked"] == pytest.approx(800)
    assert r["ret"] == pytest.approx(800)
    assert (r["n"], r["hits"]) == (5, 1)
    assert r["final"] == pytest.approx(10_000)


def test_bitik_goes_all_in_when_bank_is_short(monkeypatch):
    monkeypatch.setattr(ks, "BANK0", 300.0)
    r = ks.simulate([[bet(2.0, 0)] * 4], "bitik")
    # 50, 100, kalan 150 (istenen 200): kasa biter
    assert r["staked"] == pytest.approx(300)
    assert r["n"] == 3
    assert r["bust"] == 0


def test_kelly_sizing_edge_cap_and_daily_limit():
    # tahmini ödeme = 0,70 / 0,10 = 7,0 ; p = 0,10 -> avantaj yok -> bahis yok
    assert ks.stake("kelly", 10_000, 0, bet(5.0, 1, p=0.10, agfp=0.10), 10_000, 0) == 0.0
    # p = 0,20 -> avantaj 0,4 ; çeyrek Kelly = 0,25 * 0,4 / 6 = 1/60 -> kasanın %1,67'si
    s = ks.stake("kelly", 10_000, 0, bet(5.0, 1, p=0.20, agfp=0.10), 10_000, 0)
    assert s == pytest.approx(10_000 / 60)
    # çok büyük avantaj: kasanın %2'si ile sınırlı
    big = bet(5.0, 1, p=0.50, agfp=0.10)
    assert ks.stake("kelly", 10_000, 0, big, 10_000, 0) == pytest.approx(200.0)
    # günlük sınır: gün başı kasanın %8'i = 800, 700 harcanmış -> en çok 100
    assert ks.stake("kelly", 10_000, 0, big, 10_000, 700) == pytest.approx(100.0)


def test_temkinli_picks_four_strongest_favorites_in_time_order():
    fav_odds = [2.5, 1.5, 3.0, 1.2, 2.0, 4.0]
    day = [race(f"r{i}", [o, o * 3]) for i, o in enumerate(fav_odds)]
    assert [b.odds for b in ks.p_temkinli(day)] == [2.5, 1.5, 1.2, 2.0]


def test_cesur_picks_biggest_fields_and_shortest_longshot():
    sizes = [3, 5, 12, 8, 10]
    day = [race(f"r{i}", [1.5] * (n - 2) + [10.0 + i, 40.0 + i]) for i, n in enumerate(sizes)]
    # en kalabalık 4 saha: n = 12, 10, 8, 5 -> koşu sırasıyla 5 (i=1), 12 (i=2), 8 (i=3), 10 (i=4); oranı >= 10 olan en kısa
    assert [b.odds for b in ks.p_cesur(day)] == [11.0, 12.0, 13.0, 14.0]


def test_degerci_rule_uses_model_over_agf_ratio_and_skips_races_without_model():
    # A: fark yok. B: 3. at oran 3,0 ve p 0,30 / agf 0,10. C: 3. at p < %8 olduğu için elenir, 2. at uygun.
    a = race("A", [2.0, 3.0, 5.0], p=[0.5, 0.3, 0.2], agfp=[0.5, 0.3, 0.2])
    b = race("B", [1.8, 4.0, 9.0], p=[0.4, 0.3, 0.3], agfp=[0.7, 0.2, 0.1])
    c = race("C", [1.5, 6.0, 30.0], p=[0.5, 0.45, 0.05], agfp=[0.9, 0.09, 0.01])
    d = race("D", [2.0, 3.0], p=[np.nan, np.nan], agfp=[0.5, 0.5])        # modeli yok
    assert [x.odds for x in ks.p_degerci([a, b, c, d])] == [9.0, 6.0]


def test_build_days_orders_races_by_post_time_and_runners_by_prog_no():
    d = pd.DataFrame({
        "race_id": ["2025-01-01_B_1"] * 2 + ["2025-01-01_A_1"] * 2,
        "date": ["2025-01-01"] * 4,
        "post_time": ["15:00"] * 2 + ["14:00"] * 2,
        "city": ["B"] * 2 + ["A"] * 2,
        "race_no": [1] * 4,
        "prog_no": [2, 1, 2, 1],
        "ganyan": [5.0, 2.0, 4.0, 1.5],
        "win": [0, 1, 1, 0],
        "p": [0.4, 0.6, 0.3, 0.7],
        "agfp": [0.5, 0.5, 0.4, 0.6],
    })
    rs = ks.build_days(d)["2025-01-01"]
    assert [r.rid for r in rs] == ["2025-01-01_A_1", "2025-01-01_B_1"]
    assert rs[0].odds.tolist() == [1.5, 4.0]
    assert rs[0].win.tolist() == [0, 1]


def test_pooled_stats():
    p = ks.pooled([[bet(2.0, 1)], [bet(4.0, 0), bet(3.0, 1)]])
    assert p["n"] == 3
    assert p["per_day"] == pytest.approx(1.5)
    assert p["hit"] == pytest.approx(2 / 3)
    assert p["roi"] == pytest.approx((2.0 + 0.0 + 3.0) / 3 - 1)
    assert (p["avg"], p["med"]) == (pytest.approx(2.5), pytest.approx(2.5))


def test_unit_roi_ci_point_estimate_matches_pooled():
    plans = [[bet(2.0, 1)], [bet(4.0, 0), bet(3.0, 1)], [bet(5.0, 0)]]
    boot = np.random.default_rng(0).integers(0, len(plans), size=(50, len(plans)))
    point, lo, hi = ks.unit_roi_ci(plans, boot)
    assert point == pytest.approx(ks.pooled(plans)["roi"])
    assert lo <= point <= hi


def test_rejim_groups_consecutive_months_with_same_takeout():
    d = pd.DataFrame({
        "race_id": ["a", "b", "c", "d"],
        "date": ["2024-01-05", "2024-02-05", "2024-02-06", "2024-03-05"],
        "S": [1.344, 1.344, 1.344, 1.441],
    })
    assert ks.rejim(d) == [["2024-01", "2024-02", 0.26], ["2024-03", "2024-03", 0.31]]
