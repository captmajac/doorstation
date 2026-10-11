import pytest

from doorstation_common.config import ConfigError, MqttSettings, load_yaml


def test_mqtt_defaults():
    assert MqttSettings.from_dict(None) == MqttSettings("localhost", 1883, "doorstation")


def test_mqtt_unknown_key_rejected():
    with pytest.raises(ConfigError, match="hots"):
        MqttSettings.from_dict({"hots": "x"})


def test_load_yaml_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_yaml(tmp_path / "nope.yaml")


def test_load_yaml_not_mapping(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("- 1\n")
    with pytest.raises(ConfigError):
        load_yaml(p)


def test_mqtt_heartbeat_default_and_override():
    assert MqttSettings.from_dict(None).heartbeat_s == 300
    assert MqttSettings.from_dict({"heartbeat_s": 0}).heartbeat_s == 0


def test_load_yaml_duplicate_key_rejected(tmp_path):
    # Sonst überschreibt der zweite Eintrag still den ersten (z. B. zwei Eingänge "bell").
    p = tmp_path / "a.yaml"
    p.write_text("inputs:\n  bell: {pin: 9}\n  bell: {pin: 10}\n")
    with pytest.raises(ConfigError, match="bell"):
        load_yaml(p)


def test_load_yaml_same_key_in_different_mappings_ok(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("a: {pin: 1}\nb: {pin: 2}\n")
    assert load_yaml(p) == {"a": {"pin": 1}, "b": {"pin": 2}}


@pytest.mark.parametrize("d, field", [
    ({"host": 123}, "host"), ({"host": ""}, "host"),
    ({"port": "1883"}, "port"), ({"port": 0}, "port"), ({"port": 70000}, "port"), ({"port": True}, "port"),
    ({"prefix": "door/station"}, "prefix"), ({"prefix": "a#"}, "prefix"), ({"prefix": ""}, "prefix"),
    ({"prefix": 5}, "prefix"),
])
def test_mqtt_invalid_values_rejected(d, field):
    with pytest.raises(ConfigError, match=field):
        MqttSettings.from_dict(d)
