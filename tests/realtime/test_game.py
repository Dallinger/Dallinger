import pytest

from dallinger.db import CONTROL_CHANNEL, DIRECT_CHANNEL
from dallinger.realtime import RealtimeGame, validate_game_types


class Duel(RealtimeGame):
    channel = "duel"

    def initial_state(self, players):
        return {"players": players}

    def apply(self, state, player_id, message, now, sent):
        pass


def game_type(**attributes):
    return type("Configured", (Duel,), attributes)


class TestValidGameTypes:
    def test_returns_an_instance_per_channel(self):
        Race = game_type(channel="race", tick_rate=20)

        games = validate_game_types([Duel, Race], experiment_channel="chat")

        assert set(games) == {"duel", "race"}
        assert type(games["duel"]) is Duel
        assert type(games["race"]) is Race

    @pytest.mark.parametrize(
        "attributes",
        [
            {"tick_rate": 0},
            {"tick_rate": 0.5},
            {"max_duration": 0.25},
            {"max_messages_per_second": 0.5},
            {"message_burst": 1},
            {"time_limit": 0.01},
            {"time_limit": 60},
            {"state_version": "2b"},
        ],
    )
    def test_boundary_settings_are_accepted(self, attributes):
        assert validate_game_types([game_type(**attributes)])


class TestInvalidGameTypes:
    @pytest.mark.parametrize("game_type", [object, Duel()])
    def test_not_a_game_type(self, game_type):
        with pytest.raises(ValueError, match="not a RealtimeGame subclass"):
            validate_game_types([game_type])

    def test_duplicate_channel_names_both_types(self):
        Other = type("Other", (Duel,), {})

        with pytest.raises(ValueError, match="^Duel and Other both use the channel"):
            validate_game_types([Duel, Other])

    def test_channel_is_required(self):
        class Unnamed(RealtimeGame):
            def initial_state(self, players):
                return {}

            def apply(self, state, player_id, message, now, sent):
                pass

        with pytest.raises(ValueError, match="^Unnamed's channel must be a non-empty"):
            validate_game_types([Unnamed])

    def test_experiment_channel(self):
        with pytest.raises(ValueError, match="Duel's channel duel is the experiment's"):
            validate_game_types([Duel], experiment_channel="duel")

    @pytest.mark.parametrize("channel", [CONTROL_CHANNEL, DIRECT_CHANNEL])
    def test_reserved_channel(self, channel):
        with pytest.raises(ValueError, match="reserved for Dallinger's own use"):
            validate_game_types([game_type(channel=channel)])

    def test_settings_set_in_init_are_checked(self):
        class Configured(Duel):
            def __init__(self):
                self.tick_rate = -1

        with pytest.raises(ValueError, match="^Configured's tick_rate"):
            validate_game_types([Configured])

    @pytest.mark.parametrize(
        "attributes, error",
        [
            ({"channel": ""}, "channel must be a non-empty string"),
            ({"channel": 7}, "channel must be a non-empty string"),
            ({"channel": "duel:2"}, "channel 'duel:2' may not contain a colon"),
            ({"tick_rate": -1}, "tick_rate must be a number, 0 or more"),
            ({"tick_rate": "20"}, "tick_rate must be a number"),
            ({"max_duration": 0}, "max_duration must be None or a positive"),
            ({"max_duration": -5}, "max_duration must be None or a positive"),
            ({"max_duration": float("inf")}, "max_duration must be None"),
            ({"max_messages_per_second": 0}, "max_messages_per_second must be a"),
            ({"max_messages_per_second": -1}, "max_messages_per_second must be a"),
            ({"max_messages_per_second": None}, "max_messages_per_second must"),
            ({"message_burst": 0}, "message_burst must be a whole number"),
            ({"message_burst": 2.5}, "message_burst must be a whole number"),
            ({"time_limit": 0}, "time_limit must be a positive number"),
            ({"time_limit": None}, "time_limit must be a positive number"),
            ({"time_limit": 61}, "time_limit must be a positive number, at most 60"),
            ({"state_version": (1, 2)}, "state_version must be an integer or a"),
        ],
    )
    def test_setting(self, attributes, error):
        with pytest.raises(ValueError, match="^Configured's " + error):
            validate_game_types([game_type(**attributes)])

    def test_required_methods_are_checked(self):
        class Partial(RealtimeGame):
            channel = "partial"

            def appy(self, state, player_id, message, now, sent):
                pass

        with pytest.raises(
            ValueError, match="^Partial must define apply and initial_state"
        ):
            validate_game_types([Partial])
