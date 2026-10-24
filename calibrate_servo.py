#!/usr/bin/env python3
"""Interactive calibration of the servo connected to physical pin 15."""
import signal
import time
import tkinter as tk
from tkinter import messagebox, ttk

from servo_calibration import (
    CALIBRATION_PATH, Calibration, load_calibration, save_calibration,
)
from servo_control import ServoController


class CalibrationWindow:
    def __init__(self, root, controller_factory=None):
        self.root = root
        self.controller_factory = controller_factory or (lambda: ServoController(use_saved_calibration=False))
        self.controller = None
        self.current = self.target = 1500
        self.last_interaction = time.monotonic()
        self.endpoint_min = self.endpoint_max = None
        self.margin = tk.StringVar(value='50')
        self.travel = tk.StringVar(value='180')
        self.measured = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Сигнал выключен. Нажми «Включить: 1500 мкс».')
        self.pulse_text = tk.StringVar(value='1500 мкс — нейтраль')
        self.limits_text = tk.StringVar(value='Границы ещё не записаны')
        root.title('Калибровка сервы — пин 15')
        root.geometry('820x620')
        root.minsize(760, 600)
        root.protocol('WM_DELETE_WINDOW', self.close)
        panel = ttk.Frame(root, padding=20)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='Калибровка сервы', font=('Sans', 20, 'bold')).pack(anchor='w')
        ttk.Label(panel, text=(
            'Подводи к границам мелкими шагами. При упоре или усилении гудения сразу отступи.\n'
            'Не держи вал в упоре. Ползунок задаёт импульс, а не измеряет положение.'
        ), wraplength=760).pack(anchor='w', pady=(8, 14))
        actions = ttk.Frame(panel)
        actions.pack(fill='x')
        self.start_button = ttk.Button(actions, text='Включить: 1500 мкс', command=self.start)
        self.start_button.pack(side='left')
        ttk.Button(actions, text='К нейтрали', command=lambda: self.set_target(1500)).pack(side='left', padx=8)
        tk.Button(actions, text='СТОП — Esc / Пробел', command=self.stop,
                  bg='#b42318', fg='white', activebackground='#912018',
                  font=('Sans', 12, 'bold')).pack(side='right')
        ttk.Label(panel, textvariable=self.pulse_text, font=('Sans', 20)).pack(pady=(16, 4))
        self.scale = tk.Scale(panel, from_=500, to=2500, resolution=1, orient='horizontal',
                              command=self.on_slider, showvalue=False, length=740)
        self.scale.set(1500)
        self.scale.pack(fill='x')
        self.scale.configure(state='disabled')
        ttk.Label(panel, text='← / →: 5 мкс     Shift + ← / →: 25 мкс     Esc или Пробел: отключить PWM').pack()
        steps = ttk.Frame(panel)
        steps.pack(pady=8)
        for label, delta in (('−25 мкс', -25), ('−5 мкс', -5), ('+5 мкс', 5), ('+25 мкс', 25)):
            ttk.Button(steps, text=label, command=lambda d=delta: self.nudge(d)).pack(side='left', padx=4)
        records = ttk.Frame(panel)
        records.pack(fill='x', pady=(8, 4))
        ttk.Button(records, text='Записать нижнюю границу', command=lambda: self.record('min')).pack(side='left')
        ttk.Button(records, text='Записать верхнюю границу', command=lambda: self.record('max')).pack(side='right')
        ttk.Label(panel, textvariable=self.limits_text).pack(anchor='w', pady=4)
        settings = ttk.Frame(panel)
        settings.pack(fill='x', pady=8)
        ttk.Label(settings, text='Запас от каждой границы, мкс:').grid(row=0, column=0, sticky='w')
        ttk.Spinbox(settings, from_=0, to=200, increment=5, textvariable=self.margin, width=7).grid(row=0, column=1, padx=8)
        ttk.Checkbutton(settings, text='Полезный ход измерен транспортиром', variable=self.measured).grid(row=1, column=0, sticky='w', pady=8)
        ttk.Entry(settings, textvariable=self.travel, width=7).grid(row=1, column=1, padx=8)
        ttk.Label(settings, text='градусов; иначе шкала условная 0–180').grid(row=1, column=2, sticky='w')
        ttk.Button(panel, text='Сохранить калибровку и выключить сигнал', command=self.save).pack(fill='x', pady=8)
        ttk.Label(panel, textvariable=self.status, wraplength=760).pack(anchor='w', pady=6)
        ttk.Label(panel, text='Без действий 30 секунд — PWM отключится. При закрытии окна — тоже.',
                  wraplength=760).pack(anchor='w')
        # Handle safety keys before native Scale/Button bindings. In particular,
        # Space must stop PWM even when the start button currently has focus.
        safety_tag = f'ServoCalibrationSafety{id(self)}'
        def tag_widgets(widget):
            widget.bindtags((safety_tag,) + widget.bindtags())
            for child in widget.winfo_children():
                tag_widgets(child)
        tag_widgets(root)
        for event, delta in (('<Left>', -5), ('<Right>', 5), ('<Shift-Left>', -25), ('<Shift-Right>', 25)):
            root.bind_class(safety_tag, event, lambda e, d=delta: self.on_key(e, d))
        root.bind_class(safety_tag, '<Escape>', lambda e: self.stop_key())
        root.bind_class(safety_tag, '<space>', lambda e: self.stop_key())
        try:
            if CALIBRATION_PATH.exists():
                saved = load_calibration()
                self.endpoint_min, self.endpoint_max = saved.endpoint_min_us, saved.endpoint_max_us
                self.margin.set(f'{saved.margin_us:g}')
                self.travel.set(f'{saved.travel_degrees:g}')
                self.measured.set(saved.angle_measured)
                self.update_limits()
        except (OSError, ValueError, TypeError) as error:
            self.status.set(f'Предыдущая калибровка не загружена: {error}')
        self.timer = root.after(20, self.tick)

    def start(self):
        if self.controller is not None:
            return
        controller = None
        try:
            controller = self.controller_factory().__enter__()
            controller.set_pulse_us(1500)
            self.controller = controller
            self.current = self.target = 1500
            self.scale.configure(state='normal')
            self.scale.set(1500)
            self.start_button.configure(state='disabled')
            self.last_interaction = time.monotonic()
            self.status.set('PWM включён. Подводи к границе и записывай значение; не дави в упор.')
        except Exception as error:
            if controller is not None:
                controller.__exit__(None, None, None)
            messagebox.showerror('Не удалось включить PWM', f'{error}\n\nОстанови другие скрипты сервы и повтори.', parent=self.root)

    def stop(self, text='Сигнал выключен.'):
        controller, self.controller = self.controller, None
        try:
            if controller is not None:
                controller.__exit__(None, None, None)
        except Exception as error:
            text = f'Ошибка отключения PWM: {error}. Отключи питание сервы.'
        self.scale.configure(state='disabled')
        self.start_button.configure(state='normal')
        self.status.set(text)

    def stop_key(self):
        self.stop()
        return 'break'

    def on_key(self, event, delta):
        if event.widget.winfo_class() not in ('Entry', 'TEntry', 'Spinbox', 'TSpinbox'):
            self.nudge(delta)
            return 'break'

    def on_slider(self, value):
        if self.controller is not None:
            self.target = max(500, min(2500, round(float(value))))
            self.last_interaction = time.monotonic()

    def set_target(self, value):
        if self.controller is not None:
            self.target = max(500, min(2500, round(value)))
            self.scale.set(self.target)
            self.last_interaction = time.monotonic()

    def nudge(self, delta):
        self.set_target(self.target + delta)

    def tick(self):
        if self.controller is not None:
            if time.monotonic() - self.last_interaction > 30:
                self.stop('PWM отключён: 30 секунд без действий.')
            elif self.current != self.target:
                # Bound slider jumps to 10 us per 20 ms instead of abrupt endpoints.
                self.current += max(-10, min(10, self.target - self.current))
                try:
                    self.controller.set_pulse_us(self.current)
                except Exception as error:
                    self.stop(f'Ошибка PWM: {error}')
            self.pulse_text.set(f'Подано: {self.current:.0f} мкс    Цель: {self.target:.0f} мкс')
        self.timer = self.root.after(20, self.tick)

    def record(self, side):
        if self.controller is None:
            self.status.set('Сначала включи PWM и подведи серву к нужной границе.')
            return
        if self.current != self.target:
            self.status.set('Дождись, пока поданное значение достигнет цели.')
            return
        try:
            margin = float(self.margin.get())
            if not 0 <= margin <= 200:
                raise ValueError('Запас должен быть от 0 до 200 мкс.')
            if side == 'min':
                if self.current + margin >= 1500:
                    raise ValueError('Нижняя граница с запасом должна быть ниже 1500 мкс.')
                self.endpoint_min = self.current
                retreat = self.current + margin
            else:
                if self.current - margin <= 1500:
                    raise ValueError('Верхняя граница с запасом должна быть выше 1500 мкс.')
                self.endpoint_max = self.current
                retreat = self.current - margin
            self.set_target(retreat)
            self.update_limits()
            self.status.set('Граница записана. Серва отступает внутрь диапазона на заданный запас.')
        except ValueError as error:
            messagebox.showerror('Граница не записана', str(error), parent=self.root)

    def update_limits(self):
        low = '—' if self.endpoint_min is None else f'{self.endpoint_min:g}'
        high = '—' if self.endpoint_max is None else f'{self.endpoint_max:g}'
        self.limits_text.set(f'Записано: нижняя {low} мкс; верхняя {high} мкс. Запас применяется при сохранении.')

    def save(self):
        try:
            if self.endpoint_min is None or self.endpoint_max is None:
                raise ValueError('Сначала запиши обе границы.')
            result = Calibration(self.endpoint_min, self.endpoint_max, float(self.margin.get()),
                                 float(self.travel.get()) if self.measured.get() else 180,
                                 self.measured.get())
            save_calibration(result)
            self.stop(f'Сохранено: {result.min_pulse_us:g}–{result.max_pulse_us:g} мкс. '
                      'Перезапусти ярлык прохода сервы — он прочитает новую калибровку.')
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror('Калибровка не сохранена', str(error), parent=self.root)

    def close(self):
        self.root.after_cancel(self.timer)
        self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    window = CalibrationWindow(root)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: window.close())
    root.mainloop()


if __name__ == '__main__':
    main()
