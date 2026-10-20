from unittest import mock

import pytest
from dlgr.demos.bargaining.experiment import (
    COSTS,
    VALUES,
    Bargain,
    Bargaining,
    Bot,
)

from dallinger.realtime import Reject

SELLER, BUYER = "1", "2"


@pytest.fixture
def game():
    with mock.patch("dlgr.demos.bargaining.experiment.get_config") as get_config:
        get_config.return_value.get.return_value = 60
        yield Bargain()


@pytest.fixture
def state(game):
    """A bargain between a seller with a cost of 30 and a buyer with a value of
    80.
    """
    state = game.initial_state([SELLER, BUYER])
    state["roles"] = {SELLER: "seller", BUYER: "buyer"}
    state["values"] = {SELLER: 30, BUYER: 80}
    return state


def send(game, state, player_id, message, now=1.0):
    game.apply(state, player_id, message, now, None)


def rejection(game, state, player_id, message):
    before = repr(state)
    with pytest.raises(Reject) as raised:
        send(game, state, player_id, message)
    assert repr(state) == before
    return str(raised.value)


def play_bots(game, state):
    """Ask each bot for its message in turn, as Dallinger does in a game
    without ticks, until a round passes in which neither sends one.
    """
    for _ in range(100):
        sent = False
        for player_id in (SELLER, BUYER):
            if game.is_over(state):
                return
            message = game.bot(game.view(state, player_id), player_id, 0)
            if message is not None:
                send(game, state, player_id, message, now=0)
                sent = True
        if not sent:
            return
    raise AssertionError("The bots never stopped")


def test_roles_are_drawn_at_random_and_values_from_each_roles_range(game):
    roles = set()
    for _ in range(200):
        state = game.initial_state([SELLER, BUYER])
        assert sorted(state["roles"].values()) == ["buyer", "seller"]
        roles.add(state["roles"][SELLER])
        for player_id, role in state["roles"].items():
            low, high = COSTS if role == "seller" else VALUES
            assert low <= state["values"][player_id] <= high

    assert roles == {"seller", "buyer"}


def test_a_player_sees_the_other_players_value_only_once_the_game_is_over(game, state):
    send(game, state, SELLER, {"offer": 60})
    assert game.view(state, BUYER)["their_value"] is None
    assert game.view(state, BUYER)["value"] == 80

    send(game, state, BUYER, {"accept": 60})

    assert game.view(state, BUYER)["their_value"] == 30
    assert game.view(state, SELLER)["their_value"] == 80


def test_an_offer_replaces_the_players_last_one(game, state):
    send(game, state, SELLER, {"offer": 70}, now=2.0)
    send(game, state, SELLER, {"offer": 65}, now=5.5)

    view = game.view(state, BUYER)
    assert view["their_offer"] == 65
    assert view["my_offer"] is None
    assert view["offers"] == [
        {"by": "seller", "price": 70, "time": 2.0},
        {"by": "seller", "price": 65, "time": 5.5},
    ]


@pytest.mark.parametrize("price", [-1, 101, 50.5, "50", True, None])
def test_an_offer_must_be_whole_cents_in_range(game, state, price):
    reason = rejection(game, state, BUYER, {"offer": price})

    assert reason == "a price is a whole number of cents from 0 to 100"


@pytest.mark.parametrize("player_id, price", [(SELLER, 29), (BUYER, 81)])
def test_a_player_cannot_offer_a_price_that_loses_money(game, state, player_id, price):
    reason = rejection(game, state, player_id, {"offer": price})

    assert reason == "that price would lose you money"


@pytest.mark.parametrize("player_id, price", [(SELLER, 100), (BUYER, 0)])
def test_prices_run_from_0_to_100_cents(game, state, player_id, price):
    send(game, state, player_id, {"offer": price})

    assert game.view(state, player_id)["my_offer"] == price


@pytest.mark.parametrize("player_id, price", [(SELLER, 30), (BUYER, 80)])
def test_a_player_can_offer_a_price_that_breaks_even(game, state, player_id, price):
    send(game, state, player_id, {"offer": price})

    assert game.view(state, player_id)["my_offer"] == price


def test_a_player_cannot_accept_a_price_that_loses_money(game, state):
    send(game, state, BUYER, {"offer": 20})

    reason = rejection(game, state, SELLER, {"accept": 20})

    assert reason == "that price would lose you money"


def test_accepting_needs_an_offer_from_the_other_player(game, state):
    send(game, state, SELLER, {"offer": 60})

    assert rejection(game, state, SELLER, {"accept": 60}) == (
        "there's no offer to accept"
    )


