"""Small fictional repository used only for the runnable tutorial."""


def discount(price, rate):
    """Apply a fractional discount to a non-negative price."""
    if price < 0 or not 0 <= rate <= 1:
        raise ValueError("invalid price or discount")
    return round(price * (1 - rate), 2)
