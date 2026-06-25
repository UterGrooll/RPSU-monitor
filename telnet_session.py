"""Telnet-обмен с устройством поверх «сырого» TCP-сокета.

Устройства Nateks MGS-4 — это по сути текстовый обмен по TCP с минимальным
telnet-протоколом. Асинхронный telnetlib3 с ними не подключался, поэтому
используем обычный сокет и сами отвечаем отказом на telnet-опции (как это делал
старый telnetlib, который удалён из Python 3.13). Без сторонних зависимостей.

Интерфейс TelnetSession (write / read_available / close) не менялся — остальной
код (send_command, monitoring) работает как прежде.
"""
import socket
import time

from applog import log

# telnet-команды (IAC = Interpret As Command)
IAC, SE, SB = 255, 240, 250
WILL, WONT, DO, DONT = 251, 252, 253, 254


def _process_iac(raw):
    """Разбирает telnet-поток: отвечает отказом на DO/WILL, вырезает команды.
    Возвращает (чистые_данные: bytes, ответ_для_отправки: bytes)."""
    data = bytearray()
    reply = bytearray()
    i, n = 0, len(raw)
    while i < n:
        b = raw[i]
        if b != IAC:
            data.append(b)
            i += 1
            continue
        if i + 1 >= n:
            break  # обрыв на IAC — отбрасываем хвост
        cmd = raw[i + 1]
        if cmd == IAC:                      # экранированный 0xFF как данные
            data.append(IAC)
            i += 2
        elif cmd in (DO, DONT, WILL, WONT):
            if i + 2 >= n:
                break
            opt = raw[i + 2]
            if cmd == DO:                   # «сделай X» → «не буду»
                reply += bytes((IAC, WONT, opt))
            elif cmd == WILL:               # «я буду X» → «не надо»
                reply += bytes((IAC, DONT, opt))
            i += 3
        elif cmd == SB:                     # подпеременная: пропускаем до IAC SE
            j = i + 2
            while j + 1 < n and not (raw[j] == IAC and raw[j + 1] == SE):
                j += 1
            i = j + 2
        else:                               # прочие 2-байтовые команды (GA, NOP…)
            i += 2
    return bytes(data), bytes(reply)


class TelnetSession:
    """Синхронный telnet-обмен поверх сокета."""

    def __init__(self, sock):
        self._sock = sock

    @classmethod
    def connect(cls, ip, port, timeout=5):
        sock = socket.create_connection((ip, port), timeout=timeout)
        return cls(sock)

    def write(self, data):
        self._sock.sendall(data.encode("ascii", errors="ignore"))

    def read_available(self, idle=0.3):
        """Читает всё, что приходит, пока не наступит пауза `idle` секунд.
        Telnet-опции (IAC) обрабатываются: на DO/WILL отвечаем отказом, сами
        команды вырезаются из данных."""
        self._sock.settimeout(idle)
        raw = bytearray()
        while True:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                break
            except OSError:
                break
            if not chunk:  # соединение закрыто
                break
            raw += chunk
        data, reply = _process_iac(bytes(raw))
        if reply:
            try:
                self._sock.sendall(reply)
            except OSError:
                pass
        return data.decode("ascii", errors="ignore")

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


def connect_to_device(ip, port):
    try:
        return TelnetSession.connect(ip, port, timeout=5)
    except Exception as e:
        log(f"[{ip}:{port}] подключение не удалось: {type(e).__name__}: {e}")
        return None


def send_command(tn, command, delay=1):
    try:
        tn.write(command + "\r\n")
        time.sleep(delay)
        return tn.read_available()
    except Exception as e:
        log(f"Команда '{command}' не выполнена: {e}")
        return ""
