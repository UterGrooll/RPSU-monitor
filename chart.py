"""Простой график трендов по данным журнала — на чистом tkinter Canvas.

Без сторонних зависимостей. Время по оси X, значения по Y, разноцветные линии;
параметры включаются галочками (галочка окрашена в цвет своей линии — это и легенда).
Ось Y автоматически масштабируется под выбранные параметры.

CSV журнала: Timestamp;Status;Uptime;Voltage;Current;Leak Current;Temperature
"""
import tkinter as tk
from datetime import datetime

# (ключ, индекс столбца в CSV, подпись, цвет линии — читаемый и на светлом, и на тёмном)
PARAMS = [
    ("temp",    6, "Температура, °C", "#e24b4a"),
    ("voltage", 3, "Напряжение, В",   "#3b82f6"),
    ("current", 4, "Ток, мА",         "#22a565"),
    ("leak",    5, "Ток утечки, мА",  "#d97706"),
]


def _to_float(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


class TrendChart(tk.Frame):
    def __init__(self, master, rows, colors):
        super().__init__(master, bg=colors["bg"])
        self.colors = colors
        self.series = self._build_series(rows)
        self.vars = {}

        top = tk.Frame(self, bg=colors["bg"])
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, text="Показать:", bg=colors["bg"], fg=colors["muted"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        for key, _idx, label, color in PARAMS:
            var = tk.BooleanVar(value=(key == "temp"))   # по умолчанию — температура
            self.vars[key] = var
            tk.Checkbutton(top, text=label, variable=var, command=self.redraw,
                           fg=color, bg=colors["bg"], activebackground=colors["bg"],
                           activeforeground=color, selectcolor=colors["card"],
                           font=("Segoe UI", 9, "bold")).pack(side="left", padx=8)

        self.canvas = tk.Canvas(self, bg=colors["card"], highlightthickness=1,
                                highlightbackground=colors["border"])
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.canvas.bind("<Configure>", lambda e: self.redraw())

    def _build_series(self, rows):
        series = {key: [] for key, _, _, _ in PARAMS}
        for row in rows:
            if len(row) < 7:
                continue
            try:
                t = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            for key, idx, _, _ in PARAMS:
                v = _to_float(row[idx])
                if v is not None:
                    series[key].append((t, v))
        return series

    def redraw(self):
        c = self.canvas
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 60 or H < 60:
            return
        col = self.colors
        L, R, T, B = 62, 28, 14, 46
        pw, ph = W - L - R, H - T - B

        selected = [p for p in PARAMS if self.vars[p[0]].get()]
        pts = [pt for key, *_ in selected for pt in self.series[key]]
        if not selected or not pts:
            c.create_text(W // 2, H // 2, text="Нет данных для отображения",
                          fill=col["muted"], font=("Segoe UI", 10))
            return

        times = [t for t, _ in pts]
        vals = [v for _, v in pts]
        tmin, tmax = min(times), max(times)
        vmin, vmax = min(vals), max(vals)
        if vmax == vmin:
            vmax += 1
            vmin -= 1
        pad = (vmax - vmin) * 0.08
        vmin -= pad
        vmax += pad
        span = (tmax - tmin).total_seconds() or 1.0
        # дата показывается отдельной строкой под временем, как только данные
        # заходят на другой календарный день
        cross_day = tmin.date() != tmax.date()

        def X(t):
            return L + (t - tmin).total_seconds() / span * pw

        def Y(v):
            return T + ph - (v - vmin) / (vmax - vmin) * ph

        # сетка + подписи осей
        for i in range(6):
            yv = vmin + (vmax - vmin) * i / 5
            y = Y(yv)
            c.create_line(L, y, L + pw, y, fill=col["sep"])
            c.create_text(L - 6, y, text=f"{yv:.1f}", anchor="e", fill=col["muted"], font=("Segoe UI", 8))
            tt = tmin + (tmax - tmin) * i / 5
            x = X(tt)
            c.create_line(x, T, x, T + ph, fill=col["sep"])
            label = tt.strftime("%H:%M\n%d.%m") if cross_day else tt.strftime("%H:%M")
            c.create_text(x, T + ph + 5, text=label, anchor="n", justify="center",
                          fill=col["muted"], font=("Segoe UI", 8))
        c.create_rectangle(L, T, L + pw, T + ph, outline=col["border"])

        # линии параметров
        for key, _idx, _label, clr in selected:
            data = self.series[key]
            if len(data) == 1:
                t, v = data[0]
                c.create_oval(X(t) - 2, Y(v) - 2, X(t) + 2, Y(v) + 2, fill=clr, outline=clr)
            elif len(data) > 1:
                coords = []
                for t, v in data:
                    coords += [X(t), Y(v)]
                c.create_line(*coords, fill=clr, width=2)
