"""Tests for ganyan.allocator (§3.4)."""
import pytest
from ganyan.allocator import allocate_coupon_a, allocate_coupon_b, allocate_fixed_k


def _sample_6_legs():
    return [
        [(1, 0.45, 0.40), (2, 0.25, 0.25), (3, 0.15, 0.15), (4, 0.10, 0.12), (5, 0.05, 0.08)],
        [(1, 0.30, 0.35), (2, 0.28, 0.25), (3, 0.20, 0.20), (4, 0.12, 0.10), (5, 0.10, 0.10)],
        [(1, 0.60, 0.55), (2, 0.20, 0.20), (3, 0.10, 0.15), (4, 0.06, 0.05), (5, 0.04, 0.05)],
        [(1, 0.25, 0.20), (2, 0.24, 0.25), (3, 0.22, 0.20), (4, 0.18, 0.20), (5, 0.11, 0.15)],
        [(1, 0.50, 0.48), (2, 0.22, 0.22), (3, 0.14, 0.15), (4, 0.08, 0.08), (5, 0.06, 0.07)],
        [(1, 0.35, 0.30), (2, 0.25, 0.28), (3, 0.18, 0.18), (4, 0.12, 0.14), (5, 0.10, 0.10)],
    ]


def test_budget_never_exceeded_and_monotonic_hit_prob():
    legs = _sample_6_legs()
    budgets = [1.0, 1.25, 10.0, 50.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0]
    prev_p = 0.0
    for b in budgets:
        res_a = allocate_coupon_a(legs, budget_tl=b, unit_tl=1.25)
        assert res_a["cost"] <= b + 1e-9
        assert res_a["hit_prob"] >= prev_p - 1e-12
        prev_p = res_a["hit_prob"]

        res_b = allocate_coupon_b(legs, budget_tl=b, unit_tl=1.25, a=8.0, b=-0.85)
        assert res_b["cost"] <= b + 1e-9

        res_fk = allocate_fixed_k(legs, budget_tl=b, unit_tl=1.25)
        assert res_fk["cost"] <= b + 1e-9


def test_single_certain_winner_stays_k1():
    legs = _sample_6_legs()
    # Replace leg 2 (index 2) so horse 1 has p=1.0 and others have p=0.0
    legs[2] = [(1, 1.0, 0.80), (2, 0.0, 0.10), (3, 0.0, 0.05), (4, 0.0, 0.05)]
    res = allocate_coupon_a(legs, budget_tl=1000.0, unit_tl=1.25)
    assert res["k"][2] == 1
    assert res["selected"][2] == [1]


def test_hand_calculated_2_legs_3_horses_budget_4_units():
    # 2 legs, 3 horses each, unit_tl = 1.0, budget = 4.0 units
    # Leg 0: (1, 0.70), (2, 0.20), (3, 0.10)
    # Leg 1: (1, 0.40), (2, 0.35), (3, 0.25)
    # Step 0: k=[1, 1], P=[0.70, 0.40], cost=1
    # Step 1:
    #   Leg 0 gain: log(0.90/0.70)/log(2) = 0.36257
    #   Leg 1 gain: log(0.75/0.40)/log(2) = 0.90689 -> pick Leg 1 -> k=[1, 2], P=[0.70, 0.75], cost=2
    # Step 2 (from k=[1, 2], cost=2, budget=4):
    #   Leg 0 (k0: 1->2, new_cost=4<=4): gain = log(0.90/0.70)/log(2/1) = 0.25131 / 0.69315 = 0.36257
    #   Leg 1 (k1: 2->3, new_cost=3<=4): gain = log(1.00/0.75)/log(3/2) = 0.28768 / 0.40547 = 0.70951
    #   -> pick Leg 1! k=[1, 3], P=[0.70, 1.00], cost=3, hit_prob = 0.70
    # Step 3 (from k=[1, 3], cost=3, budget=4):
    #   Leg 0 (k0: 1->2, new_cost=6 > 4) -> exceeds budget!
    #   Leg 1 (already k1=3, no more horses) -> stops at k=[1, 3], selected=[[1], [1, 2, 3]], cost=3.0, hit_prob=0.70
    legs = [
        [(1, 0.70, 0.70), (2, 0.20, 0.20), (3, 0.10, 0.10)],
        [(1, 0.40, 0.40), (2, 0.35, 0.35), (3, 0.25, 0.25)],
    ]
    res = allocate_coupon_a(legs, budget_tl=4.0, unit_tl=1.0)
    assert res["k"] == [1, 3]
    assert res["selected"] == [[1], [1, 2, 3]]
    assert res["cost"] == pytest.approx(3.0)
    assert res["hit_prob"] == pytest.approx(0.70)
