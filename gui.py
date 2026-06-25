"""Графический интерфейс и оркестрация: класс App.

App хранит всё состояние приложения (устройства, интервал, тема, потоки опроса)
в полях экземпляра. UI на tkinter/ttk со шрифтом Segoe UI. Поддержаны две темы:
светлая (нативная Windows) и тёмная (тема ttk «clam» с перекраской).
"""
import csv
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk, filedialog

import pystray
from PIL import Image, ImageDraw

import storage
import autostart
import alarm
import chart
from monitoring import DeviceWidgets, monitor_device

APP_VERSION = "0.3"

FONT_TITLE = ("Segoe UI", 11, "bold")
FONT_LABEL = ("Segoe UI", 9)
FONT_VALUE = ("Segoe UI", 9, "bold")
FONT_HELP = ("Segoe UI", 10)
FONT_H = ("Segoe UI", 12, "bold")

THEMES = {
    "light": {
        "ttk": "vista",
        "bg": "#f0f0f0",
        "card": "#ffffff",
        "border": "#d9d9d9",
        "text": "#1a1a1a",
        "muted": "#6b6b6b",
        "sep": "#e3e3e3",
        "help_bg": "#fbfbfb",
        "zebra": "#f5f5f5",
        "alarm_bg": "#fbe7e7",
        "ok": "#1a7f37",
        "err": "#c0392b",
        "warn": "#d97706",
    },
    "dark": {
        "ttk": "clam",
        "bg": "#1f2126",
        "card": "#2a2d34",
        "border": "#3a3e46",
        "text": "#e6e6e6",
        "muted": "#9aa0a6",
        "sep": "#3a3e46",
        "help_bg": "#23262c",
        "zebra": "#262931",
        "alarm_bg": "#3a2a2c",
        "ok": "#3fb950",
        "err": "#f06a5a",
        "warn": "#e0a030",
    },
}

HELP_TEXT = (
    "Программа опрашивает блоки дистанционного питания (RPSU) оборудования "
    "MGS-4 по Telnet и сохраняет параметры.\n\n"
    "Вкладка «Главная» — карточки устройств с текущими значениями. "
    "Кнопки «Журнал» (таблица) и «График» (тренды по выбранным параметрам).\n\n"
    "Вкладка «Параметры»:\n"
    "   •  Добавить устройство — IP и имя (до 5 штук).\n"
    "   •  Интервал опроса — 1…60 минут, кнопка «Применить».\n"
    "   •  UTC-журнал для SCADA — отдельный CSV в указанной папке.\n"
    "   •  Автозапуск и тема оформления.\n\n"
    "Вкладка «Сигнализация» — звуковое оповещение по условиям (ток утечки, "
    "температура, авария ДП, падение напряжения/тока). Аварийная карточка "
    "обводится красным.\n\n"
    "Иконки на карточке:  ⚙ — редактировать,  ✕ — удалить.\n"
    "Температура выше 40 °C подсвечивается оранжевым.\n\n"
    "Где хранятся данные:\n"
    "   •  Логи и настройки — C:\\ProgramData\\RPSU Monitor\n"
    "   •  SCADA-CSV — папка, заданная в «Параметрах».\n\n"
    "Закрытие окна — подтверждение выхода; сворачивание — в системный трей.\n\n"
    f"Версия {APP_VERSION} (2026)  ·  UterGrooll"
)


