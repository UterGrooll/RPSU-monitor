"""Простой журнал событий.

Пишет строки с меткой времени в stdout, который в собранном приложении
перенаправлен в C:\\ProgramData\\RPSU Monitor\\rpsu.log (см. RPSU._setup_logging).
Логируем только значимое (старт, ошибки подключения, сбои) — без спама на
каждый успешный опрос.
"""
from datetime import datetime


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {msg}")
