"""Model training and race-normalized probability prediction (v1 HistGradientBoosting)."""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from ganyan.features import get_feature_cols


def make_estimator():
    """Return the fixed v1 HistGradientBoostingClassifier (K7)."""
    return HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.04,
        max_leaf_nodes=31,
        min_samples_leaf=60,
        l2_regularization=1.0,
        random_state=0,
    )


def fit_predict_df(train_df, test_df, feats):
    """Fit v1 model on train_df[feats] and return race-normalized win probabilities on test_df."""
    m = make_estimator()
    y_train = (train_df["finish"] == 1).astype(int)
    X_train = train_df[feats].copy()
    X_test = test_df[feats].copy()
    # Replace all-NaN columns with 0.0 so HistGradientBoosting _bin_mapper handles tiny/partial fixtures
    all_nan = [c for c in feats if X_train[c].isna().all()]
    if all_nan:
        X_train[all_nan] = 0.0
        X_test[all_nan] = 0.0
    m.fit(X_train, y_train)
    p = m.predict_proba(X_test)[:, 1]
    s = pd.Series(p, index=test_df.index)
    denom = s.groupby(test_df["race_id"]).transform("sum").values
    return np.where(denom > 0, p / denom, 1.0 / test_df.groupby("race_id")["race_id"].transform("size").values)
