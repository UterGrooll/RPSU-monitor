"""Звуковая сигнализация и проверка аварийных условий.

Пороги по паспорту MGS-4-RPSU: ток утечки — предупреждение при ±0.1 мА,
отключение при ±1 мА; защита платы по температуре +80 °C (рабочий диапазон до 45).
Напряжение/ток в прямом режиме стабилизированы — падение ниже порога указывает на
проблему с линией/регенератором (порог задаёт пользователь под свою линию).
"""
import threading
import time

try:
    import winsound
except ImportError:        # не-Windows
    winsound = None


def _to_float(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def evaluate(status, voltage, current, leak, temp, rules):
    """Возвращает список сработавших условий (тексты) для одного устройства."""
    reasons = []
    r = rules or {}
    st = (status or "").strip().upper()

    if r.get("status_off", {}).get("on") and st in ("OFF", "АВАРИЯ"):
        reasons.append("Авария ДП (статус OFF)")

    leak_v = _to_float(leak)
    rule = r.get("leak_high", {})
    if rule.get("on") and leak_v is not None:
        thr = _to_float(rule.get("value"))
        if thr is not None and abs(leak_v) >= thr:
            reasons.append(f"Ток утечки {leak_v} ≥ {thr} мА")

    temp_v = _to_float(temp)
    rule = r.get("temp_high", {})
    if rule.get("on") and temp_v is not None:
        thr = _to_float(rule.get("value"))
        if thr is not None and temp_v >= thr:
            reasons.append(f"Температура {temp_v} ≥ {thr} °C")

    return reasons


class SoundAlarm:
    """Фоновый «дин-дон» раз в несколько секунд, пока активна авария и включён звук.

    Негромкий двухтональный сигнал (не сирена). Управляется флагами active/enabled.
    """

    GAP = 6.0   # пауза между сигналами, сек

    def __init__(self):
        self._active = False
        self._enabled = True
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self._wake.set()

    def set_active(self, active):
        active = bool(active)
        if active != self._active:
            self._active = active
            self._wake.set()

    def test(self):
        """Проиграть сигнал один раз (для кнопки «Проверить звук»)."""
        threading.Thread(target=self._chime, daemon=True).start()

    def _chime(self):
        if winsound is None:
            return
        try:
            winsound.Beep(660, 180)
            time.sleep(0.05)
            winsound.Beep(880, 220)
        except Exception:
            pass

    def _run(self):
        while not self._stop.is_set():
            if self._active and self._enabled:
                self._chime()
                self._wake.wait(timeout=self.GAP)
            else:
                self._wake.wait(timeout=30.0)
            self._wake.clear()
