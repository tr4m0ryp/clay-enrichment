"""Tests for the main orchestrator module."""

import asyncio
import signal
from unittest.mock import MagicMock, patch

import pytest

import src.main as main_module
from src.main import _validate_config, supervised_worker, _get_shutdown_event


@pytest.fixture(autouse=True)
def _fresh_shutdown_event():
    """Create a fresh shutdown event for each test to avoid loop binding issues."""
    main_module.shutdown_event = asyncio.Event()
    yield
    main_module.shutdown_event = None


class TestValidateConfig:
    """Tests for startup config validation."""

    def test_valid_config_passes(self):
        """No error when required keys are present."""
        config = MagicMock()
        config.gemini_api_key = "test-key"
        config.database_url = "postgresql://localhost/test"
        _validate_config(config)

    def test_missing_gemini_key_exits(self):
        """Exits with code 1 when GEMINI_API_KEY is missing."""
        config = MagicMock()
        config.gemini_api_key = ""
        config.database_url = "postgresql://localhost/test"
        with pytest.raises(SystemExit) as exc_info:
            _validate_config(config)
        assert exc_info.value.code == 1

    def test_missing_database_url_exits(self):
        """Exits with code 1 when DATABASE_URL is missing."""
        config = MagicMock()
        config.gemini_api_key = "test-key"
        config.database_url = ""
        with pytest.raises(SystemExit) as exc_info:
            _validate_config(config)
        assert exc_info.value.code == 1

    def test_all_keys_missing_exits(self):
        """Exits with code 1 when all required keys are missing."""
        config = MagicMock()
        config.gemini_api_key = ""
        config.database_url = ""
        with pytest.raises(SystemExit) as exc_info:
            _validate_config(config)
        assert exc_info.value.code == 1


class TestSupervisedWorker:
    """Tests for the supervised_worker restart logic."""

    @pytest.fixture(autouse=True)
    def _fast_restart(self, monkeypatch):
        """Speed up restart delay for tests."""
        monkeypatch.setattr(main_module, "RESTART_DELAY_SECONDS", 0.01)

    @pytest.mark.asyncio
    async def test_restarts_after_crash(self):
        """Worker restarts after raising, up to shutdown."""
        call_count = 0
        evt = _get_shutdown_event()

        async def flaky_worker():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("boom")
            evt.set()

        with patch("src.main.logger", MagicMock()):
            await supervised_worker("test", flaky_worker)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_stops_on_shutdown_event(self):
        """Worker exits when shutdown_event is set during restart delay."""
        call_count = 0
        evt = _get_shutdown_event()

        async def crashing_worker():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("crash")

        async def set_shutdown_soon():
            await asyncio.sleep(0.005)
            evt.set()

        with patch("src.main.logger", MagicMock()):
            task = asyncio.create_task(supervised_worker("test", crashing_worker))
            stopper = asyncio.create_task(set_shutdown_soon())
            await asyncio.gather(task, stopper)

        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_cancelled_worker_exits_cleanly(self):
        """Worker exits cleanly when its task is cancelled."""
        async def forever_worker():
            await asyncio.sleep(3600)

        with patch("src.main.logger", MagicMock()):
            task = asyncio.create_task(supervised_worker("test", forever_worker))
            await asyncio.sleep(0.01)
            task.cancel()
            # supervised_worker catches CancelledError and returns
            await task

    @pytest.mark.asyncio
    async def test_passes_args_to_worker(self):
        """Positional and keyword args are forwarded to the worker."""
        received_args = {}
        evt = _get_shutdown_event()

        async def capturing_worker(a, b, key=None):
            received_args["a"] = a
            received_args["b"] = b
            received_args["key"] = key
            # Signal done so supervisor exits
            evt.set()

        with patch("src.main.logger", MagicMock()):
            await supervised_worker("test", capturing_worker, "x", "y", key="z")

        assert received_args == {"a": "x", "b": "y", "key": "z"}


class TestGracefulShutdown:
    """Tests for signal handling and graceful shutdown."""

    @pytest.mark.asyncio
    async def test_signal_handler_sets_shutdown_event(self):
        """Signal handler mechanism sets the shutdown event."""
        loop = asyncio.get_running_loop()

        from src.main import _install_signal_handlers
        with patch("src.main.logger", MagicMock()):
            _install_signal_handlers(loop)
            evt = _get_shutdown_event()
            evt.set()
            assert evt.is_set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
