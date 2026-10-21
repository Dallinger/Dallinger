"""Tests for the bargaining demo, as an example of testing a real-time game.

A game type's methods are plain functions of the game's state, so a test
builds a state, calls a method, and checks the result. No browser, server or
database is needed. The tests cover what a study depends on: the rules, what
each player can see, the pay, and that a round always ends.
"""

import json
from pathlib import Path
from unittest import mock

import jinja2
import pytest
from dlgr.demos.bargaining import experiment as experiment_module
from dlgr.demos.bargaining.experiment import (
    CHAT_CHANNEL,
    COSTS,
    JOIN_SECONDS,
    VALUES,
    Bargain,
    Bargaining,
)

from dallinger.realtime import Reject
from dallinger.realtime.game import queued_effects

SELLER, BUYER = "1", "2"


def bargain_game(rounds=1):
    """The game type, with these settings."""
    settings = {"bargaining_seconds": 60, "rounds": rounds}
    with mock.patch("dlgr.demos.bargaining.experiment.get_config") as get_config:
        get_config.return_value.get.side_effect = settings.__getitem__
        return Bargain()


@pytest.fixture
def game():
    return bargain_game()


@pytest.fixture
def new_round(game):
    """A round that has just started, before either page has opened. The
    seller's cost is 30 and the buyer's value 80, fixed here so the tests
    know them."""
    state = game.initial_state([SELLER, BUYER])
    state["roles"] = {SELLER: "seller", BUYER: "buyer"}
    state["values"] = {SELLER: 30, BUYER: 80}
    return state


@pytest.fixture
def state(game, new_round):
    """The same round with both players here, so its 60-second clock started
    at 0."""
    game.on_join(new_round, SELLER, 0)
    game.on_join(new_round, BUYER, 0)
    return new_round


def collecting_effects(call):
    """Make a call as Dallinger does, and return the effects it queued."""
    effects = []
    token = queued_effects.set(effects)
    try:
        call()
    finally:
        queued_effects.reset(token)
    return effects


def send(game, state, player_id, message, now=1.0):
    """Apply a player's message, and return the effects it queued."""
    return collecting_effects(lambda: game.apply(state, player_id, message, now, None))


def rejection(game, state, player_id, message):
    """The reason the game refuses a message. Also checks that the refused
    message changed nothing."""
    before = repr(state)
    with pytest.raises(Reject) as raised:
        send(game, state, player_id, message)
    assert repr(state) == before
    return str(raised.value)


# Starting a round


def test_roles_are_random_and_values_come_from_each_roles_range(game):
    # Random draws are checked over many rounds
    roles = set()
    for _ in range(200):
        state = game.initial_state([SELLER, BUYER])
        roles.add(state["roles"][SELLER])
        for player_id, role in state["roles"].items():
            low, high = COSTS if role == "seller" else VALUES
            assert low <= state["values"][player_id] <= high

    assert roles == {"seller", "buyer"}


def test_the_clock_starts_once_both_players_are_here(game, new_round):
    game.on_join(new_round, SELLER, 2.0)
    assert game.view(new_round, SELLER)["deadline"] is None

    # A bot has no page, so it arrives with its first offer
    send(game, new_round, BUYER, {"offer": 40}, now=5.0)

    assert game.view(new_round, SELLER)["deadline"] == 65.0


def test_a_player_who_never_arrives_cannot_hold_up_the_round(game, new_round):
    game.on_join(new_round, SELLER, 2.0)

    game.tick(new_round, JOIN_SECONDS)

    assert game.view(new_round, SELLER)["deadline"] == JOIN_SECONDS + 60


# The rules


@pytest.mark.parametrize("price", [-1, 101, 50.5, "50", None])
def test_a_price_is_whole_cents_from_0_to_100(game, state, price):
    reason = rejection(game, state, BUYER, {"offer": price})

    assert reason == "a price is a whole number of cents from 0 to 100"


@pytest.mark.parametrize(
    "player_id, breaks_even, loses", [(SELLER, 30, 29), (BUYER, 80, 81)]
)
def test_a_player_can_offer_down_to_breaking_even_but_not_at_a_loss(
    game, state, player_id, breaks_even, loses
):
    send(game, state, player_id, {"offer": breaks_even})
    assert game.view(state, player_id)["my_offer"] == breaks_even

    reason = rejection(game, state, player_id, {"offer": loses})
    assert reason == "that price would lose you money"


def test_a_player_can_only_accept_the_other_players_current_offer(game, state):
    assert rejection(game, state, BUYER, {"accept": 60}) == "there's no offer to accept"

    send(game, state, SELLER, {"offer": 60})
    send(game, state, SELLER, {"offer": 70})

    # The buyer clicked Accept before their page showed the new offer
    assert rejection(game, state, BUYER, {"accept": 60}) == "that offer has changed"


def test_a_player_sees_the_other_players_value_only_once_the_round_is_over(game, state):
    send(game, state, SELLER, {"offer": 60})
    assert game.view(state, BUYER)["their_value"] is None

    send(game, state, BUYER, {"accept": 60})

    assert game.view(state, BUYER)["their_value"] == 30


# How a round ends


def test_a_deal_ends_the_round_and_pays_each_player_their_gain(game, state):
    send(game, state, BUYER, {"offer": 55})
    send(game, state, SELLER, {"accept": 55})

    assert game.is_over(state)
    assert game.outcome(state, "finished") == {
        "roles": {SELLER: "seller", BUYER: "buyer"},
        "values": {SELLER: 30, BUYER: 80},
        "deal": 55,
        "earnings": {SELLER: 25, BUYER: 25},
    }


