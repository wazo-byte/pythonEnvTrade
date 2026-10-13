import pytest
from trading_system.broker import OrderRequest, ReviewOnlyPaperBroker


def test_paper_broker_reviews_without_external_submission():
    review = ReviewOnlyPaperBroker().submit(OrderRequest("AAPL", "BUY", 1, 100, "USD"))
    assert review.status == "PAPER_REVIEW"
    assert "No external" in review.reason


def test_paper_broker_rejects_live_environment():
    with pytest.raises(ValueError, match="Only PAPER"):
        ReviewOnlyPaperBroker().submit(OrderRequest("AAPL", "BUY", 1, 100, "USD", "LIVE"))
