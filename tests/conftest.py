import multiprocessing
import warnings

import pytest

from core._openpyxl_compat import apply_openpyxl_compat

apply_openpyxl_compat()

warnings.filterwarnings("ignore", message="Proactor event loop does not implement add_reader")
warnings.filterwarnings("ignore", category=pytest.PytestUnraisableExceptionWarning)
warnings.filterwarnings("ignore", message="unclosed transport")

pytest_plugins = ("pytest_asyncio",)


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that spawn real processes",
    )
    parser.addoption(
        "--run-performance",
        action="store_true",
        default=False,
        help="Run performance benchmarks",
    )
    parser.addoption(
        "--run-browser",
        action="store_true",
        default=False,
        help="Run tests that launch a real browser",
    )
    parser.addoption(
        "--run-stress",
        action="store_true",
        default=False,
        help="Run stress tests",
    )


def pytest_collection_modifyitems(config, items):
    skip_map = {
        "integration": not config.getoption("--run-integration"),
        "performance": not config.getoption("--run-performance"),
        "browser": not config.getoption("--run-browser"),
        "stress": not config.getoption("--run-stress"),
    }
    for item in items:
        for marker_name, should_skip in skip_map.items():
            if should_skip and marker_name in [m.name for m in item.iter_markers()]:
                item.add_marker(pytest.mark.skip(reason=f"Needs --run-{marker_name}"))


@pytest.fixture(scope="session")
def browser_lock():
    """Системный лок ОС, который использует диспетчер."""
    ctx = multiprocessing.get_context("spawn")
    return ctx.Lock()


@pytest.fixture(scope="session")
def httpserver_listen_address():
    """Фиксируем порт локального сервера для стабильности тестов."""
    return ("127.0.0.1", 8080)


@pytest.fixture(autouse=True)
def isolate_numpy(monkeypatch):
    """
    Защищает numpy от загрязнения sys.modules между тестами.
    Некоторые моки Camoufox могут оставлять фейковый 'numpy' в кэше модулей,
    что ломает реальный импорт numpy.random в последующих тестах.
    """
    import sys

    # Запоминаем оригинальный numpy если он уже загружен
    numpy_keys_before = {k for k in sys.modules if k == "numpy" or k.startswith("numpy.")}

    yield

    # После теста проверяем: если numpy был подменён фейком — восстанавливаем
    for key in list(sys.modules.keys()):
        if (key == "numpy" or key.startswith("numpy.")) and key not in numpy_keys_before:
            del sys.modules[key]
