"""What the player meant. The interpreter (LLM or keyword matcher) fills this in; the rules engine decides what happens."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Stat = Literal["might", "agility", "wits", "none"]
Difficulty = Literal["trivial", "easy", "medium", "hard", "absurd"]
Effect = Literal[
    "damage_small", "damage_medium", "damage_large", "stun", "pacify", "escape", "evade",
    "reveal_secret", "find_item", "find_gold", "heal_small",
    "hurt_self_small", "hurt_self_medium", "nothing",
]

EFFECT_HELP: dict[str, str] = {
    "damage_small": "hurt the monster a little",
    "damage_medium": "hurt the monster solidly",
    "damage_large": "hurt the monster badly (only for hard or absurd attempts)",
    "stun": "the monster is dazed and loses its next two attacks",
    "pacify": "the monster stops fighting (talking, bribing, bluffing, or distracting a beast with food)",
    "escape": "get out of the fight to the previous room",
    "evade": "duck, hide or dive aside so the monster's next attack misses (perfect against a heavy blow)",
    "reveal_secret": "uncover something hidden in this room, if anything is hidden",
    "find_item": "scrounge up a minor useful item (once per room)",
    "find_gold": "find a few coins (once per room)",
    "heal_small": "recover a few hit points (once per room)",
    "hurt_self_small": "the player gets a little hurt (failure only)",
    "hurt_self_medium": "the player gets hurt (failure only)",
    "nothing": "no mechanical effect",
}

DC: dict[str, int] = {"trivial": 0, "easy": 10, "medium": 13, "hard": 16, "absurd": 99}


class Intent(BaseModel):
    kind: Literal["action", "creative", "flavor", "question"]
    action_id: str = ""
    stat: Stat = "none"
    difficulty: Difficulty = "medium"
    success_effects: list[Effect] = Field(default_factory=list)
    failure_effects: list[Effect] = Field(default_factory=list)
    uses: list[str] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)
    summary: str = ""


def intent_schema() -> dict:
    """JSON schema for structured output. Every field required and no extras, so strict modes accept it."""
    effect = {"type": "string", "enum": list(EFFECT_HELP)}
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["action", "creative", "flavor", "question"]},
            "action_id": {"type": "string"},
            "stat": {"type": "string", "enum": ["might", "agility", "wits", "none"]},
            "difficulty": {"type": "string", "enum": list(DC)},
            "success_effects": {"type": "array", "items": effect},
            "failure_effects": {"type": "array", "items": effect},
            "uses": {"type": "array", "items": {"type": "string"}},
            "consumes": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": ["kind", "action_id", "stat", "difficulty", "success_effects", "failure_effects",
                     "uses", "consumes", "summary"],
        "additionalProperties": False,
    }
