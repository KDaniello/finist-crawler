"""
Тесты для engine/fallback_chain.py

Покрытие: 100%
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions import CaptchaBlockError, NetworkError
from engine.fallback_chain import FallbackOrchestrator
from engine.parsing_rules import CrawlerPlan

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_lock():
    return MagicMock()


@pytest.fixture
def dummy_profiles_dir(tmp_path):
    return tmp_path / "profiles"


@pytest.fixture
def dummy_plan():
    return CrawlerPlan(
        start_urls=["http://test.com"],
        start_phase="list",
        item_selector=".item",
        fields={},
        request_headers={},
    )


@pytest.fixture
def mock_save_cb():
    return MagicMock()


@pytest.fixture
def mock_light_cls():
    with patch("engine.fallback_chain.LightExecutor") as MockCls:
        instance = AsyncMock()
        MockCls.return_value.__aenter__.return_value = instance
        yield instance


@pytest.fixture
def mock_stealth_cls():
    with patch("engine.fallback_chain.StealthExecutor") as MockCls:
        instance = AsyncMock()
        MockCls.return_value.__aenter__.return_value = instance
        yield instance


# ---------------------------------------------------------------------------
# Validation Tests
# ---------------------------------------------------------------------------


class TestFallbackOrchestratorValidation:
    @pytest.mark.asyncio
    async def test_unknown_strategy_raises(self, dummy_profiles_dir, dummy_plan, mock_save_cb):
        orchestrator = FallbackOrchestrator(
            browser_lock=None, profiles_dir=dummy_profiles_dir, render_strategy="magic"
        )
        with pytest.raises(ValueError, match="Неизвестная стратегия рендеринга: magic"):
            await orchestrator.execute_plan(dummy_plan, mock_save_cb)

    @pytest.mark.asyncio
    async def test_browser_strategy_without_lock_raises(
        self, dummy_profiles_dir, dummy_plan, mock_save_cb
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=None, profiles_dir=dummy_profiles_dir, render_strategy="browser"
        )
        with pytest.raises(RuntimeError, match="не передал Browser Lock"):
            await orchestrator.execute_plan(dummy_plan, mock_save_cb)


# ---------------------------------------------------------------------------
# "Static" Strategy Tests
# ---------------------------------------------------------------------------


class TestFallbackOrchestratorStatic:
    @pytest.mark.asyncio
    async def test_static_success(
        self,
        mock_lock,
        dummy_profiles_dir,
        dummy_plan,
        mock_save_cb,
        mock_light_cls,
        mock_stealth_cls,
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=mock_lock, profiles_dir=dummy_profiles_dir, render_strategy="static"
        )
        mock_light_cls.execute.return_value = (10, {"executor": "Light"})
        total, stats = await orchestrator.execute_plan(dummy_plan, mock_save_cb)

        assert total == 10
        mock_light_cls.execute.assert_called_once()
        mock_stealth_cls.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_static_captcha_aborts(
        self,
        mock_lock,
        dummy_profiles_dir,
        dummy_plan,
        mock_save_cb,
        mock_light_cls,
        mock_stealth_cls,
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=mock_lock, profiles_dir=dummy_profiles_dir, render_strategy="static"
        )
        mock_light_cls.execute.side_effect = CaptchaBlockError("http://test", "HTTP 403")
        with pytest.raises(CaptchaBlockError, match="HTTP 403"):
            await orchestrator.execute_plan(dummy_plan, mock_save_cb)

    @pytest.mark.asyncio
    async def test_static_network_error_aborts(
        self,
        mock_lock,
        dummy_profiles_dir,
        dummy_plan,
        mock_save_cb,
        mock_light_cls,
        mock_stealth_cls,
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=mock_lock, profiles_dir=dummy_profiles_dir, render_strategy="static"
        )
        mock_light_cls.execute.side_effect = NetworkError("Timeout")
        with pytest.raises(NetworkError, match="Timeout"):
            await orchestrator.execute_plan(dummy_plan, mock_save_cb)


# ---------------------------------------------------------------------------
# "Browser" Strategy Tests
# ---------------------------------------------------------------------------


class TestFallbackOrchestratorBrowser:
    @pytest.mark.asyncio
    async def test_browser_success(
        self,
        mock_lock,
        dummy_profiles_dir,
        dummy_plan,
        mock_save_cb,
        mock_light_cls,
        mock_stealth_cls,
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=mock_lock, profiles_dir=dummy_profiles_dir, render_strategy="browser"
        )
        mock_stealth_cls.execute.return_value = (5, {"executor": "Stealth"})
        total, stats = await orchestrator.execute_plan(dummy_plan, mock_save_cb)

        assert total == 5
        mock_light_cls.execute.assert_not_called()
        mock_stealth_cls.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_browser_crash_raises(
        self,
        mock_lock,
        dummy_profiles_dir,
        dummy_plan,
        mock_save_cb,
        mock_light_cls,
        mock_stealth_cls,
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=mock_lock, profiles_dir=dummy_profiles_dir, render_strategy="browser"
        )
        mock_stealth_cls.execute.side_effect = ValueError("Browser Exploded")
        with pytest.raises(
            NetworkError, match="Сбой финального Fallback-экзекутора: Browser Exploded"
        ):
            await orchestrator.execute_plan(dummy_plan, mock_save_cb)


# ---------------------------------------------------------------------------
# "Auto" (Fallback Chain) Strategy Tests
# ---------------------------------------------------------------------------


class TestFallbackOrchestratorAuto:
    @pytest.mark.asyncio
    async def test_auto_success_on_light(
        self,
        mock_lock,
        dummy_profiles_dir,
        dummy_plan,
        mock_save_cb,
        mock_light_cls,
        mock_stealth_cls,
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=mock_lock, profiles_dir=dummy_profiles_dir, render_strategy="auto"
        )
        mock_light_cls.execute.return_value = (20, {"executor": "Light"})
        total, stats = await orchestrator.execute_plan(dummy_plan, mock_save_cb)

        assert total == 20
        mock_light_cls.execute.assert_called_once()
        mock_stealth_cls.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_fallback_on_captcha(
        self,
        mock_lock,
        dummy_profiles_dir,
        dummy_plan,
        mock_save_cb,
        mock_light_cls,
        mock_stealth_cls,
        caplog,
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=mock_lock, profiles_dir=dummy_profiles_dir, render_strategy="auto"
        )
        mock_light_cls.execute.side_effect = CaptchaBlockError("url", "Turnstile")
        mock_stealth_cls.execute.return_value = (15, {"executor": "Stealth"})
        await orchestrator.execute_plan(dummy_plan, mock_save_cb)

        mock_light_cls.execute.assert_called_once()
        mock_stealth_cls.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_fallback_on_network_error(
        self,
        mock_lock,
        dummy_profiles_dir,
        dummy_plan,
        mock_save_cb,
        mock_light_cls,
        mock_stealth_cls,
        caplog,
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=mock_lock, profiles_dir=dummy_profiles_dir, render_strategy="auto"
        )
        mock_light_cls.execute.side_effect = NetworkError("DNS Error")
        mock_stealth_cls.execute.return_value = (2, {"executor": "Stealth"})
        await orchestrator.execute_plan(dummy_plan, mock_save_cb)

        mock_light_cls.execute.assert_called_once()
        mock_stealth_cls.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_both_crash(
        self,
        mock_lock,
        dummy_profiles_dir,
        dummy_plan,
        mock_save_cb,
        mock_light_cls,
        mock_stealth_cls,
    ):
        orchestrator = FallbackOrchestrator(
            browser_lock=mock_lock, profiles_dir=dummy_profiles_dir, render_strategy="auto"
        )
        mock_light_cls.execute.side_effect = CaptchaBlockError("url")
        mock_stealth_cls.execute.side_effect = Exception("Camoufox Dead")
        with pytest.raises(NetworkError, match="Сбой финального Fallback-экзекутора"):
            await orchestrator.execute_plan(dummy_plan, mock_save_cb)
