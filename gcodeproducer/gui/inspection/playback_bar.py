"""PlaybackBar — Preview transport shared by FDM and CAM."""
from __future__ import annotations
import time
from PyQt6.QtCore import QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSlider, QSpinBox, QVBoxLayout, QWidget
from gcodeproducer.gui.editors.widgets import small_button
from .inspection_constants import (TRANSPORT_BUTTONS, PLAY_ICON, PAUSE_ICON, PLAY_INTERVAL_MS,
                                   PLAY_SPEED_STEPS, PLAY_SPEED_DECADES, PLAY_SPEED_DEFAULT)


class PlaybackBar(QWidget):
    """Line cursor, layer range and timed playback of one G-code program.

    The bar owns the cursor (a program line index) and the visible layer range
    and reports them; the window applies them to the viewer, text panel and
    status line. It knows nothing about FDM or CAM: both use the same program
    and toolpath representation.
    """
    cursorChanged = pyqtSignal(int)          # line index
    layersChanged = pyqtSignal(int, int)     # lowest, highest visible layer

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = None
        self.tp = None
        self.cursor = 0
        self.layer_min = 0
        self.layer_max = 0
        self.play_speed = 1.0
        self._play_acc = 0.0
        self._play_t = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(PLAY_INTERVAL_MS)
        self.timer.timeout.connect(self._tick)

        self.line_slider = QSlider(Qt.Orientation.Horizontal)
        self.line_slider.setToolTip("Position in the whole program")
        self.line_slider.valueChanged.connect(lambda v: self.set_cursor(v))
        self.line_spin = QSpinBox()
        self.line_spin.setPrefix("line ")
        self.line_spin.setKeyboardTracking(False)
        self.line_spin.valueChanged.connect(lambda v: self.set_cursor(v-1))
        self.layer_line_slider = QSlider(Qt.Orientation.Horizontal)
        self.layer_line_slider.setToolTip("Position within the top visible layer")
        self.layer_line_slider.valueChanged.connect(lambda v: self.set_cursor(v, follow=False))
        self.layer_min_spin = QSpinBox()
        self.layer_min_spin.setPrefix("from ")
        self.layer_min_spin.setToolTip("Lowest visible layer")
        self.layer_min_spin.valueChanged.connect(self._on_layer_min)
        self.layer_max_spin = QSpinBox()
        self.layer_max_spin.setPrefix("to ")
        self.layer_max_spin.setToolTip("Highest visible layer")
        self.layer_max_spin.valueChanged.connect(lambda v: self.set_layer_max(v-1))
        self.single_layer = QCheckBox("Single layer")
        self.single_layer.setToolTip("Show only the top visible layer")
        self.single_layer.toggled.connect(lambda _on: self._apply_layers(update_cursor=False))
        self.follow_layer = QCheckBox("Follow")
        self.follow_layer.setChecked(True)
        self.follow_layer.setToolTip("The top visible layer follows the line cursor while scrubbing / playing")

        actions = {"start": lambda: self.set_cursor(0), "prev_layer": lambda: self.step_layer(-1),
                   "prev_line": lambda: self.step_line(-1), "play": self.toggle_play,
                   "next_line": lambda: self.step_line(1), "next_layer": lambda: self.step_layer(1),
                   "end": self.show_all}
        self.buttons = {}
        transport = QHBoxLayout()
        transport.setSpacing(2)
        for key, text, tip in TRANSPORT_BUTTONS:
            button = small_button(text, tip, 44 if key == "play" else 30)
            button.clicked.connect(actions[key])
            self.buttons[key] = button
            transport.addWidget(button)
        self.b_play = self.buttons["play"]
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(0, PLAY_SPEED_STEPS)
        self.speed_slider.setMinimumWidth(80)
        self.speed_slider.setMaximumWidth(180)
        self.speed_slider.setToolTip("Playback speed (logarithmic)")
        self.speed_slider.valueChanged.connect(self._on_speed)
        self.speed_lbl = QLabel()
        self.speed_lbl.setMinimumWidth(90)
        self.speed_slider.setValue(PLAY_SPEED_DEFAULT)
        self._on_speed(self.speed_slider.value())
        transport.addSpacing(8)
        transport.addWidget(QLabel("Speed"))
        transport.addWidget(self.speed_slider)
        transport.addWidget(self.speed_lbl)
        transport.addSpacing(8)
        transport.addWidget(QLabel("Line"))
        transport.addWidget(self.line_slider, 1)
        transport.addWidget(self.line_spin)

        layers = QHBoxLayout()
        self.lbl_in_layer = QLabel("In layer")
        layers.addWidget(self.lbl_in_layer)
        layers.addWidget(self.layer_line_slider, 1)
        layers.addSpacing(8)
        layers.addWidget(QLabel("Layers"))
        layers.addWidget(self.layer_min_spin)
        layers.addWidget(self.layer_max_spin)
        layers.addWidget(self.single_layer)
        layers.addWidget(self.follow_layer)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addLayout(transport)
        v.addLayout(layers)
        self.clear()

    # ----------------------------------------------------------------- program
    def clear(self):
        self.stop_play()
        self.program = self.tp = None
        self.cursor = self.layer_min = self.layer_max = 0
        for w in (self.line_slider, self.layer_line_slider):
            with QSignalBlocker(w):
                w.setRange(0, 0)
        for w in (self.line_spin, self.layer_min_spin, self.layer_max_spin):
            with QSignalBlocker(w):
                w.setRange(1, 1)
                w.setValue(1)

    def set_program(self, program, tp):
        """Show a new program in full, cursor at its end."""
        self.stop_play()
        self.program, self.tp = program, tp
        n = max(1, len(program.lines))
        layers = max(1, program.num_layers)
        with QSignalBlocker(self.line_slider):
            self.line_slider.setRange(0, n-1)
            self.line_slider.setPageStep(max(1, n//100))
        with QSignalBlocker(self.line_spin):
            self.line_spin.setRange(1, n)
        for spin in (self.layer_min_spin, self.layer_max_spin):
            with QSignalBlocker(spin):
                spin.setRange(1, layers)
        self.layer_min, self.layer_max = 0, layers-1
        with QSignalBlocker(self.layer_min_spin):
            self.layer_min_spin.setValue(1)
        self._apply_layers(update_cursor=False)
        self.set_cursor(n-1, follow=False)

    @property
    def last_layer(self):
        return max(0, (self.program.num_layers if self.program is not None else 1)-1)

    # ----------------------------------------------------------------- cursor
    def set_cursor(self, line, follow=True):
        if self.program is None or not len(self.program.lines):
            return
        line = max(0, min(len(self.program.lines)-1, int(line)))
        self.cursor = line
        with QSignalBlocker(self.line_slider):
            self.line_slider.setValue(line)
        with QSignalBlocker(self.line_spin):
            self.line_spin.setValue(line+1)
        layer = int(self.tp.line_layer[line]) if self.tp is not None and len(self.tp.line_layer) else 0
        if follow and self.follow_layer.isChecked() and layer != self.layer_max:
            self.layer_max = max(0, min(self.last_layer, layer))
            self._apply_layers(update_cursor=False)
        self._update_layer_line_slider()
        self.cursorChanged.emit(line)

    def _layer_range(self, layer):
        lo, hi = self.tp.layer_line_range(layer)
        if layer == self.last_layer:
            hi = len(self.program.lines)-1        # the top layer includes the end G-code
        return lo, max(lo, hi)

    def _update_layer_line_slider(self):
        if self.tp is None:
            return
        lo, hi = self._layer_range(self.layer_max)
        with QSignalBlocker(self.layer_line_slider):
            self.layer_line_slider.setRange(lo, hi)
            self.layer_line_slider.setValue(self.cursor)

    def step_line(self, direction):
        """Next / previous line that does something (comments and blank lines are skipped)."""
        if self.program is None:
            return
        line = self.cursor+direction
        lines = self.program.lines
        while 0 < line < len(lines)-1 and lines[line].cmd is None:
            line += direction
        self.set_cursor(line)

    # ----------------------------------------------------------------- layers
    def set_layer_max(self, layer, move_cursor=True):
        """Top visible layer (the vertical slider / PgUp / PgDn); the cursor goes to its end."""
        if self.program is None:
            return
        self.layer_max = max(0, min(self.last_layer, int(layer)))
        self._apply_layers(update_cursor=move_cursor)

    def step_layer(self, direction):
        self.set_layer_max(self.layer_max+direction)

    def show_all(self):
        if self.program is None:
            return
        self.layer_max = self.last_layer
        self._apply_layers(update_cursor=False)
        self.set_cursor(len(self.program.lines)-1, follow=False)

    def _on_layer_min(self, value):
        self.layer_min = value-1
        if self.layer_min > self.layer_max:
            self.layer_max = self.layer_min
        self._apply_layers(update_cursor=False)

    def _apply_layers(self, update_cursor=True):
        if self.program is None:
            return
        if self.single_layer.isChecked():
            low = self.layer_max
        else:
            low = min(self.layer_min_spin.value()-1, self.layer_max)
        self.layer_min = low
        with QSignalBlocker(self.layer_max_spin):
            self.layer_max_spin.setValue(self.layer_max+1)
        self.layersChanged.emit(self.layer_min, self.layer_max)
        if update_cursor and self.tp is not None and not self.timer.isActive():
            self.set_cursor(self._layer_range(self.layer_max)[1], follow=False)
        else:
            self._update_layer_line_slider()

    # ----------------------------------------------------------------- playback
    def is_playing(self):
        return self.timer.isActive()

    def _on_speed(self, value):
        self.play_speed = 10 ** (value/PLAY_SPEED_STEPS*PLAY_SPEED_DECADES)
        self.speed_lbl.setText(f"{self.play_speed:,.0f} lines/s")

    def toggle_play(self):
        if self.timer.isActive():
            self.stop_play()
            return
        if self.program is None or not len(self.program.lines):
            return
        if self.cursor >= len(self.program.lines)-1:
            self.set_cursor(0)                     # replay from the start
        self._play_acc = 0.0
        self._play_t = time.perf_counter()
        self.timer.start()
        self.b_play.setText(PAUSE_ICON)

    def stop_play(self):
        self.timer.stop()
        self.b_play.setText(PLAY_ICON)

    def advance(self, seconds):
        """Move the cursor by ``seconds`` of playback; returns False when the end is reached."""
        self._play_acc += seconds*self.play_speed
        steps = int(self._play_acc)
        if steps <= 0:
            return True
        self._play_acc -= steps
        last = len(self.program.lines)-1
        if self.cursor+steps >= last:
            self.set_cursor(last)
            return False
        self.set_cursor(self.cursor+steps)
        return True

    def _tick(self):
        if self.program is None:
            return self.stop_play()
        now = time.perf_counter()
        elapsed, self._play_t = now-self._play_t, now
        if not self.advance(elapsed):
            self.stop_play()
