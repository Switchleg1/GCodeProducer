"""Normalize legacy stored strategies without silently changing their path direction."""
from .cam_constants import STRATEGY_ALIASES


def cutting_strategy(kind, strategy):
    return STRATEGY_ALIASES.get(kind, {}).get(strategy, strategy)
