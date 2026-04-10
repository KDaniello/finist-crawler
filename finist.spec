# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec файл для Finist Crawler.
Сборка: pyinstaller finist.spec
"""

from __future__ import annotations

from pathlib import Path
import sys

block_cipher = None
ROOT = Path(SPECPATH)
import sysconfig
SP = Path(sysconfig.get_paths()["purelib"])

# ── Пакеты ───────────────────────────────────────────────────────────────────
import flet
import flet_desktop

FLET_DIR         = Path(flet.__file__).parent
FLET_DESKTOP_DIR = Path(flet_desktop.__file__).parent
CAMOUFOX_DIR     = SP / "camoufox"
BROWSERFORGE_DIR = SP / "browserforge"
APIFY_DIR        = SP / "apify_fingerprint_datapoints"
PLAYWRIGHT_DIR   = SP / "playwright"
LANGUAGE_TAGS_DIR= SP / "language_tags"
CERTIFI_DIR      = SP / "certifi"

# ── Данные ────────────────────────────────────────────────────────────────────
added_files = [
    # Проект
    (str(ROOT / "specs"),  "specs"),
    (str(ROOT / "assets"), "assets"),

    # Flet
    (str(FLET_DIR),         "flet"),
    (str(FLET_DESKTOP_DIR), "flet_desktop"),

    # camoufox data-файлы
    (str(CAMOUFOX_DIR / "browserforge.yml"),        "camoufox"),
    (str(CAMOUFOX_DIR / "fonts.json"),              "camoufox"),
    (str(CAMOUFOX_DIR / "GeoLite2-City.mmdb"),      "camoufox"),
    (str(CAMOUFOX_DIR / "launchServer.js"),         "camoufox"),
    (str(CAMOUFOX_DIR / "territoryInfo.xml"),       "camoufox"),
    (str(CAMOUFOX_DIR / "setup.cfg"),               "camoufox"),
    (str(CAMOUFOX_DIR / "warnings.yml"),            "camoufox"),
    (str(CAMOUFOX_DIR / "webgl" / "webgl_data.db"), "camoufox/webgl"),

    # browserforge data
    (str(BROWSERFORGE_DIR / "injectors" / "data" / "utils.js.xz"),
     "browserforge/injectors/data"),

    # apify_fingerprint_datapoints — все data файлы
    (str(APIFY_DIR / "data" / "browser-helper-file.json"),
     "apify_fingerprint_datapoints/data"),
    (str(APIFY_DIR / "data" / "fingerprint-network-definition.zip"),
     "apify_fingerprint_datapoints/data"),
    (str(APIFY_DIR / "data" / "header-network-definition.zip"),
     "apify_fingerprint_datapoints/data"),
    (str(APIFY_DIR / "data" / "headers-order.json"),
     "apify_fingerprint_datapoints/data"),
    (str(APIFY_DIR / "data" / "input-network-definition.zip"),
     "apify_fingerprint_datapoints/data"),

    # playwright driver (node.exe + весь package)
    (str(PLAYWRIGHT_DIR / "driver"), "playwright/driver"),

    # language_tags — все json файлы
    (str(LANGUAGE_TAGS_DIR / "data" / "json"), "language_tags/data/json"),

    # certifi — корневые сертификаты
    (str(CERTIFI_DIR / "cacert.pem"), "certifi"),
]

# ── Скрытые импорты ───────────────────────────────────────────────────────────
hidden_imports = [
    # Flet
    "flet",
    "flet.app",
    "flet.utils",
    "flet.utils.pip",
    "flet.controls",
    "flet.controls.material",
    "flet.controls.material.icons",
    "flet_desktop",

    # curl_cffi
    "curl_cffi",
    "curl_cffi.requests",
    "curl_cffi.requests.errors",

    # Camoufox
    "camoufox",
    "camoufox.async_api",
    "camoufox.sync_api",
    "camoufox.pkgman",
    "camoufox.fingerprints",
    "camoufox.utils",
    "camoufox.addons",
    "camoufox.locale",
    "camoufox.ip",
    "camoufox.server",
    "camoufox.warnings",
    "camoufox.webgl",
    "camoufox.webgl.sample",

    # Playwright
    "playwright",
    "playwright.async_api",

    # browserforge
    "browserforge",
    "browserforge.bayesian_network",
    "browserforge.download",
    "browserforge.headers",
    "browserforge.headers.generator",
    "browserforge.headers.utils",
    "browserforge.fingerprints",
    "browserforge.fingerprints.generator",
    "browserforge.injectors",
    "browserforge.injectors.data",
    "browserforge.injectors.playwright",
    "browserforge.injectors.playwright.injector",
    "browserforge.injectors.pyppeteer",
    "browserforge.injectors.undetected_playwright",
    "apify_fingerprint_datapoints",

    # language_tags (используется camoufox для локалей)
    "language_tags",
    "language_tags.Subtag",
    "language_tags.Tag",
    "language_tags.data",

    # numpy (требуется camoufox)
    "numpy",
    "numpy.core",
    "numpy.core._multiarray_umath",

    # certifi
    "certifi",

    # Parsing
    "bs4",
    "jmespath",
    "jsonschema",
    "jsonschema.validators",
    "yaml",

    # Data
    "openpyxl",
    "openpyxl.styles",
    "openpyxl.utils",
    "openpyxl.compat.numbers",
    "openpyxl.compat.strings",

    # Core
    "pydantic",
    "pydantic_settings",
    "psutil",
    "requests",
    "colorama",
    "charset_normalizer",
    "charset_normalizer.md",
    "charset_normalizer.cd",

    # Project modules
    "core",
    "core.config",
    "core.dispatcher",
    "core.exceptions",
    "core.file_manager",
    "core.job_config",
    "core.logger",
    "core.resources",
    "core.telemetry",
    "core.updater",
    "engine",
    "engine.fallback_chain",
    "engine.parsing_rules",
    "engine.rate_limiter",
    "engine.spec_loader",
    "engine.executors",
    "engine.executors.base",
    "engine.executors.light",
    "engine.executors.stealth",
    "engine.browser",
    "engine.browser.behaviors",
    "engine.browser.browser_setup",
    "engine.browser.detection",
    "engine.browser.profiles",
    "bots.universal_bot",
    "ui.app",
    "ui.theme",
    "ui.pages.launcher",
    "ui.pages.monitor",
    "ui.pages.results",
]

# ── Исключения ────────────────────────────────────────────────────────────────
excludes = [
    "pandas",
    "matplotlib",
    "scipy",
    "PIL._imagingtk",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "wx",
    "gtk",
    "IPython",
    "jupyter",
    "notebook",
    "sphinx",
    "docutils",
    "test",
    "tests",
    "unittest",
    "pytest",
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── PYZ ───────────────────────────────────────────────────────────────────────
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

# ── EXE ───────────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="FinistCrawler",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        "vcruntime140.dll",
        "python3*.dll",
        "_ssl*.pyd",
        "curl_cffi*.pyd",
        "fletd.exe",
        "node.exe",
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
    onefile=True,
)