class App:
    MAX_DEVICES = 5

    def __init__(self):
        self.devices = []
        self.polling_interval = 60        # в минутах
        self.window = None
        self.utc_enabled = None
        self.main_frame = None
        self.monitor_stop_events = []     # сигналы остановки активных потоков опроса
        self.scada_csv_dir = ""           # папка для SCADA-CSV (пусто → в папку данных)
        self.scada_dir_var = None         # tk-переменная поля пути в GUI
        self.theme = "light"
        self.colors = THEMES["light"]
        self.style = None
        self.dark_mode = None             # tk.BooleanVar
        self.autostart_var = None         # tk.BooleanVar
        self.alarm_cfg = dict(storage.DEFAULT_CONFIG["alarm"])
        self.sound_alarm = None           # alarm.SoundAlarm
        self.alarm_vars = {}              # tk-переменные вкладки «Сигнализация»
        self.device_alarms = {}           # имя устройства -> список причин аварии
        self.device_cards = {}            # имя устройства -> tk.Frame карточки
        self.device_values = {}           # имя устройства -> (status, voltage, current, leak, temp)

    def run(self):
        self.create_gui()
        self.window.mainloop()

    def save_config(self):
        """Сохраняет текущее состояние (устройства, интервал, UTC, папка SCADA, тема)."""
        storage.save_config({
            "devices": self.devices,
            "polling_interval": self.polling_interval,
            "utc_enabled": bool(self.utc_enabled.get()) if self.utc_enabled else False,
            "scada_csv_dir": self.scada_csv_dir,
            "theme": self.theme,
            "alarm": self.alarm_cfg,
        })

    def _status_color(self, text):
        t = (text or "").strip().lower()
        c = self.colors
        if t == "on":
            return c["ok"]
        if t in ("авария", "ошибка", "off"):
            return c["err"]
        if t == "нет rpsu":
            return c["warn"]
        if t in ("нет связи", "нет данных", ""):
            return c["muted"]
        return c["text"]

    # ------------------------------------------------------------------
    # Сигнализация
    # ------------------------------------------------------------------
    def report_values(self, name, values):
        """Из потока опроса: сохранить последние значения устройства и пересчитать
        аварию. values = (status, voltage, current, leak, temp) или None (нет данных)."""
        self.device_values[name] = values
        self._reeval_device(name)

    def _reeval_device(self, name):
        """Пересчитывает аварию устройства по текущим порогам и последним значениям.
        Вызывается и из опроса, и сразу при изменении настроек сигнализации."""
        values = self.device_values.get(name)
        if not values:
            reasons = []
        else:
            status, voltage, current, leak, temp = values
            reasons = alarm.evaluate(status, voltage, current, leak, temp, self.alarm_cfg.get("rules"))
        self.device_alarms[name] = reasons
        if self.sound_alarm is not None:
            self.sound_alarm.set_active(any(self.device_alarms.values()))
        card = self.device_cards.get(name)
        if card is not None and self.window is not None:
            try:
                self.window.after(0, lambda c=card, a=bool(reasons): self._set_card_alarm(c, a))
            except Exception:
                pass

    def _set_card_alarm(self, card, active):
        try:
            card.config(highlightthickness=2 if active else 0)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Операции с устройствами
    # ------------------------------------------------------------------
    def add_device(self, ip_entry, name_entry, status_label):
        ip = ip_entry.get().strip()
        name = name_entry.get().strip()
        if len(self.devices) >= self.MAX_DEVICES:
            status_label.config(text=f"Максимум {self.MAX_DEVICES} устройств!", fg=self.colors["err"])
            return
        if not ip or not name:
            status_label.config(text="IP и имя обязательны!", fg=self.colors["err"])
            return
        self.devices.append({"ip": ip, "name": name, "port": 23})
        self.save_config()
        status_label.config(text=f"Добавлено: {name}", fg=self.colors["ok"])
        ip_entry.delete(0, tk.END)
        name_entry.delete(0, tk.END)
        self.update_main_window()

    def delete_device(self, name):
        self.devices = [d for d in self.devices if d["name"] != name]
        self.save_config()
        self.update_main_window()

    def edit_device(self, old_name, new_ip, new_name):
        for d in self.devices:
            if d["name"] == old_name:
                d["ip"] = new_ip
                d["name"] = new_name
                break
        self.save_config()
        self.update_main_window()

    def browse_scada_dir(self):
        chosen = filedialog.askdirectory(
            title="Папка для SCADA CSV",
            initialdir=self.scada_csv_dir or None,
        )
        if chosen:
            self.scada_csv_dir = chosen
            if self.scada_dir_var is not None:
                self.scada_dir_var.set(chosen)
            self.save_config()

    # ------------------------------------------------------------------
    # Вспомогательные окна / трей
    # ------------------------------------------------------------------
    JOURNAL_LIMIT = 5000   # сколько последних записей показывать (для скорости)

    def _read_journal_rows(self, device_name):
        """Строки журнала устройства без заголовка (или пустой список)."""
        try:
            with open(storage.log_path(device_name), 'r', encoding='utf-8') as f:
                data = list(csv.reader(f, delimiter=';'))
            return data[1:] if data else []
        except FileNotFoundError:
            return []

    def show_chart(self, device_name):
        rows = self._read_journal_rows(device_name)
        win = tk.Toplevel()
        win.title(f"График — {device_name}")
        win.geometry("920x520")
        win.configure(bg=self.colors["bg"])
        ttk.Label(win, text=device_name, font=FONT_H).pack(anchor="w", padx=14, pady=(10, 0))
        if not rows:
            ttk.Label(win, text="Нет данных для графика — журнал пуст.",
                      foreground=self.colors["muted"]).pack(pady=30)
            return
        chart.TrendChart(win, rows[-10000:], self.colors).pack(fill="both", expand=True)

    def show_debug_log(self, device_name):
        c = self.colors
        win = tk.Toplevel()
        win.title(f"Журнал — {device_name}")
        win.geometry("840x470")
        win.configure(bg=c["bg"])

        rows = self._read_journal_rows(device_name)

        # шапка: имя + счётчик
        top = ttk.Frame(win, padding=(14, 10, 14, 6))
        top.pack(fill="x")
        ttk.Label(top, text=device_name, font=FONT_H).pack(side="left")
        shown = min(len(rows), self.JOURNAL_LIMIT)
        info = f"записей: {len(rows)}" + (f" (показаны последние {shown})" if len(rows) > shown else "")
        ttk.Label(top, text=info, foreground=c["muted"]).pack(side="right")

        if not rows:
            ttk.Label(win, text="Журнал пуст — данные появятся после первого опроса.",
                      foreground=c["muted"]).pack(pady=30)
            return

        # таблица
        columns = ("time", "status", "uptime", "voltage", "current", "leak", "temp")
        titles = ["Время", "Статус", "В работе, ч", "Напряжение, В", "Ток, мА", "Утечка, мА", "Темп., °C"]
        widths = [150, 80, 95, 115, 80, 90, 80]

        wrap = ttk.Frame(win)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        s = self.style
        s.configure("Journal.Treeview", background=c["card"], fieldbackground=c["card"],
                    foreground=c["text"], rowheight=23, borderwidth=0)
        s.configure("Journal.Treeview.Heading", font=("Segoe UI", 9, "bold"))
        s.map("Journal.Treeview", background=[("selected", c["sep"])], foreground=[("selected", c["text"])])

        tree = ttk.Treeview(wrap, columns=columns, show="headings", style="Journal.Treeview")
        for col, title, w in zip(columns, titles, widths):
            tree.heading(col, text=title)
            # «Время» — фиксированной ширины (по содержимому), тянутся числовые колонки
            tree.column(col, width=w, anchor=("w" if col == "time" else "center"), stretch=(col != "time"))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        tree.tag_configure("odd", background=c["card"])
        tree.tag_configure("even", background=c["zebra"])
        tree.tag_configure("alarm", background=c["alarm_bg"], foreground=c["err"])

        # новые записи — сверху
        for i, row in enumerate(reversed(rows[-self.JOURNAL_LIMIT:])):
            vals = (list(row) + [""] * 7)[:7]
            status = vals[1].strip().upper()
            tag = "alarm" if status not in ("ON", "1") else ("even" if i % 2 else "odd")
            tree.insert("", "end", values=vals, tags=(tag,))

    def create_tray_icon(self):
        def create_image():
            img = Image.new("RGB", (64, 64), "white")
            dc = ImageDraw.Draw(img)
            dc.rectangle([16, 16, 48, 48], outline="black", fill="#185fa5")
            return img

        def restore(icon, item):
            icon.stop()
            self.window.deiconify()

        def exit_app(icon, item):
            icon.stop()
            self.window.quit()
            sys.exit()

        icon = pystray.Icon(
            "RPSU Monitor",
            create_image(),
            "RPSU Monitor",
            pystray.Menu(
                pystray.MenuItem("Открыть", restore),
                pystray.MenuItem("Выход", exit_app)
            )
        )
        icon.run()

    def open_edit_window(self, device):
        win = tk.Toplevel()
        win.title(f"Редактировать: {device['name']}")
        win.resizable(False, False)
        win.configure(bg=self.colors["bg"])
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="IP-адрес:").grid(row=0, column=0, sticky="e", padx=6, pady=6)
        ip_e = ttk.Entry(frm, width=22)
        ip_e.insert(0, device["ip"])
        ip_e.grid(row=0, column=1, padx=6, pady=6)
        ttk.Label(frm, text="Имя:").grid(row=1, column=0, sticky="e", padx=6, pady=6)
        name_e = ttk.Entry(frm, width=22)
        name_e.insert(0, device["name"])
        name_e.grid(row=1, column=1, padx=6, pady=6)

        def save():
            ip, name = ip_e.get().strip(), name_e.get().strip()
            if ip and name:
                self.edit_device(device["name"], ip, name)
                win.destroy()
            else:
                messagebox.showerror("Ошибка", "Заполните оба поля!")
        ttk.Button(frm, text="Сохранить", command=save).grid(row=2, column=0, columnspan=2, pady=(10, 0))

    # ------------------------------------------------------------------
    # Главная вкладка: карточки устройств
    # ------------------------------------------------------------------
    def _build_device_card(self, parent, col, device):
        c = self.colors
        card = tk.Frame(parent, bg=c["card"], bd=1, relief="solid",
                        highlightbackground=c["err"], highlightcolor=c["err"], highlightthickness=0)
        card.grid(row=0, column=col, padx=9, pady=4, sticky="n")
        card.columnconfigure(0, minsize=120)
        card.columnconfigure(1, minsize=95)
        self.device_cards[device["name"]] = card
        if self.device_alarms.get(device["name"]):
            self._set_card_alarm(card, True)

        header = tk.Frame(card, bg=c["card"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 0))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text=device["name"], font=FONT_TITLE, bg=c["card"], fg=c["text"], anchor="w").grid(row=0, column=0, sticky="w")
        gear = tk.Label(header, text="⚙", font=("Segoe UI", 12), bg=c["card"], fg=c["muted"], cursor="hand2")
        cross = tk.Label(header, text="✕", font=("Segoe UI", 11), bg=c["card"], fg=c["err"], cursor="hand2")
        gear.grid(row=0, column=1, padx=(8, 0))
        cross.grid(row=0, column=2, padx=(8, 0))
        gear.bind("<Button-1>", lambda e, d=device: self.open_edit_window(d))
        cross.bind("<Button-1>", lambda e, n=device["name"]: self.delete_device(n))

        tk.Label(card, text=device["ip"], font=FONT_LABEL, bg=c["card"], fg=c["muted"], anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=12)
        tk.Frame(card, height=1, bg=c["sep"]).grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(7, 5))

        status_var = tk.StringVar()
        uptime_var = tk.StringVar()
        voltage_var = tk.StringVar()
        current_var = tk.StringVar()
        leak_var = tk.StringVar()
        temp_var = tk.StringVar()

        s, u, v, cc, l, t = storage.get_last_data_from_csv(device["name"])
        status_var.set("Авария" if s == "OFF" else s or "Нет данных")
        uptime_var.set(u or "—")
        voltage_var.set(v or "—")
        current_var.set(cc or "—")
        leak_var.set(l or "—")
        temp_var.set(t or "0.0")

        rows = [
            ("Статус ДП", status_var),
            ("В работе, ч", uptime_var),
            ("Напряжение, В", voltage_var),
            ("Ток, мА", current_var),
            ("Ток утечки, мА", leak_var),
            ("Температура, °C", temp_var),
        ]
        status_label = temp_label = None
        r = 3
        for lbl, var in rows:
            tk.Label(card, text=lbl, font=FONT_LABEL, bg=c["card"], fg=c["muted"], anchor="w").grid(
                row=r, column=0, sticky="w", padx=(12, 6), pady=2)
            val = tk.Label(card, textvariable=var, font=FONT_VALUE, bg=c["card"], fg=c["text"], anchor="e")
            val.grid(row=r, column=1, sticky="e", padx=(6, 12), pady=2)
            if lbl == "Статус ДП":
                status_label = val
            elif lbl == "Температура, °C":
                temp_label = val
            r += 1

        def _recolor(*_, var=status_var, lbl=status_label):
            try:
                lbl.config(fg=self._status_color(var.get()))
            except Exception:
                pass
        status_var.trace_add("write", _recolor)
        _recolor()

        btns = tk.Frame(card, bg=c["card"])
        btns.grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=(8, 12))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        ttk.Button(btns, text="Журнал", command=lambda n=device["name"]: self.show_debug_log(n)).grid(
            row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(btns, text="График", command=lambda n=device["name"]: self.show_chart(n)).grid(
            row=0, column=1, sticky="ew", padx=(3, 0))

        if temp_label is not None:
            widgets = DeviceWidgets(
                status=status_var, uptime=uptime_var, voltage=voltage_var,
                current=current_var, leak=leak_var, temperature=temp_var, temp_label=temp_label,
            )
            stop_event = threading.Event()
            self.monitor_stop_events.append(stop_event)
            threading.Thread(target=monitor_device, args=(self, device, widgets, stop_event), daemon=True).start()

    def update_main_window(self):
        # Останавливаем прежние потоки опроса, чтобы не плодить дубликаты.
        for ev in self.monitor_stop_events:
            ev.set()
        self.monitor_stop_events = []
        self.device_cards = {}

        for w in self.main_frame.winfo_children():
            w.destroy()

        holder = tk.Frame(self.main_frame, bg=self.colors["bg"])
        holder.place(relx=0.5, rely=0.5, anchor="center")

        if not self.devices:
            tk.Label(holder, text="Нет устройств.\nДобавьте их на вкладке «Параметры».",
                     font=FONT_HELP, fg=self.colors["muted"], bg=self.colors["bg"], justify="center").pack(padx=40, pady=40)
        else:
            for i, device in enumerate(self.devices):
                self._build_device_card(holder, i, device)

        # чистим состояние аварий от удалённых устройств и пересчитываем звук
        names = {d["name"] for d in self.devices}
        self.device_alarms = {k: v for k, v in self.device_alarms.items() if k in names}
        self.device_values = {k: v for k, v in self.device_values.items() if k in names}
        if self.sound_alarm is not None:
            self.sound_alarm.set_active(any(self.device_alarms.values()))

        n = max(len(self.devices), 1)
        width = min(max(n * 262 + 70, 560), 1400)
        if self.window is not None:
            self.window.geometry(f"{width}x470")

    # ------------------------------------------------------------------
    # Вкладка «Параметры»
    # ------------------------------------------------------------------
    def _build_settings_tab(self, parent):
        wrap = ttk.Frame(parent, padding=16)
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=1, uniform="cols")
        wrap.columnconfigure(1, weight=1, uniform="cols")

        # --- Добавить устройство (слева вверху) ---
        g1 = ttk.LabelFrame(wrap, text="Добавить устройство", padding=12)
        g1.grid(row=0, column=0, sticky="new", padx=(0, 8), pady=(0, 12))
        g1.columnconfigure(1, weight=1)
        ttk.Label(g1, text="IP-адрес:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ip_e = ttk.Entry(g1)
        ip_e.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(g1, text="Имя:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        name_e = ttk.Entry(g1)
        name_e.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        add_status = tk.Label(g1, text="", font=FONT_LABEL, bg=self.colors["bg"], fg=self.colors["text"])
        add_status.grid(row=2, column=0, columnspan=2, pady=(2, 6))
        ttk.Button(g1, text="➕  Добавить",
                   command=lambda: self.add_device(ip_e, name_e, add_status)).grid(row=3, column=0, columnspan=2)

        # --- Опрос (справа вверху) ---
        g2 = ttk.LabelFrame(wrap, text="Опрос", padding=12)
        g2.grid(row=0, column=1, sticky="new", padx=(8, 0), pady=(0, 12))
        ttk.Label(g2, text="Интервал, мин:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        combo = ttk.Combobox(g2, values=[1, 5, 10, 15, 30, 60], width=8, state="readonly")
        combo.set(self.polling_interval)
        combo.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        def apply_interval():
            try:
                self.polling_interval = int(combo.get())
                self.save_config()
                messagebox.showinfo("Готово", f"Интервал опроса: {self.polling_interval} мин")
            except Exception:
                pass
        ttk.Button(g2, text="Применить", command=apply_interval).grid(row=1, column=0, columnspan=2, pady=(8, 0))

        # --- Журнал для SCADA (слева внизу) ---
        g3 = ttk.LabelFrame(wrap, text="Журнал для SCADA", padding=12)
        g3.grid(row=1, column=0, sticky="new", padx=(0, 8))
        g3.columnconfigure(1, weight=1)
        ttk.Checkbutton(g3, text="Писать UTC-журнал для SCADA", variable=self.utc_enabled,
                        command=self.save_config).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(g3, text="Папка:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(g3, textvariable=self.scada_dir_var, state="readonly").grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(g3, text="Обзор…", command=self.browse_scada_dir).grid(row=1, column=2, padx=6)
        ttk.Label(g3, text="Пусто → рядом с логами в ProgramData.", foreground=self.colors["muted"]).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # --- Запуск и оформление (справа внизу) ---
        g4 = ttk.LabelFrame(wrap, text="Запуск и оформление", padding=12)
        g4.grid(row=1, column=1, sticky="new", padx=(8, 0))
        ttk.Checkbutton(g4, text="Автозапуск с Windows", variable=self.autostart_var,
                        command=self.toggle_autostart).grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Checkbutton(g4, text="Тёмная тема", variable=self.dark_mode,
                        command=self.toggle_theme).grid(row=1, column=0, sticky="w")

    def toggle_autostart(self):
        try:
            autostart.set_autostart(self.autostart_var.get())
        except Exception as e:
            messagebox.showerror("Автозапуск", f"Не удалось изменить автозапуск:\n{e}")
            self.autostart_var.set(autostart.autostart_enabled())

    # ------------------------------------------------------------------
    # Вкладка «Сигнализация»
    # ------------------------------------------------------------------
    ALARM_KEYS = ("status_off", "leak_high", "temp_high")

    def _make_alarm_vars(self):
        rules = self.alarm_cfg.get("rules", {})
        v = {"sound": tk.BooleanVar(value=self.alarm_cfg.get("sound", True))}
        for key in self.ALARM_KEYS:
            r = rules.get(key, {})
            entry = {"on": tk.BooleanVar(value=bool(r.get("on")))}
            if key != "status_off":
                entry["value"] = tk.StringVar(value=str(r.get("value", "")))
            v[key] = entry
        return v

    def _save_alarm(self):
        rules = {}
        for key in self.ALARM_KEYS:
            v = self.alarm_vars[key]
            rule = {"on": bool(v["on"].get())}
            if "value" in v:
                try:
                    rule["value"] = float(str(v["value"].get()).replace(",", "."))
                except (TypeError, ValueError):
                    rule["value"] = self.alarm_cfg.get("rules", {}).get(key, {}).get("value", 0)
                    v["value"].set(rule["value"])
            rules[key] = rule
        self.alarm_cfg = {"sound": bool(self.alarm_vars["sound"].get()), "rules": rules}
        if self.sound_alarm is not None:
            self.sound_alarm.set_enabled(self.alarm_cfg["sound"])
        self.save_config()
        # мгновенно пересчитываем аварии по новым порогам — не ждём опроса
        for name in list(self.device_values.keys()):
            self._reeval_device(name)

    def _build_alarm_tab(self, parent):
        c = self.colors
        wrap = ttk.Frame(parent, padding=16)
        wrap.pack(fill="both", expand=True)

        top = ttk.Frame(wrap)
        top.pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(top, text="Звуковая сигнализация", variable=self.alarm_vars["sound"],
                        command=self._save_alarm).pack(side="left")
        ttk.Button(top, text="Проверить звук",
                   command=lambda: self.sound_alarm and self.sound_alarm.test()).pack(side="left", padx=12)

        grp = ttk.LabelFrame(wrap, text="Условия (звук + красная рамка карточки)", padding=12)
        grp.pack(fill="x")
        grp.columnconfigure(3, weight=1)

        def add_row(r, key, prefix, has_value, unit, hint):
            ttk.Checkbutton(grp, text=prefix, variable=self.alarm_vars[key]["on"],
                            command=self._save_alarm).grid(row=r, column=0, sticky="w", pady=(4, 0))
            if has_value:
                e = ttk.Entry(grp, width=8, textvariable=self.alarm_vars[key]["value"])
                e.grid(row=r, column=1, sticky="w", padx=6, pady=(4, 0))
                e.bind("<FocusOut>", lambda ev: self._save_alarm())
                e.bind("<Return>", lambda ev: self._save_alarm())
                ttk.Label(grp, text=unit).grid(row=r, column=2, sticky="w", pady=(4, 0))
            if hint:
                ttk.Label(grp, text=hint, foreground=c["muted"]).grid(
                    row=r + 1, column=0, columnspan=4, sticky="w", pady=(0, 8))

        add_row(0, "status_off", "Авария ДП (статус OFF)", False, "", "Модуль ушёл в аварию и снял питание линии.")
        add_row(2, "leak_high", "Ток утечки ≥", True, "мА", "Паспорт: предупреждение ±0.1 мА, отключение ±1 мА.")
        add_row(4, "temp_high", "Температура ≥", True, "°C", "Защита платы по температуре — +80 °C.")

    def _build_help_tab(self, parent):
        c = self.colors
        ttk.Label(parent, text="RPSU Monitor — справка", font=FONT_H).pack(anchor="w", padx=16, pady=(14, 6))
        txt = scrolledtext.ScrolledText(parent, font=FONT_HELP, wrap="word", relief="flat",
                                        background=c["help_bg"], foreground=c["text"], insertbackground=c["text"])
        txt.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        txt.insert(tk.END, HELP_TEXT)
        txt.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Темы и сборка окна
    # ------------------------------------------------------------------
    def _apply_ttk_style(self):
        c = self.colors
        s = self.style
        s.theme_use(c["ttk"])
        if self.theme == "dark":
            s.configure(".", background=c["bg"], foreground=c["text"], fieldbackground=c["card"], bordercolor=c["border"])
            s.configure("TFrame", background=c["bg"])
            s.configure("TLabel", background=c["bg"], foreground=c["text"])
            s.configure("TLabelframe", background=c["bg"], bordercolor=c["border"])
            s.configure("TLabelframe.Label", background=c["bg"], foreground=c["muted"])
            s.configure("TButton", background=c["card"], foreground=c["text"], bordercolor=c["border"], focuscolor=c["bg"])
            s.map("TButton", background=[("active", c["sep"])])
            s.configure("TCheckbutton", background=c["bg"], foreground=c["text"])
            s.map("TCheckbutton", background=[("active", c["bg"])])
            s.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
            s.configure("TNotebook.Tab", background=c["card"], foreground=c["muted"], padding=(12, 6))
            s.map("TNotebook.Tab", background=[("selected", c["bg"])], foreground=[("selected", c["text"])])
            s.configure("TEntry", fieldbackground=c["card"], foreground=c["text"], bordercolor=c["border"], insertcolor=c["text"])
            s.configure("TCombobox", fieldbackground=c["card"], foreground=c["text"], background=c["card"],
                        bordercolor=c["border"], arrowcolor=c["text"])
            s.map("TCombobox", fieldbackground=[("readonly", c["card"])], foreground=[("readonly", c["text"])])
            # выпадающий список комбобокса
            self.window.option_add("*TCombobox*Listbox.background", c["card"])
            self.window.option_add("*TCombobox*Listbox.foreground", c["text"])
            self.window.option_add("*TCombobox*Listbox.selectBackground", c["sep"])

    def _build_content(self):
        """Собирает (или пересобирает при смене темы) содержимое окна."""
        # стоп старым потокам опроса до уничтожения карточек
        for ev in self.monitor_stop_events:
            ev.set()
        self.monitor_stop_events = []

        self.colors = THEMES[self.theme]
        self._apply_ttk_style()
        self.window.configure(bg=self.colors["bg"])
        for w in self.window.winfo_children():
            w.destroy()

        tabs = ttk.Notebook(self.window)
        main_tab = ttk.Frame(tabs)
        cfg_tab = ttk.Frame(tabs)
        alarm_tab = ttk.Frame(tabs)
        help_tab = ttk.Frame(tabs)
        tabs.add(main_tab, text="  Главная  ")
        tabs.add(cfg_tab, text="  Параметры  ")
        tabs.add(alarm_tab, text="  Сигнализация  ")
        tabs.add(help_tab, text="  Справка  ")
        tabs.pack(expand=1, fill="both", padx=8, pady=8)

        self.main_frame = tk.Frame(main_tab, bg=self.colors["bg"])
        self.main_frame.pack(fill="both", expand=True)

        self._build_settings_tab(cfg_tab)
        self._build_alarm_tab(alarm_tab)
        self._build_help_tab(help_tab)
        self.update_main_window()

    def toggle_theme(self):
        self.theme = "dark" if self.dark_mode.get() else "light"
        self.save_config()
        self._build_content()

    def _bind_window_events(self):
        self.window.is_minimized_to_tray = False

        def on_close():
            if messagebox.askyesno("Подтверждение выхода",
                                   "Завершить работу программы полностью?", parent=self.window):
                self.window.destroy()
                sys.exit()

        def on_minimize(event):
            self.window.after_idle(check_minimize)

        def check_minimize():
            if self.window.state() == 'iconic' and not self.window.is_minimized_to_tray:
                self.window.is_minimized_to_tray = True
                self.window.withdraw()
                threading.Thread(target=self.create_tray_icon, daemon=True).start()

        def on_restore(event):
            self.window.is_minimized_to_tray = False

        self.window.protocol("WM_DELETE_WINDOW", on_close)
        self.window.bind("<Unmap>", on_minimize)
        self.window.bind("<Map>", on_restore)

    def create_gui(self):
        cfg = storage.load_config()
        self.devices = cfg["devices"]
        self.polling_interval = cfg["polling_interval"]
        self.scada_csv_dir = cfg["scada_csv_dir"]
        self.alarm_cfg = cfg.get("alarm", dict(storage.DEFAULT_CONFIG["alarm"]))
        self.theme = cfg.get("theme", "light")
        if self.theme not in THEMES:
            self.theme = "light"

        self.window = tk.Tk()
        self.window.title(f"RPSU Monitor v{APP_VERSION}")
        self.window.geometry("780x470")
        self.window.minsize(560, 440)

        self.utc_enabled = tk.BooleanVar(value=cfg["utc_enabled"])
        self.scada_dir_var = tk.StringVar(value=self.scada_csv_dir)
        self.dark_mode = tk.BooleanVar(value=(self.theme == "dark"))
        self.autostart_var = tk.BooleanVar(value=autostart.autostart_enabled())
        self.sound_alarm = alarm.SoundAlarm()
        self.sound_alarm.set_enabled(self.alarm_cfg.get("sound", True))
        self.alarm_vars = self._make_alarm_vars()
        self.style = ttk.Style()

        self._bind_window_events()
        self._build_content()
