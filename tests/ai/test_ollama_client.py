"""L1 Unit — OllamaClient: config defaults, connectivity, lifecycle.

No Ollama installation required — all tests use an unreachable port.
"""

from __future__ import annotations

import allure
import pytest

from storguard.ai.ollama_client import OllamaClient, OllamaConfig


@allure.feature("AI — Ollama Client")
@allure.story("Configuration")
@pytest.mark.unit
class TestOllamaConfig:

    @allure.title("Default config points to localhost and has a non-empty model")
    def test_default_host(self):
        with allure.step("Instantiate default OllamaConfig"):
            cfg = OllamaConfig()
        with allure.step("Assert host is localhost:11434"):
            assert cfg.host == "http://localhost:11434"

    @allure.title("Default model is set (environment-specific value)")
    def test_default_model_non_empty(self):
        with allure.step("Instantiate default OllamaConfig"):
            cfg = OllamaConfig()
        with allure.step("Assert model is non-empty string"):
            assert cfg.model

    @allure.title("Temperature defaults to deterministic value 0.1")
    def test_default_temperature(self):
        with allure.step("Instantiate default OllamaConfig"):
            cfg = OllamaConfig()
        with allure.step("Assert temperature == 0.1"):
            assert cfg.temperature == 0.1

    @allure.title("Timeout is large enough for 26B model inference")
    def test_timeout_sufficient_for_large_model(self):
        with allure.step("Instantiate default OllamaConfig"):
            cfg = OllamaConfig()
        with allure.step("Assert timeout >= 120 seconds"):
            assert cfg.timeout_seconds >= 120


@allure.feature("AI — Ollama Client")
@allure.story("Connectivity")
@pytest.mark.unit
class TestOllamaClientConnectivity:

    @allure.title("Returns False when server is unreachable")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_is_available_false_on_bad_port(self):
        with allure.step("Create client pointing at port 19999 (nothing listening)"):
            client = OllamaClient(OllamaConfig(host="http://localhost:19999"))

        with allure.step("Assert is_available() returns False"):
            assert client.is_available() is False

        with allure.step("Close client"):
            client.close()

    @allure.title("Gracefully handles DNS that does not resolve")
    def test_is_available_false_on_bad_host(self):
        with allure.step("Create client with unresolvable hostname"):
            client = OllamaClient(OllamaConfig(host="http://no-such-host-xyz.local:11434"))

        with allure.step("Assert is_available() returns False without raising"):
            assert client.is_available() is False

        with allure.step("Close client"):
            client.close()


@allure.feature("AI — Ollama Client")
@allure.story("Lifecycle")
@pytest.mark.unit
class TestOllamaClientLifecycle:

    @allure.title("Context manager closes client without error")
    def test_context_manager_closes_cleanly(self):
        with allure.step("Enter context manager with unreachable host"):
            with OllamaClient(OllamaConfig(host="http://localhost:19999")) as client:
                with allure.step("Assert is_available() returns False inside context"):
                    assert not client.is_available()

    @allure.title("Multiple clients can coexist independently")
    def test_multiple_clients_independent(self):
        with allure.step("Create two clients on different ports"):
            c1 = OllamaClient(OllamaConfig(host="http://localhost:19998"))
            c2 = OllamaClient(OllamaConfig(host="http://localhost:19997"))

        with allure.step("Assert both report unavailable independently"):
            assert c1.is_available() is False
            assert c2.is_available() is False

        with allure.step("Close both clients"):
            c1.close()
            c2.close()