def test_time_running_out_ends_the_round_with_nothing_paid(game, state):
    send(game, state, SELLER, {"offer": 60})

    game.tick(state, 59.9)
    assert not game.is_over(state)
    game.tick(state, 60)

    assert game.is_over(state)
    assert game.outcome(state, "finished")["earnings"] == {SELLER: 0, BUYER: 0}


def test_two_bots_with_no_profitable_price_stop_offering(game, state):
    # Bots in a game without ticks answer each other until neither has
    # anything to send, so bots that never stopped would stall the round
    state["values"] = {SELLER: 50, BUYER: 52}
    for _ in range(100):
        messages = {p: game.bot(game.view(state, p), p, 0) for p in (SELLER, BUYER)}
        if not any(messages.values()):
            break
        for player_id, message in messages.items():
            if message:
                send(game, state, player_id, message)
    else:
        raise AssertionError("The bots never stopped")

    assert state["deal"] is None


# Rounds


@pytest.mark.parametrize("rounds, effects", [(1, []), (3, [("bargain_over", {})])])
def test_the_end_of_a_round_asks_for_the_next_one(state, rounds, effects):
    game = bargain_game(rounds=rounds)
    send(game, state, BUYER, {"offer": 55})

    assert send(game, state, SELLER, {"accept": 55}) == effects

    state["deal"] = None
    assert collecting_effects(lambda: game.tick(state, 60)) == effects


@mock.patch("dlgr.demos.bargaining.experiment.create_realtime_session")
@mock.patch("dlgr.demos.bargaining.experiment.realtime_sessions_for")
def test_the_next_round_starts_until_every_round_is_played(sessions_for, create):
    game = bargain_game(rounds=3)
    ended = mock.Mock(members=[7, 8], bots=[8])

    # The round that just ended is one of these
    sessions_for.return_value = ["round 1", "round 2"]
    game.handle_effect("bargain_over", {}, ended)
    create.assert_called_once_with(Bargain, [7, 8], bots=[8])

    create.reset_mock()
    sessions_for.return_value = ["round 1", "round 2", "round 3"]
    game.handle_effect("bargain_over", {}, ended)
    create.assert_not_called()


# The experiment


@mock.patch("dlgr.demos.bargaining.experiment.create_realtime_session")
def test_a_pair_starts_bargaining_once_both_players_are_in(create):
    players = [
        mock.Mock(participant=mock.Mock(id=1, recruiter_id="hotair")),
        mock.Mock(participant=mock.Mock(id=2, recruiter_id="bots:Bot")),
    ]
    network = mock.Mock(full=False, **{"nodes.return_value": players})
    Bargaining.add_node_to_network(None, mock.Mock(), network)
    create.assert_not_called()

    network.full = True
    Bargaining.add_node_to_network(None, mock.Mock(), network)
    create.assert_called_once_with(Bargain, [1, 2], bots=[2])


@mock.patch("dlgr.demos.bargaining.experiment.realtime_sessions_for")
def test_the_bonus_is_the_earnings_of_every_round_that_ended(sessions_for):
    sessions_for.return_value = [
        mock.Mock(status="ended", outcome={"earnings": {"7": 25, "8": 30}}),
        mock.Mock(status="failed", outcome={"earnings": {"7": 40, "8": 0}}),
        mock.Mock(status="ended", outcome={"earnings": {"7": 12, "8": 3}}),
    ]

    assert Bargaining.bonus(None, mock.Mock(id=7)) == 0.37


@pytest.fixture
def chat_db():
    """The database as ``receive_message`` sees it: one session, 11, between
    participants 7 and 8."""
    session = mock.Mock(id=11, members=[7, 8], bots=[])
    with mock.patch("dlgr.demos.bargaining.experiment.db") as db:
        db.session.get.side_effect = lambda model, id: session if id == 11 else None
        yield db


def receive_chat(participant_id, text):
    """Pass the experiment a chat message from a participant, as Dallinger
    does, and return the experiment."""
    experiment = Bargaining.__new__(Bargaining)
    experiment.publish_to_participants = mock.Mock()
    message = {"participant_id": participant_id, "session": 11, "text": text}
    experiment.receive_message(
        json.dumps(message),
        channel_name=CHAT_CHANNEL,
        participant=mock.Mock(
            id=participant_id, **{"nodes.return_value": [mock.sentinel.node]}
        ),
    )
    return experiment


@mock.patch("dlgr.demos.bargaining.experiment.Info")
def test_a_chat_message_is_saved_then_sent_to_both_players(info, chat_db):
    experiment = receive_chat(7, "  Meet me at 50?  ")

    info.assert_called_once_with(
        origin=mock.sentinel.node, contents="Meet me at 50?", details={"session": 11}
    )
    # Sent only once the Info is saved
    experiment.publish_to_participants.assert_not_called()
    (after_commit,), _ = chat_db.run_after_commit.call_args
    after_commit()
    experiment.publish_to_participants.assert_called_once_with(
        {"session": 11, "from": 7, "text": "Meet me at 50?"}, [7, 8]
    )


@mock.patch("dlgr.demos.bargaining.experiment.Info")
def test_chat_from_outside_the_pair_is_dropped(info, chat_db):
    receive_chat(9, "hello")

    info.assert_not_called()
    chat_db.run_after_commit.assert_not_called()


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
    defaults = {"bargaining_seconds": 60, "rounds": 1, "chat": False}
    experiment = mock.Mock(**{**defaults, **settings})
    page = env.get_template("instructions/instruct-ready.html")
    return " ".join(page.render(experiment=experiment).split())


def test_the_instructions_describe_the_settings():
    assert "within 45 seconds" in instructions(bargaining_seconds=45)
    assert "rounds" not in instructions()
    assert "You will play 3 rounds" in instructions(rounds=3)
    assert "chat" not in instructions()
    assert "chat with the other player" in instructions(chat=True)
