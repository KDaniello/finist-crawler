import asyncio
import logging
import random

from playwright.async_api import Page

logger = logging.getLogger(__name__)

__all__ = ["HumanBehavior"]

# --- МАТЕМАТИКА ТРАЕКТОРИЙ ---


def _bezier(
    t: float,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> tuple[float, float]:
    """Кубическая кривая Безье для плавного движения."""
    u = 1.0 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return x, y


def _mouse_path(
    start: tuple[float, float], end: tuple[float, float], steps: int
) -> list[tuple[float, float]]:
    """Генерирует человечную траекторию с микро-дрожанием руки."""
    dx, dy = end[0] - start[0], end[1] - start[1]

    # Контрольные точки с рандомизацией, но без сильных выбросов
    cp1 = (
        start[0] + dx * random.uniform(0.2, 0.4) + random.uniform(-20, 20),
        start[1] + dy * random.uniform(0.2, 0.4) + random.uniform(-20, 20),
    )
    cp2 = (
        start[0] + dx * random.uniform(0.6, 0.8) + random.uniform(-15, 15),
        start[1] + dy * random.uniform(0.6, 0.8) + random.uniform(-15, 15),
    )

    path = []
    for i in range(steps + 1):
        t = i / steps
        # Ease-in-out: замедление в начале и в конце
        t_eased = t * t * (3 - 2 * t)

        px, py = _bezier(t_eased, start, cp1, cp2, end)

        if 0 < i < steps:
            # Добавляем микро-шум (дрожание руки), но не для первой/последней точки
            px += random.gauss(0, 0.8)
            py += random.gauss(0, 0.8)

        path.append((max(0.0, px), max(0.0, py)))  # Защита от отрицательных координат

    return path


class HumanBehavior:
    """
    Класс для имитации поведения реального пользователя.
    Обходит поведенческие проверки Cloudflare/DataDome.
    """

    def __init__(self, page: Page):
        self._page = page
        self._mx: float = 0.0
        self._my: float = 0.0
        self._viewport_initialized = False

    async def _init_viewport(self) -> None:
        """Лениво инициализирует координаты в пределах реального окна браузера."""
        if self._viewport_initialized:
            return

        try:
            viewport = self._page.viewport_size
            width = viewport.get("width", 1280) if viewport else 1280
            height = viewport.get("height", 720) if viewport else 720
        except Exception:
            width, height = 1280, 720

        # Ставим мышь где-то в безопасной зоне экрана
        self._mx = random.uniform(width * 0.2, width * 0.8)
        self._my = random.uniform(height * 0.2, height * 0.8)
        self._viewport_initialized = True

    async def mouse_move(self, target_x: float, target_y: float) -> None:
        """Перемещает мышь к цели по кривой Безье с "человечными" паузами."""
        await self._init_viewport()

        # Защита от выхода за экран (Playwright не любит координаты < 0)
        target_x = max(0.0, target_x)
        target_y = max(0.0, target_y)

        # Количество шагов зависит от расстояния (от 15 до 40)
        distance = ((target_x - self._mx) ** 2 + (target_y - self._my) ** 2) ** 0.5
        steps = int(min(max(distance / 20.0, 15), 40))

        path = _mouse_path((self._mx, self._my), (target_x, target_y), steps)

        for i, (px, py) in enumerate(path):
            await self._page.mouse.move(px, py)

            # Задержка между микро-движениями (от 5 до 15 мс)
            # Человек замедляется перед тем как попасть в цель
            delay = random.uniform(0.005, 0.015)
            if i > steps * 0.8:
                delay *= 1.5

            await asyncio.sleep(delay)

        self._mx, self._my = target_x, target_y

        # Микро-пауза после остановки мыши
        await asyncio.sleep(random.uniform(0.1, 0.3))

    async def mouse_jiggle(self) -> None:
        """Случайное блуждание мыши (имитация чтения или раздумий)."""
        await self._init_viewport()
        try:
            viewport = self._page.viewport_size
            w = viewport.get("width", 1280) if viewport else 1280
            h = viewport.get("height", 720) if viewport else 720

            # Идем в случайную точку, не подходя слишком близко к краям
            tx = random.uniform(w * 0.1, w * 0.9)
            ty = random.uniform(h * 0.1, h * 0.9)

            await self.mouse_move(tx, ty)
        except Exception as e:
            logger.debug(f"Ошибка при mouse_jiggle: {e}")

    async def scroll_down(self, pixels: int = 0) -> None:
        """Скроллит страницу вниз рывками, как это делает палец на колесике мыши."""
        amount = pixels or random.randint(300, 800)

        # Разбиваем общий скролл на 3-6 рывков
        chunks = random.randint(3, 6)
        base_chunk = amount // chunks

        for i in range(chunks):
            # Добавляем случайность (иногда скроллим больше, иногда чуть-чуть назад)
            delta = base_chunk + random.randint(-40, 60)

            # Человек редко крутит колесико строго в одном направлении, иногда палец соскальзывает
            if random.random() < 0.05 and i > 0:
                delta = -abs(delta // 3)

            await self._page.mouse.wheel(0, delta)

            # Пауза между щелчками колесика
            await asyncio.sleep(random.uniform(0.05, 0.2))

        # Пауза "на чтение" после скролла
        await asyncio.sleep(random.uniform(0.5, 1.5))
