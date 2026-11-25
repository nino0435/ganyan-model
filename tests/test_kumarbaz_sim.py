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


# ----------------------------------------------------------------------------- diğer bahisler
import itertools
import sqlite3


def xrace(rid, p, ex=None, odds=None, agfp=None, prog=None):
    """Program numarası ve diğer bahis ödemeleri olan sentetik koşu."""
    p = np.array(p, float)
    n = len(p)
    odds = np.array(odds, float) if odds is not None else 0.7 / p
    agfp = np.array(agfp, float) if agfp is not None else p.copy()
    prog = np.arange(1, n + 1) if prog is None else np.array(prog)
    return ks.Race(rid, odds, np.zeros(n, int), p, agfp, prog, ex)


def top_race(i, top, ex, date="2026-03-01"):
    return xrace(f"{date}_A_{i}", [top] + [(1 - top) / 7] * 7, ex)


PLASE_ROWS = {"PLASE": [(({1},), 2.0), (({2},), 3.0)]}


def test_parse_combo():
    assert ks.parse_combo("2/5") == ({2}, {5})
    assert ks.parse_combo("3,6/4") == ({3, 6}, {4})
    assert ks.parse_combo("7") == ({7},)
    assert ks.parse_combo("") is None and ks.parse_combo("2//5") is None and ks.parse_combo("x/2") is None


def test_paid_matches_by_position_and_sums_dead_heat_rows():
    rows = [(({2}, {5}), 17.0), (({2}, {9}), 30.0)]          # ikinci sırada ölü yarış: iki satır
    assert ks.paid(rows, (2, 5)) == 17.0
    assert ks.paid(rows, (2, 9)) == 30.0
    assert ks.paid(rows, (5, 2)) == 0
    assert ks.paid([(({3, 6}, {4}), 8.0)], (6, 4)) == 8.0   # virgüllü kalemde atlardan biri yeter
    assert ks.paid(rows, (2,)) == 0                          # uzunluk uyuşmazsa eşleşmez


def test_harville_probabilities_are_complete_distributions():
    p = np.array([0.5, 0.3, 0.2])
    assert sum(ks.hv("ikili", p, [i, j]) for i, j in itertools.combinations(range(3), 2)) == pytest.approx(1)
    assert sum(ks.hv("sirali", p, [i, j]) for i, j in itertools.permutations(range(3), 2)) == pytest.approx(1)
    assert sum(ks.hv("plase", p, [i]) for i in range(3)) == pytest.approx(2)        # 3 atın hepsi ilk üçte, ikisi ilk ikide
    assert ks.hv("uclu", p, [0, 1, 2]) == pytest.approx(1)                           # 3 at: ilk üç = hepsi, 6 sıra
    assert ks.hv("sirali", p, [0, 1]) == pytest.approx(0.5 * 0.3 / 0.5)


def test_wager_splits_stake_over_combos_and_scales_uclu_unit():
    ex = {"ÜÇLÜ BAHİS": [(({1}, {2}, {3}), 120.0)], **PLASE_ROWS}
    r = xrace("2026-03-01_A_1", [0.4, 0.3, 0.2, 0.1], ex)
    b = ks.wager(r, "uclu", np.array([2, 0, 1]))             # 3 atın 6 sırası da oynanır, doğru sıra içinde
    assert b.win == 1 and b.odds == pytest.approx(120.0 / ks.UCLU_BIRIM_TL / 6)
    assert ks.wager(r, "uclu", np.array([0, 1, 3])).win == 0
    hit = ks.wager(r, "plase", np.array([1]))
    assert (hit.win, hit.odds) == (1, 3.0)
    assert (ks.wager(r, "plase", np.array([3])).win, ks.wager(r, "plase", np.array([3])).odds) == (0, 0.0)


