"""Command handlers for the voice AI command platform.

Each handler is an async callable ``(args: dict, ctx) -> DispatchResult`` that
reuses existing ``bot.db`` methods.
"""

from .dkp import award_dkp, deduct_dkp
from .guild_bank import bank_deposit, bank_withdraw

__all__ = ["award_dkp", "deduct_dkp", "bank_deposit", "bank_withdraw"]
