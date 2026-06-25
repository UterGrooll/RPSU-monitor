"""Логика опроса одного устройства в фоновом потоке.

monitor_device читает живое состояние из объекта app (polling_interval, window,
utc_enabled), поэтому смена интервала/UTC применяется на следующем витке.
"""
import time
import tkinter as tk
from dataclasses import dataclass

from parsers import (
    clean_response,
    extract_value,
    extract_uptime,
    extract_rpsu_status,
    extract_temperature,
)
from telnet_session import connect_to_device, send_command
from applog import log
import storage


def _report_values(app, name, values):
    """Отдаёт последние значения устройства в App для проверки сигнализации.
    values = (status, voltage, current, leak, temp) или None (нет данных).
    В юнит-тестах App может не уметь report_values — тогда тихо пропускаем."""
    fn = getattr(app, "report_values", None)
    if fn:
        try:
            fn(name, values)
        except Exception:
            pass


@dataclass
class DeviceWidgets:
    """tkinter-переменные одной карточки устройства + метка температуры
    (её цвет меняется отдельно). Опрос обновляет их из фонового потока."""
    status: tk.StringVar
    uptime: tk.StringVar
    voltage: tk.StringVar
    current: tk.StringVar
    leak: tk.StringVar
    temperature: tk.StringVar
    temp_label: tk.Label


def _update_temp_color(app, temp_label, temperature):
    """>40°C → оранжевая метка, иначе чёрная. Меняем цвет в GUI-потоке."""
    try:
        temp_val = float(temperature)
    except ValueError:
        temp_val = 0.0

    colors = getattr(app, "colors", None) or {}
    normal = colors.get("text", "black")
    warn = colors.get("warn", "orange")

    def apply():
        try:
            temp_label.config(fg=warn if temp_val > 40.0 else normal)
        except Exception:
            pass

    if app.window:
        try:
            app.window.after(0, apply)
        except Exception:
            pass
    else:
        apply()


def monitor_device(app, device, widgets, stop_event):
    """Цикл опроса одного устройства. Крутится в отдельном потоке-демоне и
    останавливается, когда выставлен stop_event. Период равен выставленному
    интервалу (app.polling_interval, минуты) и отсчитывается от начала витка,
    чтобы не «уползать» на время обработки."""
    ip = device["ip"]
    name = device["name"]

    while not stop_event.is_set():
        # Начало витка фиксируем заранее: пауза отсчитывается от него, поэтому
        # период опроса равен интервалу и не зависит от времени обработки.
        cycle_start = time.monotonic()

        tn = connect_to_device(ip, device["port"])
        # Тему могли переключить (карточки пересобираются) — не трогаем старые виджеты.
        if stop_event.is_set():
            if tn:
                try:
                    tn.close()
                except Exception:
                    pass
            break
        if not tn:
            try:
                widgets.status.set("Нет связи")
            except Exception:
                pass
            if app.window:
                normal = (getattr(app, "colors", None) or {}).get("text", "black")
                try:
                    app.window.after(0, lambda col=normal: widgets.temp_label.config(fg=col))
                except Exception:
                    pass
            _report_values(app, name, None)
        else:
            temperature = "0.0"
            rpsu_status = "OFF"
            rpsu_uptime = "0"
            voltage = "0"
            current = "0"
            leak_current = "0"

            try:
                # 1. Вход в меню модема
                _ = send_command(tn, "2", delay=1)

                # 2. Температуру читаем ДО входа в RPSU-меню
                status_resp = send_command(tn, "STATUS", delay=1)
                temperature = extract_temperature(clean_response(status_resp))

                # 3. Переход к платам
                _ = send_command(tn, "%1", delay=1)
                echo_resp = send_command(tn, "ECHO", delay=1)
                cleaned_echo = clean_response(echo_resp)

                if "04" not in cleaned_echo:
                    widgets.status.set("Нет RPSU")
                    _report_values(app, name, None)
                else:
                    # 4. Подключаемся к RPSU (плата 04)
                    _ = send_command(tn, "%104", delay=1)
                    _ = send_command(tn, "1", delay=1)
                    show_resp = send_command(tn, "SHOW", delay=2)
                    cleaned_show = clean_response(show_resp)

                    # 5. Извлекаем RPSU-параметры
                    rpsu_status = extract_rpsu_status(cleaned_show)
                    rpsu_uptime = extract_uptime(cleaned_show)
                    voltage = extract_value(cleaned_show, "Voltage")
                    current = extract_value(cleaned_show, "Current")
                    leak_current = extract_value(cleaned_show, "Leak Current")

                    # 6. Обновляем GUI
                    widgets.status.set("Авария" if rpsu_status == "OFF" else rpsu_status)
                    widgets.uptime.set(rpsu_uptime)
                    widgets.voltage.set(voltage)
                    widgets.current.set(current)
                    widgets.leak.set(leak_current)
                    widgets.temperature.set(temperature)
                    _update_temp_color(app, widgets.temp_label, temperature)

                    # 7. Запись в CSV (логи — в папку данных; UTC для SCADA — в заданную папку)
                    storage.write_to_csv(name, rpsu_status, rpsu_uptime, voltage, current, leak_current, temperature)
                    if app.utc_enabled and app.utc_enabled.get():
                        storage.write_to_utc_csv(name, rpsu_status, rpsu_uptime, voltage, current, leak_current, temperature, app.scada_csv_dir)

                    # 8. Отдаём значения в App → проверка сигнализации (звук + рамка)
                    _report_values(app, name, (rpsu_status, voltage, current, leak_current, temperature))

            except Exception as e:
                log(f"[{name}] ошибка опроса: {e}")
                try:
                    widgets.status.set("Ошибка")
                except Exception:
                    pass
                _report_values(app, name, None)
            finally:
                try:
                    tn.close()
                except Exception:
                    pass

        # Пауза до конца интервала; прерывается мгновенно при stop_event.
        elapsed = time.monotonic() - cycle_start
        wait_s = max(0, app.polling_interval * 60 - elapsed)
        if stop_event.wait(wait_s):
            break
