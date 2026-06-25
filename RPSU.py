# --- https://github.com/UterGrooll/RPSU-monitor ---
"""Точка входа RPSU Monitor.

Логика разнесена по модулям:
  parsers.py         — разбор ответов устройства
  telnet_session.py  — telnet-обмен поверх «сырого» сокета
  paths.py           — расположение папок (данные, конфиг)
  storage.py         — config.json и CSV-журналы
  monitoring.py      — цикл опроса устройства
  gui.py             — класс App: интерфейс и состояние
"""
import os
import sys
from datetime import datetime

from paths import DATA_DIR
from gui import App


def _setup_logging():
    """В сборке с --noconsole у PyInstaller sys.stdout/stderr = None, и любой
    print() либо падает, либо теряется. Перенаправляем вывод в файл-лог —
    он же служит журналом диагностики (ошибки подключения и т.п.).
    """
    log_path = os.path.join(DATA_DIR, "rpsu.log")
    try:
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        stream = open(os.devnull, "w")
    sys.stdout = stream
    sys.stderr = stream
    print(f"\n===== RPSU Monitor запущен {datetime.now():%Y-%m-%d %H:%M:%S} =====")


if __name__ == "__main__":
    _setup_logging()
    App().run()
