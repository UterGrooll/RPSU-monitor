"""Хранение данных: конфиг (config.json) и журналы измерений (CSV).

Логи (`{name}_data.csv`) и конфиг лежат в DATA_DIR (%PROGRAMDATA%\\RPSU Monitor).
SCADA-журнал (`{name}_utc_data.csv`) пишется в отдельную папку scada_dir, заданную
пользователем (её читает CSV-драйвер Rapid SCADA); при пустом пути — рядом с логами.
"""
import os
import csv
import json
import copy
from datetime import datetime, timedelta

import paths
from paths import DATA_DIR, CONFIG_PATH
from applog import log

CSV_HEADER = ["Timestamp", "Status", "Uptime", "Voltage", "Current", "Leak Current", "Temperature"]

DEFAULT_CONFIG = {
    "devices": [],
    "polling_interval": 60,   # минуты
    "utc_enabled": False,
    "scada_csv_dir": "",      # пусто → SCADA-CSV пишется в DATA_DIR
    "theme": "light",         # "light" | "dark"
    "alarm": {
        "sound": True,
        "rules": {
            "status_off":  {"on": True},
            "leak_high":   {"on": True,  "value": 0.1},   # ±0.1 мА — предупреждение по паспорту
            "temp_high":   {"on": True,  "value": 45},    # рабочий максимум платы
        },
    },
}


# ----------------------------------------------------------------------
# Конфиг
# ----------------------------------------------------------------------
def load_config():
    """Читает config.json; при отсутствии — пытается мигрировать старый
    devices.json. Всегда возвращает полный словарь (с дефолтами)."""
    data = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = _migrate_legacy_devices()
    except Exception as e:
        log(f"Ошибка чтения config.json: {e}")

    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if isinstance(data, dict):
        for key in cfg:
            if key in data:
                cfg[key] = data[key]
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _migrate_legacy_devices():
    """Старый формат — devices.json (просто список устройств). Ищем рядом с
    данными, с exe и в текущей папке; возвращаем как {'devices': [...]}"""
    for folder in (DATA_DIR, paths.app_dir(), os.getcwd()):
        legacy = os.path.join(folder, "devices.json")
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                devices = json.load(f)
            if isinstance(devices, list):
                log(f"Перенесён старый devices.json из {folder}")
                return {"devices": devices}
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return {}


# ----------------------------------------------------------------------
# CSV-журналы
# ----------------------------------------------------------------------
def log_path(device_name):
    """Путь к основному журналу устройства (в папке данных)."""
    return os.path.join(DATA_DIR, f"{device_name}_data.csv")


def write_to_csv(device_name, rpsu_status, rpsu_uptime, voltage, current, leak_current, temperature):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filename = log_path(device_name)
    file_exists = os.path.exists(filename)

    with open(filename, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, delimiter=";")
        if not file_exists:
            writer.writerow(CSV_HEADER)
        writer.writerow([timestamp, rpsu_status, rpsu_uptime, voltage, current, leak_current, temperature])


def write_to_utc_csv(device_name, rpsu_status, rpsu_uptime, voltage, current, leak_current, temperature, scada_dir=""):
    timestamp_utc = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    status_numeric = 1 if rpsu_status == "ON" else 0
    if status_numeric == 0:
        rpsu_uptime = voltage = current = leak_current = "0"

    target_dir = scada_dir or DATA_DIR
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        log(f"Папка SCADA недоступна ({target_dir}): {e}; пишу в {DATA_DIR}")
        target_dir = DATA_DIR
    filename = os.path.join(target_dir, f"{device_name}_utc_data.csv")
    file_exists = os.path.exists(filename)

    with open(filename, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, delimiter=";")
        if not file_exists:
            writer.writerow(CSV_HEADER)
        writer.writerow([timestamp_utc, status_numeric, rpsu_uptime, voltage, current, leak_current, temperature])


def get_last_data_from_csv(device_name):
    """Последняя строка журнала: (status, uptime, voltage, current, leak, temperature).
    Если файла/данных нет — кортеж из пустых строк."""
    try:
        filename = log_path(device_name)
        if not os.path.exists(filename):
            return "", "", "", "", "", ""

        with open(filename, 'r', encoding='utf-8') as f:
            reader = list(csv.reader(f, delimiter=';'))
            if len(reader) > 1:
                last = reader[-1]
                return (
                    last[1] if len(last) > 1 else "",
                    last[2] if len(last) > 2 else "",
                    last[3] if len(last) > 3 else "",
                    last[4] if len(last) > 4 else "",
                    last[5] if len(last) > 5 else "",
                    last[6] if len(last) > 6 else ""
                )
    except Exception as e:
        log(f"Ошибка чтения CSV: {e}")
    return "", "", "", "", "", ""
