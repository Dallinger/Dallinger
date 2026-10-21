"""Tests for the coins demo, as an example of what to test in a real-time game.

A game type's methods are plain functions of its state, so most tests build a
state, call one method, and check the state or what it returned. They need no
runner, browser or database. The sections follow the methods of the game type,
then the experiment and its bot.
"""

from pathlib import Path
from unittest import mock

import jinja2
import pytest
from dlgr.demos.coins import experiment as experiment_module
from dlgr.demos.coins.experiment import (
    COIN_SECONDS,
    MAX_COINS,
    SAFE_SECONDS,
    SAVED_MOVEMENT,
    STARTS,
    Bot,
    CoinCollection,
    Coins,
)

from dallinger.realtime import Reject
from dallinger.realtime.game import queued_effects

ONE, TWO = "1", "2"


def coins_game(stealing=False, bouncing=False, bot_speed=1.0):
    """A game type with these settings. It reads them when it's made."""
    settings = {
        "stealing": stealing,
        "bouncing": bouncing,
        "bounce_distance": 0.5,
        "bot_speed": bot_speed,
        "bonus_per_coin": 0.02,
    }
    with mock.patch("dlgr.demos.coins.experiment.get_config") as get_config:
        get_config.return_value.get.side_effect = settings.__getitem__
        return Coins()


@pytest.fixture
def game():
    return coins_game()


@pytest.fixture
def state(game):
    """Two players in the middle of the arena, one above the other, and no
    coins."""
    state = game.initial_state([ONE, TWO])
    state["players"][ONE].update(x=10, y=6)
    state["players"][TWO].update(x=10, y=8)
    state["coins"] = []
    return state


def send(game, state, player_id, message, now=10.0):
    """Apply a message as a runner does, and return the effects it queued.

    ``queue_effect`` only works while a runner is collecting effects, so this
    sets up the collection.
    """
    effects = []
    token = queued_effects.set(effects)
    try:
        game.apply(state, player_id, message, now, None)
    finally:
        queued_effects.reset(token)
    return effects


def rejection(game, state, player_id, message, now=10.0):
    """The reason ``apply`` refuses a message, checking it left the state as
    it was."""
    before = repr(state)
    with pytest.raises(Reject) as raised:
        send(game, state, player_id, message, now)
    assert repr(state) == before
    return str(raised.value)


def position(state, player_id):
    player = state["players"][player_id]
    return player["x"], player["y"]


# initial_state


def test_players_are_numbered_and_placed_in_order_of_participant_id(game):
    state = game.initial_state(["10", "9", "2"])

    players = state["players"]
    assert [players[p]["number"] for p in ("2", "9", "10")] == [1, 2, 3]
    assert [position(state, p) for p in ("2", "9", "10")] == [
        tuple(start) for start in STARTS[:3]
    ]


@pytest.mark.parametrize("count", [1, 5])
def test_a_game_is_for_two_to_four_players(game, count):
    with pytest.raises(ValueError):
        game.initial_state([str(n) for n in range(1, count + 1)])


# apply: what a message does, and which messages it refuses


def test_a_move_covers_five_units_a_second_in_its_direction(game, state):
    send(game, state, ONE, {"dx": 1, "dy": 0, "seconds": 0.2})
    send(game, state, TWO, {"dx": 0, "dy": -1, "seconds": 0.4})

    assert position(state, ONE) == (11, 6)
    assert position(state, TWO) == (10, 6)


def test_a_page_cannot_move_its_player_faster_than_the_clock_allows(game, state):
    moves = [{"dx": 1, "dy": 0, "seconds": 0.15}] * 4
    for message in moves:
        send(game, state, ONE, message)

    # The fourth move gets only what was left of the saved movement time
    assert position(state, ONE) == (pytest.approx(10 + 5 * SAVED_MOVEMENT), 6)
    assert rejection(game, state, ONE, moves[0]) == (
        "moving faster than the game allows"
    )

    send(game, state, ONE, moves[0], now=10.1)
    assert position(state, ONE) == (pytest.approx(10 + 5 * (SAVED_MOVEMENT + 0.1)), 6)


