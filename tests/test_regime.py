import pandas as pd
from trading_system.regime import classify_market_regime


def test_market_regime_labels_bullish_structure():
    data = pd.DataFrame({"Close": [110], "EMA20": [105], "EMA50": [100]})
    assert classify_market_regime(data) == "BULLISH"
