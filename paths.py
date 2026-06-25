"""Расположение файлов приложения.

Логи и конфиг хранятся не рядом с exe (Program Files доступен только на чтение),
а в %PROGRAMDATA%\\RPSU Monitor — общей для всех пользователей папке с правом записи.
Папка для SCADA-CSV задаётся отдельно в настройках (см. config.scada_csv_dir).

Для тестов путь к данным можно переопределить переменной окружения RPSU_DATA_DIR.
"""
import os
import sys

APP_NAME = "RPSU Monitor"


def app_dir():
    """Папка установки: где лежит exe (frozen) или скрипт (разработка)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_data_dir():
    override = os.environ.get("RPSU_DATA_DIR")
    if override:
        path = override
    else:
        base = os.environ.get("PROGRAMDATA") or os.environ.get("ALLUSERSPROFILE")
        path = os.path.join(base, APP_NAME) if base else os.path.join(app_dir(), "data")
    os.makedirs(path, exist_ok=True)
    return path


DATA_DIR = _resolve_data_dir()
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
