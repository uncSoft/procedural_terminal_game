"""What items do beyond their numbers. An item names its powers in items.toml (`powers = ["luck"]`), from this list:

    while you carry it
        luck         +1 to every roll you make
        seeker       +1 when you search a room for secrets
        careful      +2 to pick a lock or disarm a trap
        unseen       +2 to dodge and to flee
        cook         resting heals 4 more
        goblin_bane  +2 damage against goblins (a weapon's)
        prophecy     a Fate token each time you go down the stairs, if there's room for it
        cursed       the stairs take 2 of your most HP each time you go down them carrying it
        valuable     30 more souls when your run ends, if you still have it
    when you pick it up
        mapper       the whole floor's map is yours
    a choice it gives you
        throw        in a fight: throw it for its damage (an agility roll; better against a weakness). It's gone after
        distract     in a fight, once per fight: the monster loses its next attack. You keep it
        reveal       out of a fight: use it up to light the room. Anything hidden shows, and any hidden room behind
                     these walls

Carrying means in your pack, or as your weapon or armor. Two of the same item count once. (The Lucky Rabbit's Foot's
extra Fate is older than this and lives in Player.max_fate.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .content import Content, ItemDef
    from .models import GameState

POWERS = {
    "luck": "+1 to every roll you make",
    "seeker": "+1 to search for secrets",
    "careful": "+2 to pick locks and disarm traps",
    "unseen": "+2 to dodge and to flee",
    "cook": "resting heals 4 more",
    "goblin_bane": "+2 damage against goblins",
    "prophecy": "a Fate token each time you go down the stairs",
    "cursed": "cursed: the stairs take 2 of your most HP each time",
    "valuable": "30 more souls when your run ends, if you still have it",
    "mapper": "maps the whole floor when you pick it up",
    "throw": "throw it in a fight (it's gone after)",
    "distract": "distracts a monster once a fight: it loses its next attack",
    "reveal": "light the room with it: anything hidden shows (it's gone after)",
}
SHORT = {  # a power in a few words, for an item's tile
    "luck": "+1 every roll", "seeker": "+1 searching", "careful": "+2 lockpicking", "unseen": "+2 dodge & flee",
    "cook": "rest heals +4", "goblin_bane": "goblin-bane", "prophecy": "Fate each floor", "cursed": "cursed",
    "valuable": "valuable", "mapper": "maps the floor", "throw": "throw it", "distract": "distracts",
    "reveal": "shows what's hidden",
}
PICKED_UP = {"bomb": "for walls and monsters", "small_key": "opens a chest"}  # counters, not things you carry
# Roll bonuses: power -> (bonus, the kinds of roll it helps, or None for every one of yours)
ROLLS = {"luck": (1, None), "seeker": (1, {"search"}), "careful": (2, {"disarm"}), "unseen": (2, {"dodge", "flee"})}
GOBLINS = {"goblin", "goblinoid"}  # monster tags a goblin-bane weapon bites


def carried(state: GameState, content: Content) -> list[ItemDef]:
    """Everything you have on you: weapon, armor and pack, each item once."""
    player = state.player
    keys = dict.fromkeys(k for k in [player.weapon, player.armor, *player.inventory] if k)
    return [content.item(k) for k in keys]


def holders(state: GameState, content: Content, power: str) -> list[ItemDef]:
    return [item for item in carried(state, content) if power in item.powers]


def has(state: GameState, content: Content, power: str) -> bool:
    return bool(holders(state, content, power))


def roll_bonuses(state: GameState, content: Content, kind: str) -> list[tuple[str, int]]:
    """What carried items add to one of your rolls ("attack", "dodge", "flee", "search", "disarm", "smash",
    "creative", "throw"), each under its item's name so the dice show where it came from."""
    bonuses = []
    for item in carried(state, content):
        for power in item.powers:
            value, kinds = ROLLS.get(power, (0, set()))
            if value and (kinds is None or kind in kinds):
                bonuses.append((item.name, value))
    return bonuses


def describe(item: ItemDef) -> list[str]:
    """An item's powers, in words, for its card."""
    return [POWERS[p] + (f" ({item.damage})" if p == "throw" and item.damage else "") for p in item.powers]