def test_rastgele_is_the_exact_average_over_all_combinations():
    r = xrace("2026-03-01_A_1", [0.25] * 4, {"SIRALI İKİLİ": [(({1}, {2}), 12.0)]})
    b = ks.rastgele(r, "sirali")                              # 4 at: 12 sıralı çift
    assert b.win == pytest.approx(1 / 12) and b.win * b.odds == pytest.approx(12.0 / 12)
    r = xrace("2026-03-01_A_2", [0.125] * 8, PLASE_ROWS)
    b = ks.rastgele(r, "plase")                               # rastgele at 2/8 ihtimalle ilk ikide
    assert b.win == pytest.approx(2 / 8) and b.win * b.odds == pytest.approx((2.0 + 3.0) / 8)
    c = ks.rastgele_cifte(xrace("2026-03-01_A_1", [0.5, 0.5]), xrace("2026-03-01_A_2", [0.5] * 4, {"ÇİFTE": [(({1}, {2}), 20.0)]}))
    assert c.win * c.odds == pytest.approx(20.0 / 8)


def test_plase_persona_plays_four_most_confident_races_that_offer_plase_in_time_order():
    tops = [0.30, 0.35, 0.60, 0.40, 0.45, 0.50]               # 2 numaralı koşuda (0.60) plase yok
    day = [top_race(i, t, PLASE_ROWS if i != 2 else {}) for i, t in enumerate(tops)]
    bets = ks.p_plase(day)
    assert [b.rid[-1] for b in bets] == ["1", "3", "4", "5"]  # 0.35, 0.40, 0.45, 0.50
    assert all(b.win == 1 and b.odds == 2.0 for b in bets)    # 1 numaralı at ilk ikide


def test_ikili_persona_orders_the_pair_and_sirali_needs_the_exact_order():
    p = [0.5, 0.3, 0.1, 0.05, 0.05]
    r = xrace("2026-03-01_A_1", p, {"İKİLİ": [(({1}, {2}), 7.0)], "SIRALI İKİLİ": [(({2}, {1}), 20.0)]})
    assert [(b.win, b.odds) for b in ks.p_ikili([r])] == [(1, 7.0)]      # sıra önemsiz
    assert [(b.win, b.odds) for b in ks.p_sirali([r])] == [(0, 0.0)]     # model 1→2 dedi, gelen 2→1


def test_uclu_persona_waits_for_the_known_payout_unit():
    ex = {"ÜÇLÜ BAHİS": [(({1}, {2}), 0.0)]}
    p = [0.4, 0.3, 0.2, 0.05, 0.05]
    early = xrace("2025-05-31_A_1", p, {"ÜÇLÜ BAHİS": [(({1}, {2}, {3}), 90.0)]})
    late = xrace("2025-06-01_A_1", p, {"ÜÇLÜ BAHİS": [(({1}, {2}, {3}), 90.0)]})
    assert ks.p_uclu([early]) == []                           # birim 2 TL olmadan önce oynanmaz
    b = ks.p_uclu([late])
    assert len(b) == 1 and b[0].odds == pytest.approx(90.0 / ks.UCLU_BIRIM_TL / 6) and b[0].win == 1


def test_cifte_persona_pairs_consecutive_races_with_model_favorites():
    a = xrace("2026-03-01_A_1", [0.6, 0.3, 0.1])
    r = xrace("2026-03-01_A_2", [0.2, 0.5, 0.3], {"ÇİFTE": [(({1}, {2}), 25.0)]})
    other_city = xrace("2026-03-01_B_5", [0.5, 0.5], {"ÇİFTE": [(({1}, {1}), 9.0)]})   # önceki ayağı yok
    assert [i for i, *_ in ks.cifte_pairs([a, r, other_city])] == [1]
    bets = ks.p_cifte([a, r, other_city])
    assert [(b.win, b.odds, b.rid) for b in bets] == [(1, 25.0, "2026-03-01_A_2")]


def test_dengeli_derya_plays_degerci_horses_only_in_plase_races():
    value = xrace("2026-03-01_A_1", [0.30, 0.40, 0.10, 0.10, 0.10], PLASE_ROWS, agfp=[0.10, 0.50, 0.10, 0.20, 0.10])
    no_plase = xrace("2026-03-01_A_2", [0.30, 0.40, 0.10, 0.10, 0.10], {}, agfp=[0.10, 0.50, 0.10, 0.20, 0.10])
    bets = ks.p_dengeli([value, no_plase])
    assert [(b.rid, b.win, b.odds) for b in bets] == [("2026-03-01_A_1", 1, 2.0)]   # 1 numaralı at: p 0,30 / AGF 0,10 = 3 kat