@pytest.mark.parametrize(
    "message, reason",
    [
        ("left", "a move is {dx, dy, seconds}"),
        ({"dx": 2, "dy": 0, "seconds": 0.1}, "dx and dy are each -1, 0 or 1"),
        ({"dx": 0, "dy": 0, "seconds": 0.1}, "a move needs a direction"),
        ({"dx": 1, "dy": 0, "seconds": -0.1}, "seconds is a positive number"),
        ({"dx": 1, "dy": 0, "seconds": float("nan")}, "seconds is a positive number"),
        ({"dx": 1, "dy": 0, "seconds": 10**400}, "seconds is a positive number"),
    ],
)
def test_malformed_moves_are_refused(game, state, message, reason):
    assert rejection(game, state, ONE, message) == reason


def test_a_move_collects_the_coins_it_passes_near(game, state):
    state["coins"] = [
        {"id": 0, "x": 11, "y": 6.6},
        {"id": 1, "x": 11.5, "y": 6.8},
        {"id": 2, "x": 12.6, "y": 6},
    ]

    send(game, state, ONE, {"dx": 1, "dy": 0, "seconds": 0.4})

    assert [coin["id"] for coin in state["coins"]] == [1]
    assert state["players"][ONE]["coins"] == 2


def test_a_coin_goes_to_the_first_player_to_reach_it(game, state):
    state["players"][ONE].update(y=7)
    state["players"][TWO].update(y=7)
    state["coins"] = [{"id": 0, "x": 11, "y": 7}]

    send(game, state, TWO, {"dx": 1, "dy": 0, "seconds": 0.4})
    send(game, state, ONE, {"dx": 1, "dy": 0, "seconds": 0.4})

    assert [state["players"][p]["coins"] for p in (ONE, TWO)] == [0, 1]


# apply, with the settings that make players touch


def test_players_pass_through_each_other_with_both_rules_off(game, state):
    state["players"][TWO]["coins"] = 3

    assert send(game, state, ONE, {"dx": 0, "dy": 1, "seconds": 0.5}) == []

    assert position(state, ONE) == (10, 8.5)
    assert state["players"][TWO]["coins"] == 3


def test_running_into_a_player_steals_one_of_their_coins(state):
    game = coins_game(stealing=True)
    state["players"][TWO]["coins"] = 3

    effects = send(game, state, ONE, {"dx": 0, "dy": 1, "seconds": 0.5})

    assert effects == [("steal", {"by": ONE, "from": TWO, "at": [10, 7]})]
    assert [state["players"][p]["coins"] for p in (ONE, TWO)] == [1, 2]
    assert [state["players"][p]["stole"] for p in (ONE, TWO)] == [1, 0]
    assert [state["players"][p]["coins_lost"] for p in (ONE, TWO)] == [0, 1]


def test_a_robbed_player_is_safe_for_two_seconds(state):
    game = coins_game(stealing=True)
    state["players"][TWO]["coins"] = 3
    down, up = {"dx": 0, "dy": 1, "seconds": 0.2}, {"dx": 0, "dy": -1, "seconds": 0.2}

    send(game, state, ONE, down, now=10.0)
    send(game, state, ONE, up, now=10.2)
    send(game, state, ONE, down, now=10.0 + SAFE_SECONDS - 0.1)
    assert state["players"][TWO]["coins"] == 2

    send(game, state, ONE, up, now=12.1)
    send(game, state, ONE, down, now=12.3)
    assert state["players"][TWO]["coins"] == 1


def test_running_into_a_player_stops_you_and_knocks_them_away(state):
    game = coins_game(bouncing=True)

    effects = send(game, state, ONE, {"dx": 0, "dy": 1, "seconds": 0.5})

    assert effects == [("bounce", {"by": ONE, "bounced": TWO, "at": [10, 7]})]
    assert position(state, ONE) == (10, pytest.approx(7))
    # Touching distance, plus the bounce distance
    assert position(state, TWO) == (10, pytest.approx(8.5))
    assert [state["players"][p]["bounced"] for p in (ONE, TWO)] == [0, 1]
    assert [state["players"][p]["bounced_others"] for p in (ONE, TWO)] == [1, 0]


