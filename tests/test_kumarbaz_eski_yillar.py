"""Kumarbaz eski yıllar sınaması: pencere ve özet hesapları (sentetik veri, DB gerekmez)."""
import pandas as pd
import pytest

from scripts import run_kumarbaz_eski_yillar as ey
from scripts import run_kumarbaz_sim as ks


def bet(odds, win, rid="r"):
    return ks.Bet(odds, win, 0.2, 0.1, rid)


def test_pencere_selects_days_by_year_range():
    dates = ["2018-05-01", "2019-01-02", "2021-12-31", "2022-01-01"]
    d, p = ey.pencere(dates, [[1], [2], [3], [4]], "2019", "2021")
    assert d == ["2019-01-02", "2021-12-31"] and p == [[2], [3]]


def test_ozet_pools_bets_groups_years_and_trims_extreme_payouts():
    dates = ["2019-03-01", "2019-03-02", "2020-03-01"]
    plans = [[bet(2.0, 1), bet(0.0, 0)], [bet(30.0, 1)], [bet(0.0, 0), bet(4.0, 1)]]
    o = ey.ozet(dates, plans, {"r": 1.3})
    assert o["n"] == 5 and o["hit"] == pytest.approx(3 / 5)
    assert o["roi"] == pytest.approx((2 + 30 + 4) / 5 - 1)
    assert o["beklenen"] == pytest.approx(0.2)
    assert o["yil"]["2019"] == (3, pytest.approx((2 + 0 + 30) / 3 - 1))
    assert o["yil"]["2020"] == (2, pytest.approx(4 / 2 - 1))
    assert o["ilk25_cikar"] == pytest.approx(-1.0)                # 3 tutan bahis da 25'ten az: hepsi çıkınca geriye 0 kalır
    assert o["sinir10"] == pytest.approx((2 + 10 + 4) / 5 - 1)    # 30 katlık ödeme 10'a iner


def test_ozet_splits_by_takeout_regime():
    plans = [[bet(2.0, 1, "a"), bet(0.0, 0, "b")]]
    o = ey.ozet(["2019-01-01"], plans, {"a": 1.3, "b": 1.8})      # a: düşük kesinti (Σ < 1,40), b: yüksek
    assert o["dusuk"] == (1, pytest.approx(1.0)) and o["yuksek"] == (1, pytest.approx(-1.0))


def test_cita_matches_hand_computation():
    d = pd.DataFrame({"race_id": ["r1", "r1", "r2", "r2"], "ganyan": [2.0, 4.0, 1.5, 6.0],
                      "win": [1, 0, 0, 1], "p": [0.6, 0.4, 0.2, 0.8]})
    (_, h_r, r_r), (_, h_f, r_f), (_, h_m, r_m) = ks.cita(d)
    assert (h_r, r_r) == (pytest.approx(0.5), pytest.approx(2.0 - 1))        # (2 + 0 + 0 + 6) / 4
    assert (h_f, r_f) == (pytest.approx(0.5), pytest.approx(0.0))            # favoriler 2,0 (kazandı) ve 1,5 (kaybetti)
    assert (h_m, r_m) == (pytest.approx(1.0), pytest.approx((2 + 6) / 2 - 1))  # modelin tercihi 2,0 ve 6,0, ikisi de kazandı
