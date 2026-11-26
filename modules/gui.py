"""Shows the live measurements and recording controls."""

from collections import deque
from math import nan
from queue import Empty, Queue
from threading import Thread

import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from .analysis import break_segment, metrics, new_analysis, process
from .ble import run_monitor, timestamp
from .heart_rate import milliseconds
from .recording import add_link, add_packet, elapsed, export_csv, new_recording, stop_recording

STYLE = """
QMainWindow, QWidget#content { background: #141c27; color: #e9eff7; }
QLabel { color: #d9e4ef; }
QLabel#title { color: #f4f8ff; font-size: 25px; font-weight: bold; }
QLabel#metric { background: #202d3d; padding: 12px; border-radius: 6px; }
QPushButton { background: #2b4057; color: white; padding: 8px 14px; border-radius: 5px; }
QPushButton:hover { background: #365772; }
QPushButton:disabled { color: #8a9bad; background: #202d3d; }
QTableWidget { background: #192432; color: #e9eff7; gridline-color: #344457;
               alternate-background-color: #202d3d; }
QHeaderView::section { background: #28384b; color: #e9eff7; padding: 5px; border: 0; }
"""


def display(value, decimals=1):
    return "—" if value is None else f"{value:.{decimals}f}"


class Window(QMainWindow):
    def __init__(self, address=None):
        super().__init__()
        self.setWindowTitle("PulseLab")
        self.resize(1150, 760)
        self.setStyleSheet(STYLE)
        self.analysis = new_analysis()
        self.beats = deque(maxlen=240)
        self.recording = None
        self.saved = False
        self.closing = False
        self.sequence = 0

        content = QWidget(objectName="content")
        self.setCentralWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("PulseLab", objectName="title"))
        toolbar.addStretch()
        self.record_button = QPushButton("Start recording")
        self.record_button.clicked.connect(self.toggle_recording)
        toolbar.addWidget(self.record_button)
        self.export_button = QPushButton("Export CSV…")
        self.export_button.clicked.connect(self.export)
        self.export_button.setEnabled(False)
        toolbar.addWidget(self.export_button)
        layout.addLayout(toolbar)

        self.connection = QLabel("Starting Bluetooth…")
        self.connection.setWordWrap(True)
        layout.addWidget(self.connection)
        metrics = QHBoxLayout()
        self.metrics = []
        for name in ("Heart rate (BPM)", "Latest R-R (ms)", "RMSSD (ms)", "SDNN (ms)"):
            label = QLabel(f"{name}\n—", objectName="metric")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty("metric_name", name)
            self.metrics.append(label)
            metrics.addWidget(label, 1)
        layout.addLayout(metrics)

        self.diagnostic = QLabel("Waiting for heart rate notifications")
        self.diagnostic.setWordWrap(True)
        self.session_status = QLabel("Recording idle")
        layout.addWidget(self.diagnostic)
        layout.addWidget(self.session_status)

        plot = pg.PlotWidget(background="#192432")
        plot.setTitle("R-R tachogram", color="#e9eff7")
        plot.setLabel("bottom", "Cumulative received R-R time", units="s")
        plot.setLabel("left", "R-R interval", units="ms")
        plot.showGrid(x=True, y=True, alpha=0.2)
        self.line = plot.plot(pen=pg.mkPen("#62d7cb", width=2), connect="finite",
                              symbol="o", symbolSize=4, symbolBrush="#62d7cb", symbolPen=None)
        self.flagged = plot.plot(pen=None, symbol="o", symbolSize=8,
                                 symbolBrush="#ffbd70", symbolPen=None)
        layout.addWidget(plot, 3)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("#", "Arrival (UTC)", "Δ arrival (ms)", "R-R count", "R-R values (ms)", "Diagnostics")
        )
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(4, 210)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 2)

        self.messages = Queue()
        self.monitor = Thread(target=run_monitor, args=(address, self.messages, lambda: self.closing))
        self.monitor.start()

        self.clock = QTimer(self, interval=100)
        self.clock.timeout.connect(self.refresh)
        self.clock.start()

    def refresh(self):
        if self.closing:
            if not self.monitor.is_alive():
                self.close()
            return
        self.read_bluetooth()
        self.update_session_status()

    def read_bluetooth(self):
        while True:
            try:
                kind, data = self.messages.get_nowait()
            except Empty:
                return
            if kind == "status":
                self.connection.setText(data)
            elif kind == "link":
                self.show_link(*data)
            else:
                self.show_packet(*data)

    def discard_confirmed(self):
        if self.recording is None or self.saved:
            return True
        return QMessageBox.question(
            self, "Unsaved recording", "Discard the recording without exporting it?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Discard

    def toggle_recording(self):
        if self.recording is not None and self.recording["stop"] is None:
            self.read_bluetooth()
            stop_recording(self.recording, timestamp())
            self.record_button.setText("Start recording")
            self.export_button.setEnabled(True)
        elif self.discard_confirmed():
            self.recording = new_recording(timestamp())
            self.saved = False
            self.record_button.setText("Stop recording")
            self.export_button.setEnabled(False)
        self.update_session_status()

    def update_session_status(self):
        if self.recording is None:
            return
        seconds = elapsed(self.recording, timestamp()) / 1000
        rr_seconds = self.recording["analysis"]["total_ticks"] / 1024
        state = "Recording" if self.recording["stop"] is None else "Stopped"
        self.session_status.setText(
            f"{state}  ·  Elapsed {seconds:.1f} s  ·  Received R-R {rr_seconds:.1f} s  "
            f"·  Elapsed − R-R {seconds - rr_seconds:+.1f} s"
        )

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export recording", "pulselab.csv",
                                               "CSV files (*.csv)")
        if not path:
            return
        try:
            export_csv(self.recording, path)
        except OSError as error:
            QMessageBox.critical(self, "CSV export failed", str(error))
        else:
            self.saved = True

    def set_metrics(self, values):
        for label, value in zip(self.metrics, values):
            label.setText(f"{label.property('metric_name')}\n{value}")

    def show_link(self, stamp, address, kind, detail):
        if self.recording is not None:
            add_link(self.recording, stamp, address, kind, detail)
        if kind in {"connected", "disconnected"}:
            break_segment(self.analysis)
        if kind == "disconnected":
            rmssd, sdnn = metrics(self.analysis)
            self.set_metrics(("—", "—", display(rmssd), display(sdnn)))
        self.diagnostic.setText(f"{kind.capitalize()} · {detail}")
        self.add_row(("—", stamp[1], "—", "—", "—", f"{kind}: {detail}"))

    def show_packet(self, stamp, address, characteristic, payload):
        if self.recording is not None:
            add_packet(self.recording, stamp, address, characteristic, payload)
        packet = process(self.analysis, payload, stamp[0])
        self.sequence += 1
        beats = packet["beats"]
        measurement = packet["measurement"]
        self.beats.extend(beats)
        bpm = measurement["bpm"] if measurement else None
        latest = milliseconds(beats[-1]["ticks"]) if beats else None
        self.set_metrics((display(bpm, 0), display(latest),
                          *(display(value) for value in metrics(self.analysis))))
        notes = packet["notes"]
        for beat in beats:
            quality = beat["quality"]
            if quality and quality not in notes:
                notes.append(quality)
        coverage = packet["coverage_delta_ms"]
        diagnostic = " · ".join(notes) or "Receiving notifications"
        if coverage is not None:
            diagnostic += f"  |  Segment arrival time − R-R {coverage / 1000:+.2f} s"
        self.diagnostic.setText(diagnostic)
        rr_text = ", ".join(display(milliseconds(beat["ticks"])) for beat in beats)
        self.add_row((str(self.sequence), stamp[1], display(packet["arrival_delta_ms"]),
                      str(len(beats)) if measurement else "—", rr_text or "—",
                      " · ".join(notes)))
        if beats:
            self.update_plot()

    def update_plot(self):
        x, y, flagged_x, flagged_y = [], [], [], []
        previous_segment = None
        for beat in self.beats:
            seconds, rr = beat["cumulative_ms"] / 1000, milliseconds(beat["ticks"])
            if previous_segment is not None and previous_segment != beat["segment"]:
                x.append(nan)
                y.append(nan)
            x.append(seconds)
            y.append(rr)
            if beat["quality"]:
                flagged_x.append(seconds)
                flagged_y.append(rr)
            previous_segment = beat["segment"]
        self.line.setData(x, y)
        self.flagged.setData(flagged_x, flagged_y)

    def add_row(self, values):
        scroll = self.table.verticalScrollBar()
        at_bottom = scroll.value() == scroll.maximum()
        if self.table.rowCount() >= 250:
            self.table.removeRow(0)
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            if column == 5 and value:
                item.setForeground(QColor("#ffbd70"))
            self.table.setItem(row, column, item)
        if at_bottom:
            self.table.scrollToBottom()

    def closeEvent(self, event):
        if not self.closing:
            if not self.discard_confirmed():
                event.ignore()
                return
            self.closing = True
            self.connection.setText("Closing Bluetooth…")
        if self.monitor.is_alive():
            event.ignore()
        else:
            event.accept()

