"""Quick travel (rules.journey): back to a room you've been in, from the map, past nothing hostile, now and then
stopped by something that's wandered in on the way, but not so often a floor can be farmed."""

from conftest import put_monster
from ptg.rules import TRAVEL_MEETINGS, available_actions, journey, perform
from ptg.world import generate


def walked(seed=5, content=None, steps=4):
    """A run some rooms in, everything on the floor calm, and the rooms walked through in order."""
    state = generate(seed)
    for room in state.rooms:
        room.monster = None
    path = [state.room_id]
    for _ in range(steps):
        ways = [a.id for a in available_actions(state, content) if a.id.startswith("go:")]
        fresh = [w for w in ways if not state.rooms[state.room.exits[w[3:]].to].visited]
        if not fresh:
            break
        perform(state, content, fresh[0])
        path.append(state.room_id)
    return state, path


def test_quick_travel_goes_back_through_rooms_youve_been_and_tells_it_in_a_line(content):
    state, path = walked(content=content)
    assert len(path) >= 3
    start = path[0]
    steps = journey(state, start)
    assert steps and steps[-1][1] == start and len(steps) <= len(path) - 1  # (the shortest way)
    state.wandered[str(state.floor)] = TRAVEL_MEETINGS  # (nothing will stop it this time)
    turn = state.turn
    events = perform(state, content, f"travel:{start}")
    assert state.room_id == start and events[0].kind == "travel" and events[0].data["quiet"]
    assert "make your way back" in events[0].text and state.turn == turn + 1


def test_no_travel_to_somewhere_new_past_a_fight_or_from_one(content):
    state, path = walked(content=content)
    unseen = next((r.id for r in state.rooms if not r.visited), None)
    if unseen is not None:
        assert journey(state, unseen) is None
    assert journey(state, state.room_id) is None
    middle = state.rooms[path[1]]
    put_monster(state, content)  # (a fight where you stand: no setting off)
    assert journey(state, path[0]) is None
    state.room.monster = None
    saved = state.room_id
    state.room_id = middle.id
    put_monster(state, content)  # (something hostile on the only way back)
    state.room_id = saved
    assert journey(state, path[0]) is None or all(to != middle.id for _, to in journey(state, path[0]))
    assert perform(state, content, f"travel:{state.room_id}")[0].kind == "info"  # (costs nothing, says why not)


def test_something_wandering_stops_a_trip_now_and_then_but_only_so_often_a_floor(content):
    stopped = 0
    for seed in range(60):
        state, path = walked(seed, content)
        if len(path) < 3:
            continue
        trips = 0
        while trips < 12:
            target = path[0] if state.room_id != path[0] else path[-1]
            if journey(state, target) is None:
                break
            events = perform(state, content, f"travel:{target}")
            trips += 1
            if events[0].kind == "ambush":
                stopped += 1
                assert state.room.monster and state.room.monster.hostile and state.room_id not in (target,)
                state.room.monster = None  # (beaten, say)
        assert state.wandered.get(str(state.floor), 0) <= TRAVEL_MEETINGS
    assert stopped > 0
