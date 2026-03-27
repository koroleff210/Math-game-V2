# app/services/upgrade_catalog.py
#
# Central upgrade catalog — Phase D2.
#
# Defines the four permanent upgrades available in the Blacksmith shop.
# This is the single source of truth for upgrade metadata:
#   - display info (label, description)
#   - max level
#   - cost per level
#   - placeholder effect info used by D3 snapshot logic (but NOT wired yet)
#
# DB tables are NOT used for these definitions.
# All game code must import from here rather than hard-coding upgrade types.

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class UpgradeDef:
    """Static definition for one upgradeable attribute.

    Attributes
    ----------
    upgrade_type : str
        Machine key stored in PlayerUpgrade.upgrade_type.
    label : str
        Human-readable display name shown in the shop.
    description : str
        Short in-UI description of what this upgrade does.
    max_level : int
        The player cannot purchase beyond this level.
    costs : List[int]
        costs[i] is the Diamonds cost to go from level i to level i+1.
        Length must equal max_level.
    effects : List[int | float]
        effects[i] is the effective value at level i (level 0 = baseline).
        Length must equal max_level + 1.
        NOT wired into gameplay yet (D3 will use this).
    """
    upgrade_type: str
    label: str
    description: str
    max_level: int
    costs: List[int]
    effects: List[int | float]
    effect_format: str = '{v}'
    effect_is_pct: bool = False

    def cost_for_next_level(self, current_level: int) -> int | None:
        """Return the Diamonds cost to purchase the next level.

        Returns None if already at max level.
        """
        if current_level >= self.max_level:
            return None
        return self.costs[current_level]

    def effect_at_level(self, level: int) -> int | float:
        """Return the effective value at the given level."""
        return self.effects[level]

    def format_effect(self, level: int) -> str:
        """Return a human-readable effect string for the given level."""
        v = self.effects[level]
        display = int(v * 100) if self.effect_is_pct else v
        return self.effect_format.format(v=display)


# ── Catalog ───────────────────────────────────────────────────────────────────
#
# Four upgrades for the first release.
#
# steal_token_cap
#   +1 to maximum steal tokens the player may hold.
#   Baseline (level 0) = 1.  Max level 2 = cap of 3 (conservative first-release cap).
#
# shield_bonus_pct
#   Percentage bonus applied to both manual and reactive shield durations.
#   Baseline (level 0) = 0 %.  Max level 3 = +20 %.
#   effect stored as a fraction (0.10 = +10 %).
#
# mine_bonus
#   Flat gold added to every mine action reward.
#   Baseline (level 0) = 0.  Max level 3 = +15 gold.
#
# treasure_bonus
#   Flat gold added to every treasure search reward.
#   Baseline (level 0) = 0.  Max level 3 = +15 gold.

UPGRADE_CATALOG: Dict[str, UpgradeDef] = {
    'steal_token_cap': UpgradeDef(
        upgrade_type='steal_token_cap',
        label='Steal Capacity',
        description='Increase the maximum steal tokens you can hold.',
        max_level=2,
        costs=[5, 10],              # level 0→1, 1→2
        effects=[1, 2, 3],          # effective cap at levels 0–2
        effect_format='Max {v} tokens',
    ),
    'shield_bonus_pct': UpgradeDef(
        upgrade_type='shield_bonus_pct',
        label='Shield Fortification',
        description='Extend both manual and reactive shield durations by a percentage.',
        max_level=3,
        costs=[5, 10, 20],
        effects=[0.0, 0.10, 0.15, 0.20],  # fraction bonus at levels 0–3
        effect_format='+{v}% duration',
        effect_is_pct=True,
    ),
    'mine_bonus': UpgradeDef(
        upgrade_type='mine_bonus',
        label='Mining Efficiency',
        description='Earn bonus gold on every mine action.',
        max_level=3,
        costs=[5, 10, 20],
        effects=[0, 5, 10, 15],     # bonus gold at levels 0–3
        effect_format='+{v} gold per mine',
    ),
    'treasure_bonus': UpgradeDef(
        upgrade_type='treasure_bonus',
        label='Treasure Hunter',
        description='Earn bonus gold on every treasure search.',
        max_level=3,
        costs=[5, 10, 20],
        effects=[0, 5, 10, 15],     # bonus gold at levels 0–3
        effect_format='+{v} gold per search',
    ),
}

# Ordered list used for consistent UI display (dict order is insertion-order in
# Python 3.7+, but an explicit list avoids any ambiguity).
UPGRADE_ORDER: List[str] = [
    'steal_token_cap',
    'shield_bonus_pct',
    'mine_bonus',
    'treasure_bonus',
]


def get_upgrade(upgrade_type: str) -> UpgradeDef:
    """Return the UpgradeDef for *upgrade_type*.

    Raises ValueError if the type is not in the catalog.
    """
    try:
        return UPGRADE_CATALOG[upgrade_type]
    except KeyError:
        raise ValueError(f'Unknown upgrade type: {upgrade_type!r}')
