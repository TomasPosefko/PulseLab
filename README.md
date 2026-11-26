# PulseLab

A Python app for checking my Garmin HRM-Dual on Ubuntu 24.04. It shows heart rate, the time between beats (R-R intervals), a live plot, and two heart rate variability measurements (RMSSD and SDNN).

## Setup

Run these commands from the project folder:

```bash
sudo apt update
sudo apt install bluez python3-venv libxcb-cursor0 libegl1 libgl1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

## Use

Turn on Bluetooth and put on the strap. The app finds it automatically. If you have more than one monitor, you can pick one with `python main.py --address AA:BB:CC:DD:EE:FF`.

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