def test_accepting_an_offer_that_has_since_changed_is_refused(game, state):
    send(game, state, SELLER, {"offer": 60})
    send(game, state, SELLER, {"offer": 70})

    assert rejection(game, state, BUYER, {"accept": 60}) == "that offer has changed"


@pytest.mark.parametrize("message", ["deal", ["offer", 50], {"bid": 5}])
def test_other_messages_are_refused(game, state, message):
    assert rejection(game, state, BUYER, message) == (
        "a message is an offer or an accept"
    )


def test_a_deal_ends_the_game_and_pays_each_player_their_gain(game, state):
    send(game, state, BUYER, {"offer": 55})
    assert not game.is_over(state)

    send(game, state, SELLER, {"accept": 55})

    assert game.is_over(state)
    assert game.outcome(state, "finished") == {
        "roles": {SELLER: "seller", BUYER: "buyer"},
        "values": {SELLER: 30, BUYER: 80},
        "deal": 55,
        "earnings": {SELLER: 25, BUYER: 25},
    }
    assert game.view(state, SELLER)["earnings"] == 25


def test_bargaining_closes_at_the_deadline_with_nothing_paid(game, state):
    send(game, state, SELLER, {"offer": 60})
    assert game.next_deadline(state) == 60

    game.tick(state, 59.9)
    assert not game.is_over(state)
    game.tick(state, 60)

    assert game.is_over(state)
    assert game.outcome(state, "finished")["earnings"] == {SELLER: 0, BUYER: 0}


def test_bots_with_no_profitable_price_stop_at_their_limits(game, state):
    state["values"] = {SELLER: 50, BUYER: 52}

    play_bots(game, state)

    assert state["deal"] is None
    assert state["standing"] == {"seller": 55, "buyer": 47}


def test_a_bot_accepts_an_offer_that_earns_it_five_cents(game, state):
    send(game, state, BUYER, {"offer": 34})
    assert game.bot(game.view(state, SELLER), SELLER, 0) == {"offer": 95}

    send(game, state, BUYER, {"offer": 35})

    assert game.bot(game.view(state, SELLER), SELLER, 0) == {"accept": 35}


def network_of(*recruiter_ids, full=True):
    nodes = [
        mock.Mock(participant=mock.Mock(id=n, recruiter_id=r))
        for n, r in enumerate(recruiter_ids, start=1)
    ]
    return mock.Mock(full=full, **{"nodes.return_value": nodes})


@mock.patch("dlgr.demos.bargaining.experiment.create_realtime_session")
def test_a_full_network_starts_a_bargain_with_runner_played_bots(create):
    # A browser bot's recruiter id is "bots", and it plays on the page
    Bargaining.add_node_to_network(None, mock.Mock(), network_of("bots", "bots:Bot"))

    create.assert_called_once_with(Bargain, [1, 2], bots=[2])


@mock.patch("dlgr.demos.bargaining.experiment.create_realtime_session")
def test_a_network_waiting_for_its_second_player_starts_nothing(create):
    Bargaining.add_node_to_network(None, mock.Mock(), network_of("hotair", full=False))

    create.assert_not_called()


@mock.patch("dlgr.demos.bargaining.experiment.realtime_sessions_for")
def test_the_bonus_is_the_earnings_of_each_ended_bargain_in_dollars(sessions_for):
    sessions_for.return_value = [
        mock.Mock(status="ended", outcome={"earnings": {"7": 25, "8": 30}}),
        mock.Mock(status="failed", outcome={"earnings": {"7": 40, "8": 0}}),
        mock.Mock(status="ended", outcome={"earnings": {"7": 12, "8": 3}}),
    ]
    participant = mock.Mock(id=7)

    assert Bargaining.bonus(None, participant) == 0.37
    sessions_for.assert_called_once_with(participant, Bargain)


@pytest.fixture
def bot():
    bot = Bot.__new__(Bot)
    bot.URL = "http://localhost:5000/ad?x=1"
    bot.participant_id = 7
    bot.log = mock.Mock()
    bot.wait_for_realtime_sessions = mock.Mock()
    return bot


@mock.patch("dlgr.demos.bargaining.experiment.requests.post")
def test_a_bot_joins_a_pair_then_waits_for_its_bargain(post, bot):
    bot.participate()

    post.assert_called_once_with("http://localhost:5000/node/7")
    bot.wait_for_realtime_sessions.assert_called_once_with(Bargain)


@mock.patch("dlgr.demos.bargaining.experiment.requests.post")
def test_a_bot_that_cannot_join_a_pair_does_not_wait(post, bot):
    post.return_value.ok = False

    bot.participate()

    bot.wait_for_realtime_sessions.assert_not_called()
