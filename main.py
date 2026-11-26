import argparse

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from modules.gui import Window


def main():
    parser = argparse.ArgumentParser(description="Monitor a Bluetooth heart rate strap")
    parser.add_argument("--address", help="Connect to a specific Bluetooth address")
    args = parser.parse_args()

    app = QApplication([])
    pg.setConfigOptions(antialias=True)
    window = Window(args.address)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
