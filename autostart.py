"""Автозапуск при входе в Windows через ключ реестра HKCU\\…\\Run.

Текущий пользователь — права администратора не нужны. Запись срабатывает при
входе пользователя; на сервере с автологином программа поднимется сама после
перезагрузки. Источник истины — сам реестр (чекбокс инициализируется из него).
"""
import os
import sys

try:
    import winreg
except ImportError:        # не-Windows — функции становятся «пустыми»
    winreg = None

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_NAME = "RPSU Monitor"


def _target():
    """Команда запуска для реестра (в кавычках из-за пробелов в пути)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'


def autostart_enabled(name=APP_RUN_NAME):
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, name)
        return True
    except OSError:
        return False


def set_autostart(enable, name=APP_RUN_NAME):
    if winreg is None:
        return
    if enable:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, _target())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass
        except OSError:
            pass
