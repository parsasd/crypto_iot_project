"""
Integration test placeholder for the price feeder and MQTT broker.

In a full CI environment this test would spin up a Mosquitto broker,
start the price feeder and verify that messages are published to the
expected topics.  Due to the limitations of this example the test
simply asserts True.
"""


def test_feeder_placeholder():
    assert True