def test_players_heading_into_each_other_both_bounce_and_neither_steals(state):
    game = coins_game(stealing=True, bouncing=True)
    state["players"][TWO].update(heading=[0, -1], moved_at=9.95, coins=2)
    state["players"][ONE]["coins"] = 2

    effects = send(game, state, ONE, {"dx": 0, "dy": 1, "seconds": 0.5})

    assert effects == [
        ("bounce", {"by": ONE, "bounced": TWO, "at": [10, 7]}),
        ("bounce", {"by": TWO, "bounced": ONE, "at": [10, 7]}),
    ]
    assert position(state, ONE) == (10, pytest.approx(6.75))
    assert position(state, TWO) == (10, pytest.approx(8.25))
    assert [state["players"][p]["coins"] for p in (ONE, TWO)] == [2, 2]


def test_pressing_against_a_player_at_a_wall_bounces_them_once(state):
    game = coins_game(bouncing=True)
    state["players"][ONE].update(x=10, y=10)
    state["players"][TWO].update(x=10, y=12)

    effects = []
    for n in range(10):
        down = {"dx": 0, "dy": 1, "seconds": 0.03}
        effects += send(game, state, ONE, down, now=10.0 + 0.03 * n)

    assert len(effects) == 1


# tick


def test_a_coin_appears_every_two_seconds_until_there_are_six(game, state):
    game.tick(state, COIN_SECONDS - 0.05)
    assert state["coins"] == []

    game.tick(state, COIN_SECONDS)
    assert len(state["coins"]) == 1

    # A tick late enough for several coins catches up on all of them
    game.tick(state, 4 * COIN_SECONDS)
    assert len(state["coins"]) == 4

    game.tick(state, 20 * COIN_SECONDS)
    assert len(state["coins"]) == MAX_COINS


# view, save_message and outcome


def test_a_view_leaves_out_what_pages_do_not_need(game, state):
    view = game.view(state, TWO)

    assert view["me"] == TWO
    assert set(view["players"]) == {ONE, TWO}
    for hidden in ("moved_until", "heading", "moved_at", "eventful"):
        assert hidden not in view["players"][ONE]


def test_only_moves_that_collect_a_coin_or_touch_a_player_are_saved(state):
    game = coins_game(bouncing=True)
    state["coins"] = [{"id": 0, "x": 11, "y": 6}]
    right = {"dx": 1, "dy": 0, "seconds": 0.4}

    send(game, state, ONE, right)
    assert game.save_message(state, ONE, right, None) is True
    # A refused move leaves the state as the last accepted one left it
    refused = Reject("moving faster than the game allows")
    assert game.save_message(state, ONE, right, refused) is False

    send(game, state, ONE, right, now=10.4)
    assert game.save_message(state, ONE, right, None) is False


def test_the_outcome_is_each_players_results(game, state):
    state["players"][ONE].update(coins=3, stole=2, bounced=4)
    state["players"][TWO].update(coins=5, coins_lost=2, bounced_others=4)

    assert game.outcome(state, "max_duration") == {
        "coins": {ONE: 3, TWO: 5},
        "stole": {ONE: 2, TWO: 0},
        "coins_lost": {ONE: 0, TWO: 2},
        "bounced": {ONE: 4, TWO: 0},
        "bounced_others": {ONE: 0, TWO: 4},
    }


# handle_effect, which runs on a worker and can use the database


@mock.patch("dlgr.demos.coins.experiment.db")
@mock.patch("dlgr.demos.coins.experiment.Info")
@mock.patch("dlgr.demos.coins.experiment.Participant")
def test_each_effect_becomes_an_info_on_the_node_of_the_player_who_did_it(
    participant_model, info, db, game
):
    payload = {"by": "7", "from": "8", "at": [3, 4]}

    game.handle_effect("steal", payload, mock.Mock())

    participant_model.query.get.assert_called_once_with(7)
    node = participant_model.query.get.return_value.nodes.return_value[0]
    info.assert_called_once_with(origin=node, contents="steal", details=payload)
    db.session.add.assert_called_once_with(info.return_value)


# bot


def bot_move(game, state):
    message = game.bot(game.view(state, ONE), ONE, 1.0)
    return message and (message["dx"], message["dy"])


