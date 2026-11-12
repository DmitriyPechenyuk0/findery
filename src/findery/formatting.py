"""Text helpers shared by the terminal commands and the bot."""

from decimal import Decimal


def format_amount(value: Decimal | int) -> str:
    """18500 -> "18 500"."""
    return f"{value:,.0f}".replace(",", " ")
