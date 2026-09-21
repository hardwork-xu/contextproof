from pricing import discount


def total_after_discount(prices, rate):
    return sum(discount(price, rate) for price in prices)