@pytest.mark.parametrize("bot_speed", [0.5, 1.0])
def test_a_bot_heads_for_a_coin_at_its_share_of_a_players_speed(state, bot_speed):
    game = coins_game(bot_speed=bot_speed)
    state["coins"] = [{"id": 0, "x": 15, "y": 6}]

    message = game.bot(game.view(state, ONE), ONE, 1.0)

    assert message == {"dx": 1, "dy": 0, "seconds": bot_speed / game.tick_rate}


def test_a_bot_skips_a_coin_another_player_will_reach_first(game, state):
    state["coins"] = [{"id": 0, "x": 10, "y": 9}, {"id": 1, "x": 2, "y": 2}]

    assert bot_move(game, state) == (-1, -1)


def test_a_bot_with_no_coin_to_go_for_waits_in_the_middle_of_its_part(game, state):
    # Everything above y = 7 is nearer to the bot, so it heads up to y = 3.5
    assert bot_move(game, state) == (0, -1)

    state["players"][ONE].update(y=3)
    state["players"][TWO].update(y=9)
    assert bot_move(game, state) is None


# The experiment


def network_of(*recruiter_ids, full=True):
    nodes = [
        mock.Mock(participant=mock.Mock(id=n, recruiter_id=r))
        for n, r in enumerate(recruiter_ids, start=1)
    ]
    return mock.Mock(full=full, **{"nodes.return_value": nodes})


@mock.patch("dlgr.demos.coins.experiment.create_realtime_session")
def test_a_full_group_starts_a_game_with_runner_played_bots(create):
    network = network_of("hotair", "bots:Bot", full=False)
    CoinCollection.add_node_to_network(None, mock.Mock(), network)
    create.assert_not_called()

    network.full = True
    CoinCollection.add_node_to_network(None, mock.Mock(), network)
    create.assert_called_once_with(Coins, [1, 2], bots=[2])


@mock.patch("dlgr.demos.coins.experiment.realtime_sessions_for")
def test_the_bonus_pays_for_each_coin_from_games_that_ended(sessions_for):
    sessions_for.return_value = [
        mock.Mock(status="ended", outcome={"coins": {"7": 4, "8": 9}}),
        mock.Mock(status="failed", outcome={"coins": {"7": 20, "8": 0}}),
        mock.Mock(status="ended", outcome={"coins": {"7": 3, "8": 1}}),
    ]
    experiment = mock.Mock(bonus_per_coin=0.03)

    assert CoinCollection.bonus(experiment, mock.Mock(id=7)) == 0.21


def instructions(**settings):
    """The instructions page's text, for an experiment with these settings."""
    folder = Path(experiment_module.__file__).parent / "templates"
    env = jinja2.Environment(
        loader=jinja2.ChoiceLoader(
            [
                jinja2.DictLoader({"layout.html": "{% block body %}{% endblock %}"}),
                jinja2.FileSystemLoader(folder),
            ]
        )
    )
    defaults = {
        "players_per_group": 2,
        "stealing": False,
        "bouncing": False,
        "bonus_per_coin": 0.02,
    }
    experiment = mock.Mock(**{**defaults, **settings})
    page = env.get_template("instructions/instruct-ready.html")
    return " ".join(page.render(experiment=experiment).split())


def test_the_instructions_follow_the_settings():
    assert "play with 1 other player," in instructions(players_per_group=2)
    assert "play with 3 other players," in instructions(players_per_group=4)
    assert "earns you 1 cent." in instructions(bonus_per_coin=0.01)
    assert "earns you 7 cents." in instructions(bonus_per_coin=0.07)
    assert "take one of their coins" not in instructions()
    assert "take one of their coins" in instructions(stealing=True)
    assert "knock them away" in instructions(bouncing=True)


@mock.patch("dlgr.demos.coins.experiment.requests.post")
def test_a_bot_joins_a_group(post):
    bot = Bot.__new__(Bot)
    bot.URL = "http://localhost:5000/ad?x=1"
    bot.participant_id = 7

    bot.participate()

    post.assert_called_once_with("http://localhost:5000/node/7")
