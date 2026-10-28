"""What the dice screen tells you before you roll (ptg/dice.py Roll.needed and Roll.chance, ui/dice.py): the least the
die must show and your odds are the rules' own, and the row of faces shows them."""

import itertools

import pytest

from ptg import dice
from ptg.dice import Roll
from ptg.ui.dice import FACE_INKS, face_kind, faces_strip


class Loaded:
    """Dice that show what they're told to, in turn."""

    def __init__(self, *faces: int) -> None:
        self.faces = list(faces)

    def randint(self, low: int, high: int) -> int:
        return self.faces.pop(0)


@pytest.mark.parametrize("advantage", [-1, 0, 1])
@pytest.mark.parametrize("bonus", [-3, 0, 2, 7])
def test_the_odds_told_before_the_roll_are_the_rules_own(bonus, advantage):
    """Every face (every pair, with two dice) rolled through dice.check: the faces that succeed are Roll.needed and
    up, and the share of rolls that succeed is Roll.chance. A 1 always fails, a 20 always succeeds (unless it can't be
    done)."""
    bonuses = [("might", bonus)]
    for dc in range(1, 32):
        for impossible in (False, True):
            def check(*faces):
                return dice.check(Loaded(*faces), "might", bonuses, dc, advantage=advantage, impossible=impossible)

            roll = check(10, 10)
            one = [face for face in range(1, 21) if dice.check(Loaded(face), "might", bonuses, dc,
                                                               impossible=impossible).success]
            assert one == list(range(roll.needed, 21)), (dc, bonus, impossible)
            rolls = list(itertools.product(range(1, 21), repeat=1 if advantage == 0 else 2))
            made = sum(check(*faces).success for faces in rolls)
            assert roll.chance == pytest.approx(made / len(rolls)), (dc, bonus, advantage, impossible)


def test_a_1_and_a_20_set_the_bounds():
    assert Roll("might", "player", [5], 5, [("might", 9)], dc=3).needed == 2  # (a 1 still fails)
    assert Roll("might", "player", [5], 5, dc=40).needed == 20  # (only a 20 will do)
    assert Roll("might", "player", [5], 5, dc=12, impossible=True).needed == 21
    assert Roll("might", "player", [5], 5, dc=12, impossible=True).chance == 0


def test_each_face_in_the_row_is_coloured_by_how_it_would_go():
    roll = Roll("attack", "player", [14], 14, [("might", 2), ("level", 1)], dc=11, success=True)  # 8 or better
    assert [face_kind(roll, face) for face in range(1, 21)] == ["fumble", *["bad"] * 6, *["good"] * 12, "crit"]
    impossible = Roll("lift", "player", [20], 20, dc=11, impossible=True)
    assert {face_kind(impossible, face) for face in range(1, 21)} == {"bad"}

    strip = faces_strip(roll, 3)
    faces, marks = strip.plain.split("\n")
    assert len(faces) == len(marks) == 20 * 3 + 19 and not marks.strip()
    assert faces.split() == [str(face) for face in range(1, 21)]
    for face, kind in ((1, "fumble"), (7, "bad"), (8, "good"), (20, "crit")):
        ink, dark = FACE_INKS[kind]
        assert styles_at(strip, cell(face, 3)) == f"{ink} on {dark}", face


def test_the_row_lights_the_tumbling_faces_and_marks_where_the_dice_land():
    roll = Roll("search", "player", [7, 16], 16, dc=12, success=True, advantage=1)
    tumbling = faces_strip(roll, 3, lit=(3, 15))
    assert {face for face in range(1, 21) if "bold" in styles_at(tumbling, cell(face, 3))} == {3, 15}
    assert not tumbling.plain.split("\n")[1].strip()

    landed = faces_strip(roll, 3, landed=(16, 7))  # (the one kept first)
    faces, marks = landed.plain.split("\n")
    assert marks.strip().split() == ["△", "▲"]
    assert "▲" in marks[cell(16, 3):cell(16, 3) + 3] and "△" in marks[cell(7, 3):cell(7, 3) + 3]
    assert "bold" in styles_at(landed, cell(16, 3)) and "bold" not in styles_at(landed, cell(7, 3))


def cell(face: int, width: int) -> int:
    """Where `face` starts in the row of faces, `width` columns each and a space between."""
    return (face - 1) * (width + 1)


def styles_at(text, offset: int) -> str:
    return " ".join(str(span.style) for span in text.spans if span.start <= offset < span.end)
