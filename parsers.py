"""Разбор текстовых ответов устройства (telnet) в значения параметров.

Чистые функции без состояния — на вход строка ответа, на выход значение.
"""
import re


def clean_response(response):
    # Удаляем ANSI escape sequences (цвета и т.п.)
    response = re.sub(r'\x1B\[[0-9;]*[a-zA-Z]', '', response)
    # Оставляем только печатаемые ASCII + переводы строк
    response = re.sub(r'[^\x20-\x7E\n\r]', '', response)
    return response.strip()


def extract_value(response, key):
    match = re.search(rf"{re.escape(key)}\s*[:=]\s*([-\d.]+)", response, re.IGNORECASE)
    return match.group(1) if match else "0"


def extract_uptime(response):
    match = re.search(r"RPSU Uptime[:=]\s*(\d+)", response, re.IGNORECASE)
    return match.group(1) if match else "0"


def extract_rpsu_status(response):
    match = re.search(r"RPSU Status[:=]\s*(ON|OFF)", response, re.IGNORECASE)
    return match.group(1).upper() if match else "OFF"


def extract_temperature(response):
    # Формат ответа: "Temperature : 31.250 C" — число, затем пробел и C.
    match = re.search(r"Temperature\s*[:=]\s*([0-9.]+)\s*C", response, re.IGNORECASE)
    if match:
        try:
            # Округляем до 1 знака, сохраняя строкой: 31.250 → 31.2
            return f"{float(match.group(1)):.1f}"
        except ValueError:
            pass
    return "0.0"
