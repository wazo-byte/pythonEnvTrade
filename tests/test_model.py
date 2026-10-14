import pandas as pd
from trading_system.model import RidgeReturnModel


def test_ridge_model_learns_simple_linear_relationship():
    features = pd.DataFrame({"x": [0, 1, 2, 3], "y": [0, 1, 4, 9]})
    labels = pd.Series([1, 3, 5, 7])
    model = RidgeReturnModel(alpha=0).fit(features, labels)
    assert abs(model.predict(pd.DataFrame({"x": [4], "y": [16]})).iloc[0] - 9) < 1e-9
