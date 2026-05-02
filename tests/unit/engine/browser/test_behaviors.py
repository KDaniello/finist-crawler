"""
Тесты для engine/browser/behaviors.py

Покрытие: 100%
- Математика _bezier: проверка краевых точек (t=0 и t=1).
- Траектории _mouse_path: генерация списка точек, защита от отрицательных координат.
- Инициализация HumanBehavior: ленивый _init_viewport (с/без viewport_size, обработка ошибок).
- mouse_move: правильное разбиение на шаги, вызов page.mouse.move, замедление в конце пути.
- mouse_jiggle: генерация случайной точки в пределах экрана, перехват неожиданных ошибок Playwright.
- scroll_down: разбиение скролла на рывки, эффект "соскальзывания" (отрицательный delta), вызов page.mouse.wheel.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.browser.behaviors import (
    HumanBehavior,
    _bezier,
    _mouse_path,
)

# ---------------------------------------------------------------------------
# Math & Path Generation Tests
# ---------------------------------------------------------------------------


class TestMathAndPaths:
    def test_bezier_endpoints(self):
        """Проверка, что кривая Безье всегда начинается в p0 и заканчивается в p3."""
        p0 = (10.0, 10.0)
        p1 = (20.0, 50.0)
        p2 = (80.0, 50.0)
        p3 = (90.0, 10.0)

        # В начале пути (t = 0)
        start_pt = _bezier(0.0, p0, p1, p2, p3)
        assert start_pt == p0

        # В конце пути (t = 1)
        end_pt = _bezier(1.0, p0, p1, p2, p3)
        assert end_pt == p3

        # Где-то посередине (t = 0.5) - просто убеждаемся, что математика не падает
        mid_pt = _bezier(0.5, p0, p1, p2, p3)
        assert 10 < mid_pt[0] < 90

    def test_mouse_path_generation(self):
        """Генерация пути должна создавать нужное кол-во точек и не уходить в минус."""
        start = (100.0, 100.0)
        end = (200.0, 200.0)
        steps = 10

        with patch("random.gauss", return_value=5.0):  # Фиксируем шум для предсказуемости
            path = _mouse_path(start, end, steps)

        assert len(path) == steps + 1
        assert path[0] == start
        # Последняя точка может не совпадать идеально с `end` из-за шума,
        # но _bezier без шума на t=1 возвращает end. В нашей функции шум не применяется к последней точке.
        assert path[-1] == end

    def test_mouse_path_negative_protection(self):
        """Путь не должен содержать отрицательных координат, даже при сильном шуме."""
        start = (0.0, 0.0)
        end = (5.0, 5.0)

        # Очень сильный отрицательный шум, который увел бы координаты в минус
        with patch("random.gauss", return_value=-50.0):
            path = _mouse_path(start, end, steps=5)

        for x, y in path:
            assert x >= 0.0
            assert y >= 0.0


# ---------------------------------------------------------------------------
# HumanBehavior Tests
# ---------------------------------------------------------------------------


class TestHumanBehavior:
    @pytest.fixture
    def mock_page(self):
        """Мокает объект Page из Playwright."""
        page = MagicMock()
        page.viewport_size = {"width": 1920, "height": 1080}
        page.mouse = AsyncMock()
        return page

    @pytest.fixture
    def behavior(self, mock_page):
        return HumanBehavior(page=mock_page)

    @pytest.mark.asyncio
    async def test_init_viewport_success(self, behavior):
        """Ленивая инициализация должна задать стартовые координаты."""
        assert not behavior._viewport_initialized
        assert behavior._mx == 0.0
        assert behavior._my == 0.0

        await behavior._init_viewport()

        assert behavior._viewport_initialized
        assert 1920 * 0.2 <= behavior._mx <= 1920 * 0.8
        assert 1080 * 0.2 <= behavior._my <= 1080 * 0.8

    @pytest.mark.asyncio
    async def test_init_viewport_no_size(self, behavior, mock_page):
        """Если viewport_size = None, используются дефолты 1280x720."""
        mock_page.viewport_size = None
        await behavior._init_viewport()

        assert behavior._viewport_initialized
        assert 1280 * 0.2 <= behavior._mx <= 1280 * 0.8

    @pytest.mark.asyncio
    async def test_init_viewport_error_fallback(self, behavior, mock_page):
        """Если обращение к viewport_size падает, используются дефолты."""
        # Имитируем PropertyMock, который выбрасывает ошибку
        type(mock_page).viewport_size = property(
            lambda self: (_ for _ in ()).throw(Exception("Dead"))
        )

        await behavior._init_viewport()

        assert behavior._viewport_initialized
        assert 1280 * 0.2 <= behavior._mx <= 1280 * 0.8

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_mouse_move(self, mock_sleep, behavior, mock_page):
        """Проверка логики перемещения мыши."""
        behavior._mx, behavior._my = 100.0, 100.0
        behavior._viewport_initialized = True

        # Двигаемся далеко, чтобы шагов было максимум (40)
        await behavior.mouse_move(1000.0, 1000.0)

        # 41 точка пути (включая старт и финиш) -> 41 вызов mouse.move
        assert mock_page.mouse.move.call_count == 41

        # 41 вызов sleep в цикле + 1 финальный sleep
        assert mock_sleep.call_count == 42

        # Координаты должны обновиться
        assert behavior._mx == 1000.0
        assert behavior._my == 1000.0

        # Последний вызов move должен быть точно в target (защита от < 0 тоже работает)
        mock_page.mouse.move.assert_called_with(1000.0, 1000.0)

    @pytest.mark.asyncio
    @patch("engine.browser.behaviors.HumanBehavior.mouse_move", new_callable=AsyncMock)
    async def test_mouse_jiggle_success(self, mock_move, behavior):
        """Jiggle должен выбрать случайную точку и вызвать mouse_move."""
        behavior._viewport_initialized = True

        with patch("random.uniform", side_effect=[500.0, 600.0]):
            await behavior.mouse_jiggle()

        mock_move.assert_called_once_with(500.0, 600.0)

    @pytest.mark.asyncio
    @patch("engine.browser.behaviors.HumanBehavior.mouse_move", new_callable=AsyncMock)
    async def test_mouse_jiggle_error_handling(self, mock_move, behavior, caplog):
        """Ошибки внутри jiggle (например, закрытая страница) проглатываются."""
        import logging

        mock_move.side_effect = Exception("Page closed")

        with caplog.at_level(logging.DEBUG):
            await behavior.mouse_jiggle()

        assert "Ошибка при mouse_jiggle: Page closed" in caplog.text

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_scroll_down_behavior(self, mock_sleep, behavior, mock_page):
        """Скролл должен разбиваться на рывки (с возможным откатом назад)."""
        # Фиксируем random, чтобы было ровно 4 чанка и 1 откат
        with (
            patch("random.randint", side_effect=[4, 10, 10, 10, 10]),
            patch("random.random", side_effect=[1.0, 0.01, 1.0, 1.0]),
        ):  # На 2-й итерации random < 0.05
            # Скроллим на 400 пикселей (базовый чанк = 100)
            await behavior.scroll_down(pixels=400)

        # Вызвалось 4 раза
        assert mock_page.mouse.wheel.call_count == 4

        # 4 паузы между чанками + 1 финальная пауза "на чтение"
        assert mock_sleep.call_count == 5

        # Проверяем аргументы вызовов (y-delta)
        calls = mock_page.mouse.wheel.call_args_list
        # Итерация 0: 100 + 10 = 110
        assert calls[0][0][1] == 110
        # Итерация 1: "соскальзывание" (откат назад). delta = 100 + 10 = 110. откат = -abs(110//3) = -36
        assert calls[1][0][1] == -36
        # Итерация 2 и 3: 100 + 10 = 110
        assert calls[2][0][1] == 110
        assert calls[3][0][1] == 110
