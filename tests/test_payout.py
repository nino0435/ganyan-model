"""Tests for ganyan.payout (§3.3)."""
import numpy as np
import pandas as pd
import pytest
from ganyan.payout import PayoutModel


def test_payout_model_recovers_synthetic_parameters():
    rng = np.random.default_rng(123)
    true_a = {"Ankara": 7.5, "İstanbul": 8.2, "İzmir": 7.8}
    true_b = -0.85

    rows = []
    for city, a_val in true_a.items():
        for _ in range(150):
            # 6 winners with AGF shares around 0.05..0.40
            shares = rng.uniform(0.05, 0.40, size=6)
            x = float(np.sum(np.log(shares)))
            noise = rng.normal(0.0, 0.05)
            y = a_val + true_b * x + noise
            rows.append({"city": city, "x": x, "y": y, "payout": float(np.exp(y))})

    df = pd.DataFrame(rows)
    model = PayoutModel().fit(df)

    assert model.b < 0
    assert abs(model.b - true_b) / abs(true_b) <= 0.05

    for city, a_val in true_a.items():
        est_a = model.a_by_city[city]
        assert abs(est_a - a_val) / abs(a_val) <= 0.05

    # Check predict_payout matches exp(a + b * sum(log(shares)))
    sample_shares = [0.2, 0.2, 0.2, 0.2, 0.2, 0.2]
    expected = np.exp(model.a_by_city["Ankara"] + model.b * sum(np.log(sample_shares)))
    assert model.predict_payout("Ankara", sample_shares) == pytest.approx(expected)