def test_build_altili_hits_only_when_every_leg_is_covered_and_persona_picks_surest(monkeypatch):
    date = "2026-03-01"
    rs = [xrace(f"{date}_A_{k}", [0.6, 0.3, 0.1]) for k in range(1, 7)]
    sure = ks.Alt(tuple(r.rid for r in rs), [{1}] * 6, 5_000.0)             # hep 1 numaralı at kazandı
    miss = ks.Alt(tuple(r.rid for r in rs), [{1}, {1}, {1}, {1}, {1}, {3}], 90_000.0)   # son ayakta 3 numara
    res = ks.build_altili({date: rs}, {date: [sure, miss]})[date]
    cost, prob, hit = res[0].m
    assert 0 < cost <= ks.ALT_BUDGET and hit == 1 and 0 < prob <= 1
    assert res[1].m[2] == 0 and res[1].a[2] == 0                              # kuponda 3 numaralı at yok
    assert res[0].m[0] == pytest.approx(ks.UNIT_TL * round(cost / ks.UNIT_TL))   # maliyet birim biletin tam katı
    # seçici: kuponu en çok tutacak altılıyı oynar, bahis tutarı = maliyet, ödeme = ikramiye / maliyet
    low = ks.AltRec(date, "low", 100.0, (100.0, 0.05, 0), (100.0, 0.04, 0))
    high = ks.AltRec(date, "high", 800.0, (160.0, 0.30, 1), (150.0, 0.25, 0))
    monkeypatch.setattr(ks, "ALT_RES", {date: [low, high]})
    b = ks.p_altili_model([rs[0]])[0]
    assert (b.rid, b.win) == ("high", 1) and b.w == pytest.approx(160.0 / ks.BASE) and b.odds == pytest.approx(800.0 / 160.0)
    assert ks.p_altili_agf([rs[0]])[0].rid == "high" and ks.p_altili_agf([rs[0]])[0].win == 0
    assert ks.p_altili_model([xrace("2026-03-02_A_1", [0.5, 0.5])]) == []     # o gün altılı yok


def test_stake_weight_scales_flat_stake_and_money_weighted_roi(monkeypatch):
    kupon = bet(2.0, 1)._replace(w=4.0)                                        # 200 TL'lik kupon, 2 kat öder
    r = ks.simulate([[kupon]], "flat")
    assert r["staked"] == pytest.approx(200) and r["final"] == pytest.approx(10_000 - 200 + 400)
    plans = [[bet(2.0, 1), bet(0.0, 0)._replace(w=3.0)]]                       # 1 birim kazandı (2), 3 birim kaybetti
    assert ks.pooled(plans)["roi"] == pytest.approx(2.0 / 4 - 1)
    assert ks.unit_roi_n(plans[0]) == (2, pytest.approx(2.0 / 4 - 1))
    boot = np.zeros((5, 1), int)
    point, lo, hi = ks.unit_roi_ci(plans, boot)
    assert point == pytest.approx(-0.5) and lo == pytest.approx(-0.5) and hi == pytest.approx(-0.5)


def test_roi_diff_ci_is_the_difference_of_the_two_rois():
    a = [[bet(4.0, 1)], [bet(3.0, 0)]]                       # getiri +%100
    b = [[bet(1.0, 1)], [bet(1.0, 1)]]                       # getiri %0
    boot = np.random.default_rng(0).integers(0, 2, size=(20, 2))
    point, lo, hi = ks.roi_diff_ci(a, b, boot)
    assert point == pytest.approx(1.0) == pytest.approx(ks.pooled(a)["roi"] - ks.pooled(b)["roi"])
    assert lo <= hi


