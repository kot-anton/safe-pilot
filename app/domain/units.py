"""Unit conversion helpers. All domain math is done in Decimal, in pounds/inches/gallons."""
from decimal import Decimal

LB_PER_KG = Decimal("2.2046226218")


def kg_to_lb(value: Decimal) -> Decimal:
    return value * LB_PER_KG


def lb_to_kg(value: Decimal) -> Decimal:
    return value / LB_PER_KG


def gal_to_lb(gallons: Decimal, density_lb_per_gal: Decimal) -> Decimal:
    return gallons * density_lb_per_gal


def lb_to_gal(pounds: Decimal, density_lb_per_gal: Decimal) -> Decimal:
    if density_lb_per_gal == 0:
        raise ValueError("fuel density must be > 0")
    return pounds / density_lb_per_gal


def to_decimal(value) -> Decimal:
    """Safely coerce input (str/float/int/Decimal) to Decimal without binary float artifacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def compact_decimal(
    value: Decimal | str, *, decimal_places: int | None = None
) -> str:
    """Render a decimal without scientific notation or insignificant trailing zeros.

    ``decimal_places`` bounds display precision while still removing a resulting ``.0``.
    """
    decimal = to_decimal(value)
    if decimal_places is not None:
        decimal = decimal.quantize(Decimal("1").scaleb(-decimal_places))
    text = format(decimal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text
