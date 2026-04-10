"""
Finist Crawler — Benchmark Suite
Измеряет скорость и потребление ресурсов каждого источника.

Запуск:
    python benchmark.py                    # все источники
    python benchmark.py --source habr      # один источник
    python benchmark.py --output results   # сохранить в benchmark_results.json
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import psutil
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Добавляем корень в sys.path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bots.universal_bot import run_universal_bot
from core.config import get_paths, setup_environment
from core.dispatcher import Dispatcher
from core.file_manager import SessionManager
from core.job_config import JobConfig
from core.logger import setup_main_logging, stop_main_logging

console = Console()

# =============================================================================
# СЦЕНАРИИ БЕНЧМАРКА
# Минимальные параметры — достаточно для замера, не слишком долго
# =============================================================================

BENCHMARK_SCENARIOS: dict[str, JobConfig] = {
    "habr": JobConfig(
        spec_name="habr_search.yaml",
        max_pages=10,
        detail_max_pages=0,
        template_params={"keyword": "Python"},
    ),
    "lenta": JobConfig(
        spec_name="lenta_search.yaml",
        max_pages=10,
        detail_max_pages=0,
        template_params={"keyword": "технологии"},
    ),
    "reddit": JobConfig(
        spec_name="reddit_comments.yaml",
        max_pages=2,
        detail_max_pages=20,
        template_params={"keyword": "python"},
    ),
    "steam": JobConfig(
        spec_name="steam_reviews.yaml",
        max_pages=1,
        detail_max_pages=20,
        template_params={"app_id": "1091500"},
    ),
    "2gis": JobConfig(
        spec_name="twogis_search.yaml",
        max_pages=5,
        template_params={"keyword": "Кофе"},
    ),
}

# Человекочитаемые названия
SOURCE_NAMES = {
    "habr": "Хабр",
    "lenta": "Лента.ру",
    "reddit": "Reddit",
    "steam": "Steam",
    "2gis": "2GIS",
    "otzovik": "Отзовик",
}

# Тип данных каждого источника
SOURCE_DATA_TYPE = {
    "habr": "статьи",
    "lenta": "статьи",
    "reddit": "комментарии",
    "steam": "отзывы",
    "2gis": "отзывы",
    "otzovik": "отзывы",
}

# Стратегия рендеринга
SOURCE_STRATEGY = {
    "habr": "static (curl_cffi)",
    "lenta": "static (curl_cffi)",
    "reddit": "static (curl_cffi)",
    "steam": "static (curl_cffi)",
    "2gis": "static (curl_cffi)",
    "otzovik": "browser (Camoufox)",
}


@dataclass
class BenchmarkResult:
    """Результат одного прогона бенчмарка."""

    source_key: str
    source_name: str
    data_type: str
    strategy: str

    # Временные метрики
    elapsed_sec: float = 0.0
    records_collected: int = 0
    records_per_second: float = 0.0

    # Метрики памяти (в МБ)
    ram_start_mb: float = 0.0
    ram_peak_mb: float = 0.0
    ram_delta_mb: float = 0.0

    # Статус
    success: bool = False
    error: str = ""

    # Метаданные
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    python_version: str = field(
        default_factory=lambda: f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )


def _get_process_ram_mb(pid: int) -> float:
    """Возвращает RSS память процесса и всех его потомков в МБ."""
    try:
        proc = psutil.Process(pid)
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return round(total / (1024**2), 1)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0


def _monitor_ram(
    pid: int,
    samples: list[float],
    stop_flag: list[bool],
    interval: float = 0.5,
) -> None:
    """Фоновый поток — собирает RAM сэмплы каждые interval секунд."""
    while not stop_flag[0]:
        mb = _get_process_ram_mb(pid)
        if mb > 0:
            samples.append(mb)
        time.sleep(interval)


def _count_jsonl_records(jsonl_path: Path) -> int:
    """Считает непустые строки в JSONL файле."""
    if not jsonl_path.exists():
        return 0
    try:
        count = 0
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
    except OSError:
        return 0


def run_single_benchmark(
    source_key: str,
    job: JobConfig,
    paths,
    log_queue,
) -> BenchmarkResult:
    """
    Запускает один источник и измеряет метрики.

    Returns:
        BenchmarkResult с заполненными метриками.
    """
    result = BenchmarkResult(
        source_key=source_key,
        source_name=SOURCE_NAMES.get(source_key, source_key),
        data_type=SOURCE_DATA_TYPE.get(source_key, "записи"),
        strategy=SOURCE_STRATEGY.get(source_key, "auto"),
    )

    # RAM до запуска
    current_pid = os.getpid()
    result.ram_start_mb = _get_process_ram_mb(current_pid)

    # Запускаем мониторинг RAM в фоне
    ram_samples: list[float] = [result.ram_start_mb]
    stop_flag: list[bool] = [False]

    import threading

    ram_thread = threading.Thread(
        target=_monitor_ram,
        args=(current_pid, ram_samples, stop_flag, 0.5),
        daemon=True,
    )
    ram_thread.start()

    session_mgr = SessionManager(base_dir=paths.data_dir)
    dispatcher = Dispatcher(session_manager=session_mgr, log_queue=log_queue)

    start_time = time.perf_counter()

    try:
        session_id = dispatcher.start_tasks(
            worker_target=run_universal_bot,
            specs=[job.spec_name],
            config_overrides=job.to_dict(),
        )

        if not session_id:
            result.error = "Dispatcher не смог запустить задачу"
            return result

        # Ждём завершения с таймаутом 5 минут
        timeout = 300.0
        poll_interval = 1.0
        waited = 0.0

        while dispatcher.is_running() and waited < timeout:
            time.sleep(poll_interval)
            waited += poll_interval

        if waited >= timeout:
            dispatcher.stop_all()
            result.error = f"Таймаут {timeout}с"
            result.success = False
        else:
            result.success = True

    except Exception as e:
        result.error = str(e)
        result.success = False
        dispatcher.stop_all()

    finally:
        elapsed = time.perf_counter() - start_time
        stop_flag[0] = True
        ram_thread.join(timeout=2.0)

    result.elapsed_sec = round(elapsed, 2)

    # Считаем записи из JSONL
    if session_id:
        # Ищем папку источника внутри сессии
        session_dir = paths.data_dir / session_id
        if session_dir.exists():
            for source_dir in session_dir.iterdir():
                if source_dir.is_dir():
                    jsonl = source_dir / f"{source_dir.name}.jsonl"
                    result.records_collected += _count_jsonl_records(jsonl)

    # Метрики RAM
    if ram_samples:
        result.ram_peak_mb = round(max(ram_samples), 1)
        result.ram_delta_mb = round(result.ram_peak_mb - result.ram_start_mb, 1)

    # Записей в секунду
    if result.elapsed_sec > 0 and result.records_collected > 0:
        result.records_per_second = round(result.records_collected / result.elapsed_sec, 2)

    return result


def print_results_table(results: list[BenchmarkResult]) -> None:
    """Выводит красивую таблицу результатов через Rich."""
    table = Table(
        title="Finist Crawler — Benchmark Results",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        padding=(0, 1),
    )

    table.add_column("Источник", style="bold white", width=12)
    table.add_column("Тип данных", style="dim white", width=12)
    table.add_column("Стратегия", style="dim cyan", width=22)
    table.add_column("Время", justify="right", style="yellow", width=10)
    table.add_column("Собрано", justify="right", style="green", width=10)
    table.add_column("Записей/сек", justify="right", style="bright_green", width=12)
    table.add_column("RAM старт", justify="right", style="dim white", width=10)
    table.add_column("RAM пик", justify="right", style="magenta", width=10)
    table.add_column("RAM дельта", justify="right", style="red", width=11)
    table.add_column("Статус", justify="center", width=8)

    for r in results:
        status = "✅" if r.success else "❌"
        if not r.success and r.error:
            status = "❌"

        elapsed_str = f"{r.elapsed_sec:.1f}с"
        records_str = f"{r.records_collected:,}"
        rps_str = f"{r.records_per_second:.1f}" if r.records_per_second > 0 else "—"
        ram_start_str = f"{r.ram_start_mb:.0f} MB"
        ram_peak_str = f"{r.ram_peak_mb:.0f} MB"
        ram_delta_str = (
            f"+{r.ram_delta_mb:.0f} MB" if r.ram_delta_mb >= 0 else f"{r.ram_delta_mb:.0f} MB"
        )

        table.add_row(
            r.source_name,
            r.data_type,
            r.strategy,
            elapsed_str,
            records_str,
            rps_str,
            ram_start_str,
            ram_peak_str,
            ram_delta_str,
            status,
        )

    console.print()
    console.print(table)

    # Сводка
    successful = [r for r in results if r.success]
    if successful:
        total_records = sum(r.records_collected for r in successful)
        avg_rps = (
            statistics.mean(r.records_per_second for r in successful if r.records_per_second > 0)
            if any(r.records_per_second > 0 for r in successful)
            else 0
        )
        max_ram = max(r.ram_peak_mb for r in successful)

        console.print(
            Panel(
                f"[bold green]Успешно:[/] {len(successful)}/{len(results)} источников\n"
                f"[bold cyan]Всего собрано:[/] {total_records:,} записей\n"
                f"[bold yellow]Средняя скорость:[/] {avg_rps:.1f} записей/сек\n"
                f"[bold magenta]Пик RAM:[/] {max_ram:.0f} MB",
                title="[bold]Итого[/]",
                border_style="bright_black",
            )
        )

    # Ошибки
    failed = [r for r in results if not r.success]
    if failed:
        console.print()
        for r in failed:
            console.print(f"[red]❌ {r.source_name}:[/] {r.error or 'неизвестная ошибка'}")


def save_results(results: list[BenchmarkResult], output_path: Path) -> None:
    """Сохраняет результаты в JSON для использования в README."""
    data = {
        "benchmark_date": datetime.now(UTC).isoformat(),
        "python_version": results[0].python_version if results else "",
        "platform": sys.platform,
        "results": [asdict(r) for r in results],
        "summary": {
            "total_sources": len(results),
            "successful": sum(1 for r in results if r.success),
            "total_records": sum(r.records_collected for r in results if r.success),
            "avg_records_per_second": round(
                statistics.mean(
                    r.records_per_second for r in results if r.success and r.records_per_second > 0
                ),
                2,
            )
            if any(r.success and r.records_per_second > 0 for r in results)
            else 0,
            "max_ram_mb": max((r.ram_peak_mb for r in results if r.success), default=0),
        },
    }

    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"\n[dim]Результаты сохранены: {output_path}[/]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finist Crawler Benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python benchmark.py                          # все источники
  python benchmark.py --source habr            # только Хабр
  python benchmark.py --source habr lenta      # Хабр и Лента
  python benchmark.py --save                   # сохранить в JSON
        """,
    )
    parser.add_argument(
        "--source",
        nargs="+",
        choices=list(BENCHMARK_SCENARIOS.keys()),
        help="Источники для тестирования (по умолчанию — все)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Сохранить результаты в benchmark_results.json",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="Пропустить источники с browser-стратегией (Отзовик)",
    )
    args = parser.parse_args()

    # Выбираем сценарии
    selected = args.source or list(BENCHMARK_SCENARIOS.keys())
    scenarios = {k: BENCHMARK_SCENARIOS[k] for k in selected if k in BENCHMARK_SCENARIOS}

    if args.skip_browser:
        scenarios = {
            k: v for k, v in scenarios.items() if SOURCE_STRATEGY.get(k, "").startswith("static")
        }

    if not scenarios:
        console.print("[red]Нет сценариев для запуска[/]")
        return

    setup_environment()
    paths = get_paths()
    log_queue = setup_main_logging(
        logs_dir=paths.logs_dir,
        debug=False,
    )

    # Глушим консольный вывод во время бенчмарка
    import logging as _logging

    import core.logger as _core_logger

    if _core_logger._log_listener:
        for handler in _core_logger._log_listener.handlers:
            if isinstance(handler, _logging.StreamHandler):
                handler.setLevel(_logging.CRITICAL)

    console.print(
        Panel(
            f"[bold cyan]Finist Crawler Benchmark[/]\n"
            f"Источников: [yellow]{len(scenarios)}[/]  |  "
            f"Пропуск браузера: [yellow]{'да' if args.skip_browser else 'нет'}[/]",
            border_style="bright_black",
        )
    )
    console.print()

    results: list[BenchmarkResult] = []

    for i, (source_key, job) in enumerate(scenarios.items(), 1):
        name = SOURCE_NAMES.get(source_key, source_key)
        strategy = SOURCE_STRATEGY.get(source_key, "auto")

        console.print(
            f"[dim]([{i}/{len(scenarios)}])[/] [bold white]{name}[/] [dim]{strategy}[/] ...",
            end=" ",
        )

        result = run_single_benchmark(
            source_key=source_key,
            job=job,
            paths=paths,
            log_queue=log_queue,
        )
        results.append(result)

        if result.success:
            console.print(
                f"[green]✓[/] "
                f"[yellow]{result.elapsed_sec:.1f}с[/]  "
                f"[green]{result.records_collected:,} записей[/]  "
                f"[cyan]{result.records_per_second:.1f} зап/с[/]  "
                f"[magenta]RAM +{result.ram_delta_mb:.0f}MB[/]"
            )
        else:
            console.print(f"[red]✗ {result.error}[/]")

        # Пауза между источниками — даём ОС освободить ресурсы
        if i < len(scenarios):
            time.sleep(3.0)

    print_results_table(results)

    if args.save:
        output_path = _ROOT / "benchmark_results.json"
        save_results(results, output_path)

    stop_main_logging()
    log_queue.close()
    log_queue.cancel_join_thread()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