def test_build_days_attaches_program_numbers_and_exotic_rows():
    d = pd.DataFrame({
        "race_id": ["2025-01-01_A_1"] * 2 + ["2025-01-01_A_2"] * 2,
        "date": ["2025-01-01"] * 4, "post_time": ["14:00"] * 2 + ["14:30"] * 2, "city": ["A"] * 4, "race_no": [1, 1, 2, 2],
        "prog_no": [2.0, 1.0, np.nan, 1.0], "ganyan": [5.0, 2.0, 4.0, 1.5], "win": [0, 1, 1, 0],
        "p": [0.4, 0.6, 0.3, 0.7], "agfp": [0.5, 0.5, 0.4, 0.6]})
    ex = {"2025-01-01_A_1": {"PLASE": [(({1},), 1.4)]}}
    rs = ks.build_days(d, ex)["2025-01-01"]
    assert rs[0].prog.tolist() == [1, 2] and rs[0].ex == ex["2025-01-01_A_1"]
    assert rs[1].prog is None and rs[1].ex == {}                              # program numarası eksik: diğer bahisler oynanamaz


def test_load_bets_and_altili_filter_malformed_and_multi_leg_rows():
    con = sqlite3.connect(":memory:")
    con.execute("create table bets (race_id text, bet text, combo text, payout real)")
    con.execute("create table altili (date text, city text, which int, start_race int, end_race int, legs text, payout real)")
    rid = "2025-03-01_Ankara_2"
    con.executemany("insert into bets values (?,?,?,?)", [
        (rid, "PLASE", "3", 1.8), (rid, "PLASE", "3,6/4,8", 280.0),                     # çok ayaklı "7'li plase" elenir
        (rid, "İKİLİ", "2/5", 5.6), (rid, "SIRALI İKİLİ", "5/2", 17.1),
        (rid, "1. ÇİFTE", "2/2", 17.35), (rid, "2. ÇİFTE", "2/3", 14.5),                 # yalnız 2. ayağı bu koşu olan geçer
        (rid, "ÜÇLÜ BAHİS", "2//1", 61.0), (rid, "GANYAN", "2", 5.5),                    # bozuk kombinasyon ve ilgisiz bahis elenir
        ("2021-12-31_Ankara_2", "PLASE", "3", 1.8)])                                      # dönem dışı
    con.executemany("insert into altili values (?,?,?,?,?,?,?)", [
        ("2025-03-01", "Ankara", 1, 1, 6, "[[2], [3], [3], [5], [8, 9], [6]]", 1234.5),
        ("2025-03-01", "Ankara", 2, 3, 7, "[[2], [3], [3], [5], [8], [6]]", 99.0),      # 5 ayak: elenir
        ("2025-03-01", "Izmir", 1, 1, 6, "[[2], [3]]", 99.0)])                            # 6 ayak değil: elenir
    ex = ks.load_bets(con)
    assert set(ex) == {rid}
    assert ex[rid]["PLASE"] == [(({3},), 1.8)]
    assert ex[rid]["İKİLİ"] == [(({2}, {5}), 5.6)] and ex[rid]["SIRALI İKİLİ"] == [(({5}, {2}), 17.1)]
    assert ex[rid]["ÇİFTE"] == [(({2}, {2}), 17.35)] and "ÜÇLÜ BAHİS" not in ex[rid] and "GANYAN" not in ex[rid]
    alt = ks.load_altili(con)
    assert list(alt) == ["2025-03-01"] and len(alt["2025-03-01"]) == 1
    a = alt["2025-03-01"][0]
    assert a.rids[0] == "2025-03-01_Ankara_1" and a.rids[-1] == "2025-03-01_Ankara_6" and a.legs[4] == {8, 9} and a.pay == 1234.5


def test_bench_plays_the_same_races_with_model_favorite_and_random_picks():
    # model 1. at (p 0,5), kapanış favorisi 2. at (en kısa oran)
    r = xrace("2026-03-01_A_1", [0.5, 0.2, 0.1, 0.05, 0.05, 0.04, 0.03, 0.03], PLASE_ROWS,
              odds=[3.0, 1.5, 6.0, 12.0, 12.0, 15.0, 20.0, 20.0])
    days, dates = {"2026-03-01": [r]}, ["2026-03-01"]
    assert [b.odds for b in ks.bench(days, dates, "plase", "model")[0]] == [2.0]       # 1 numaralı at plase aldı
    assert [b.odds for b in ks.bench(days, dates, "plase", "favori")[0]] == [3.0]      # 2 numaralı at plase aldı
    rnd = ks.bench(days, dates, "plase", "rastgele")[0][0]
    assert rnd.win * rnd.odds == pytest.approx((2.0 + 3.0) / 8)
