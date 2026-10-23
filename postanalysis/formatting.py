"""Indian number formatting: 1,23,45,678 grouping and lakh/crore short forms."""

import math


def group_indian(n: int) -> str:
    """12345678 -> '1,23,45,678' (last three digits, then pairs)."""
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join([head, *pairs, tail])
    return s


def inr(x, decimals: int = 0, symbol: bool = True) -> str:
    """Format an amount as Indian rupees, e.g. -₹1,51,792 or ₹2,948.50. Blank for missing values."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    value = round(float(x), decimals)
    whole = int(abs(value))
    text = group_indian(whole)
    if decimals:
        text += f"{abs(value) - whole:.{decimals}f}"[1:]
    sign = "-" if value < 0 else ""
    return f"{sign}{'₹' if symbol else ''}{text}"


def inr_short(x) -> str:
    """Compact lakh/crore form: ₹1.52 L, ₹1.18 Cr, ₹45,000."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 1e7:
        return f"{sign}₹{a / 1e7:.2f} Cr"
    if a >= 1e5:
        return f"{sign}₹{a / 1e5:.2f} L"
    return inr(x)
