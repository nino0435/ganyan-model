"""Deterministic greedy coupon allocator for Altılı Ganyan (§3.4)."""
import math


def _prod(vals):
    res = 1
    for v in vals:
        res *= v
    return res


def allocate_coupon_a(legs, budget_tl, unit_tl=1.25):
    """Objective A — maximize hit probability Π_j P_j under cost = unit_tl * Π k_j <= budget_tl.

    legs: list of legs (typically 6), each leg is a list of (prog_no, p, agf_share) tuples.
    Returns dict with keys: 'selected' (list of list of prog_no), 'k' (list of int),
    'cost' (float), 'hit_prob' (float).
    """
    n_legs = len(legs)
    if n_legs == 0 or budget_tl < unit_tl - 1e-12 or any(len(leg) == 0 for leg in legs):
        return {
            "selected": [[] for _ in legs],
            "k": [0 for _ in legs],
            "cost": 0.0,
            "hit_prob": 0.0,
        }

    # Sort each leg by descending p, tie-break by ascending prog_no for determinism
    sorted_legs = [
        sorted(leg, key=lambda x: (-float(x[1]), int(x[0]))) for leg in legs
    ]

    k = [1] * n_legs
    P = [float(sorted_legs[j][0][1]) for j in range(n_legs)]

    while True:
        cur_combos = _prod(k)
        best_j = None
        best_ratio = -1.0

        for j in range(n_legs):
            kj = k[j]
            if kj >= len(sorted_legs[j]):
                continue
            new_combos = (cur_combos // kj) * (kj + 1)
            new_cost = unit_tl * new_combos
            if new_cost > budget_tl + 1e-9:
                continue
            p_next = float(sorted_legs[j][kj][1])
            if p_next <= 0.0:
                continue
            pj = max(P[j], 1e-15)
            g_j = math.log(pj + p_next) - math.log(pj)
            c_j = math.log((kj + 1.0) / kj)
            ratio = g_j / c_j
            if ratio > best_ratio + 1e-15:
                best_ratio = ratio
                best_j = j

        if best_j is None:
            break

        P[best_j] += float(sorted_legs[best_j][k[best_j]][1])
        k[best_j] += 1

    selected = [[int(sorted_legs[j][i][0]) for i in range(k[j])] for j in range(n_legs)]
    cost = float(unit_tl * _prod(k))
    hit_prob = 1.0
    for pj in P:
        hit_prob *= min(max(pj, 0.0), 1.0)

    return {
        "selected": selected,
        "k": k,
        "cost": cost,
        "hit_prob": hit_prob,
    }


def allocate_coupon_b(legs, budget_tl, unit_tl=1.25, a=8.0, b=-0.85, stop_if_net_drops=False):
    """Objective B — maximize expected return E = e^a Π_j V_j, where V_j = Σ_{selected} p_i * pay_i^b (§3.4).

    Horses within each leg are sorted by v_i = p_i * (agf_share_i ^ b) descending.
    If stop_if_net_drops is True, stops early when adding the best candidate reduces (E - cost).
    """
    n_legs = len(legs)
    if n_legs == 0 or budget_tl < unit_tl - 1e-12 or any(len(leg) == 0 for leg in legs):
        return {
            "selected": [[] for _ in legs],
            "k": [0 for _ in legs],
            "cost": 0.0,
            "hit_prob": 0.0,
            "expected_return": 0.0,
        }

    # Compute v_i = p_i * max(pay_i, 1e-4)^b and sort descending by v_i, tie-break by prog_no
    enriched_legs = []
    for leg in legs:
        items = []
        for prog_no, p, pay in leg:
            p_f = max(float(p), 0.0)
            pay_f = max(float(pay), 1e-4)
            v_f = p_f * (pay_f ** float(b))
            items.append((int(prog_no), p_f, pay_f, v_f))
        items.sort(key=lambda x: (-x[3], x[0]))
        enriched_legs.append(items)

    k = [1] * n_legs
    V = [enriched_legs[j][0][3] for j in range(n_legs)]
    P = [enriched_legs[j][0][1] for j in range(n_legs)]
    exp_a = math.exp(float(a))

    def calc_E(v_list):
        prod_v = 1.0
        for vj in v_list:
            prod_v *= max(vj, 0.0)
        return exp_a * prod_v

    while True:
        cur_combos = _prod(k)
        cur_cost = unit_tl * cur_combos
        cur_E = calc_E(V)

        best_j = None
        best_ratio = -1.0
        best_new_cost = cur_cost
        best_new_E = cur_E

        for j in range(n_legs):
            kj = k[j]
            if kj >= len(enriched_legs[j]):
                continue
            new_combos = (cur_combos // kj) * (kj + 1)
            new_cost = unit_tl * new_combos
            if new_cost > budget_tl + 1e-9:
                continue
            v_next = enriched_legs[j][kj][3]
            if v_next <= 0.0:
                continue
            vj = max(V[j], 1e-15)
            g_j = math.log(vj + v_next) - math.log(vj)
            c_j = math.log((kj + 1.0) / kj)
            ratio = g_j / c_j
            if ratio > best_ratio + 1e-15:
                best_ratio = ratio
                best_j = j
                best_new_cost = new_cost
                best_new_E = cur_E / vj * (vj + v_next)

        if best_j is None:
            break

        if stop_if_net_drops and (best_new_E - best_new_cost) < (cur_E - cur_cost):
            break

        V[best_j] += enriched_legs[best_j][k[best_j]][3]
        P[best_j] += enriched_legs[best_j][k[best_j]][1]
        k[best_j] += 1

    selected = [[enriched_legs[j][i][0] for i in range(k[j])] for j in range(n_legs)]
    cost = float(unit_tl * _prod(k))
    hit_prob = 1.0
    for pj in P:
        hit_prob *= min(max(pj, 0.0), 1.0)

    return {
        "selected": selected,
        "k": k,
        "cost": cost,
        "hit_prob": hit_prob,
        "expected_return": float(calc_E(V)),
    }


def allocate_fixed_k(legs, budget_tl, unit_tl=1.25):
    """Baseline (i): largest uniform k^n_legs that fits in budget_tl (ordered by p descending)."""
    n_legs = len(legs)
    if n_legs == 0 or budget_tl < unit_tl - 1e-12 or any(len(leg) == 0 for leg in legs):
        return {
            "selected": [[] for _ in legs],
            "k": [0 for _ in legs],
            "cost": 0.0,
            "hit_prob": 0.0,
        }

    max_k = 1
    while unit_tl * ((max_k + 1) ** n_legs) <= budget_tl + 1e-9:
        max_k += 1

    sorted_legs = [
        sorted(leg, key=lambda x: (-float(x[1]), int(x[0]))) for leg in legs
    ]
    k = [min(max_k, len(sorted_legs[j])) for j in range(n_legs)]
    selected = [[int(sorted_legs[j][i][0]) for i in range(k[j])] for j in range(n_legs)]
    cost = float(unit_tl * _prod(k))
    hit_prob = 1.0
    for j in range(n_legs):
        pj = sum(float(sorted_legs[j][i][1]) for i in range(k[j]))
        hit_prob *= min(max(pj, 0.0), 1.0)

    return {
        "selected": selected,
        "k": k,
        "cost": cost,
        "hit_prob": hit_prob,
    }
