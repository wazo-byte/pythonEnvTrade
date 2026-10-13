"""Broker boundary. This module cannot create, modify, or cancel external orders."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OrderRequest:
    ticker: str
    side: str
    quantity: int
    limit_price: float
    currency: str
    environment: str = "PAPER"


@dataclass(frozen=True)
class OrderReview:
    request: OrderRequest
    status: str
    reason: str


class Broker(Protocol):
    def submit(self, request: OrderRequest) -> OrderReview: ...


class ReviewOnlyPaperBroker:
    """Validates paper-order intent locally; it has no network or broker SDK dependency."""

    def submit(self, request: OrderRequest) -> OrderReview:
        if request.environment != "PAPER":
            raise ValueError("Only PAPER order reviews are allowed")
        if request.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if request.quantity < 1 or request.limit_price <= 0 or not request.ticker or not request.currency:
            raise ValueError("ticker, currency, positive quantity, and positive limit price are required")
        return OrderReview(request, "PAPER_REVIEW", "No external order was submitted")
