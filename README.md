# PulseLab

A Python desktop app for exploring data from Bluetooth heart rate sensors. It shows heart rate, the time between beats (R-R intervals), a live plot, and heart rate variability (RMSSD and SDNN).

Tested with a Garmin HRM-Dual on Ubuntu 24.04. Windows setup is listed below, but Bluetooth monitoring has yet to be tested on Windows.

## Setup

Open a terminal in the project folder and follow the steps for your system.

### Ubuntu 24.04

```bash
sudo apt update
sudo apt install bluez python3-venv libxcb-cursor0 libegl1 libgl1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

### Windows

Install Python 3.12 and open PowerShell in the project folder.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Use

Turn on Bluetooth and put on the strap. The app looks for it automatically. If you have more than one monitor, add `--address AA:BB:CC:DD:EE:FF` to the launch command with your strap's Bluetooth address.

Click **Start recording**, then **Stop recording** and **Export CSV**. The CSV includes the raw Bluetooth packets, their arrival times, and the heart rate and R-R values.

The app flags unusual R-R values and shows when the connection drops. Several R-R values can arrive in one packet. A delay between packets alone can't tell you whether a beat was missed.

## Files

- `main.py` starts the app.
- `modules/gui.py` shows the window and plot.
- `modules/ble.py` connects to the strap.
- `modules/heart_rate.py` reads the packets.
- `modules/analysis.py` checks R-R values and calculates RMSSD and SDNN.
- `modules/recording.py` saves the CSV.

Run the tests with `python -m unittest discover -s tests -v`.
