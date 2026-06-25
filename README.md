# RobotAI Project — Finger-Count Gesture Control for Omnidirectional Mobile Robot

> **Paper:** "Finger-Count Gesture Control for Omnidirectional Mobile Robot with Edge-Host Decoupled Architecture and Dependable Failsafe Design"  
> **Conference:** ICKII 2026, August 14–16, 2026, Sendai, Japan  
> **Authors:** Yan-Ming Lin, Tse-Chuan Hsu — Soochow University

---

## System Overview

A gesture-controlled omnidirectional robot using an **Edge-Host Decoupled** architecture:

- **Host (MacBook):** Runs MediaPipe hand tracking + gesture recognition + sends UDP commands
- **Edge (Raspberry Pi 1 B+):** Receives UDP commands → drives 4 Mecanum wheels + streams MJPEG video

The operator controls the robot using single-hand **finger-count micro-gestures** performed with the arm resting flat on a surface (zero fatigue), confirmed by a **latch-state machine** that locks the command so the hand can be removed entirely.

```
MacBook (Host)                        Raspberry Pi 1 B+ (Edge)
──────────────────────────────        ──────────────────────────────
Built-in Camera                       IMX219 / USB Camera
     ↓                                      ↓
MediaPipe Hands (21 landmarks)        pi_fast_stream.py
     ↓                                (MJPEG, 320×240, 30fps)
GestureEngine (classify + lock)             ↓
     ↓                          ←─── MJPEG over HTTP :8000
telepresence_controller.py
     ↓
UDP command ──────────────────→ pi_udp_omni.py
                                      ↓
                                 gpiozero Motor × 4
                                 (Mecanum wheel drive)
```

---

## Gesture Vocabulary

| Extended Fingers | Pose | Command | Function |
|---|---|---|---|
| None | Fist | SPACE | Emergency stop |
| Thumb only | — | Q | Clockwise rotation |
| Thumb + Index | L-shape | E | Counter-clockwise rotation |
| Index only | — | W | Forward |
| Index + Middle | — | S | Backward |
| Index + Middle + Ring | — | A | Strafe left |
| Index + Middle + Ring + Pinky | — | D | Strafe right |
| All five | Open palm | BOOST | Max speed (inherit direction) |

---

## Repository Structure

```
RobotAI_Project/
├── core/
│   ├── telepresence_controller.py   # Mac main program (gesture + display + UDP)
│   ├── gesture_engine.py            # Finger-count gesture classifier + latch state machine
│   ├── experiment_logger.py         # Per-frame telemetry recorder
│   └── watchdog_test.py             # Watchdog response time measurement
├── pi/
│   ├── pi_fast_stream.py             # Mirror of the Pi's MJPEG stream server (port 8000)
│   └── pi_udp_omni.py                # Mirror of the Pi's UDP command receiver + motor control
├── docs/
│   ├── ICKII_paper_draft.docx       # Full paper draft
│   ├── architecture_v2.png          # System architecture diagram
│   └── SUBMISSION_CHECKLIST.md      # Conference submission checklist
├── logs/                            # Experiment logs (auto-generated)
│   ├── accuracy_20260604.txt        # Gesture accuracy test results (98.1%)
│   ├── watchdog_results.txt         # Watchdog response time results (mean 533ms)
│   └── experiment_*.csv             # Per-frame telemetry CSV files
├── referencepap/                    # Reference papers (PDFs)
├── requirements.txt                  # Mac (host) Python dependencies
├── .gitignore
└── README.md                        # This file
```

The Pi itself keeps its own copy of `core/{pi_fast_stream.py,pi_udp_omni.py}` plus a
`start.sh` launcher and `logs/` under `~/RobotAI_Project/` on the Pi — the files under
`pi/` here on the Mac are mirrors kept for reference/version control, not executed directly.

---

## Quick Start

### 1. Set up the Raspberry Pi from scratch

```bash
ssh imyanming@192.168.68.112

# System packages
sudo apt update
sudo apt install -y python3-gpiozero python3-opencv python3-picamera2

# Project files: copy core/pi_fast_stream.py, core/pi_udp_omni.py, and start.sh
# from this repo's pi/ folder into ~/RobotAI_Project/core/ and ~/RobotAI_Project/ on the Pi
# (e.g. via scp), then:
chmod +x ~/RobotAI_Project/start.sh
```

Notes specific to this hardware (Pi 1 B+, Bookworm/libcamera):
- `cv2.VideoCapture()` cannot read frames from the IMX219 camera directly (it only
  exposes raw Bayer data over plain V4L2) — capture must go through `Picamera2`/libcamera,
  with OpenCV used only for JPEG encoding. This is already how `pi_fast_stream.py` is written.
- `import cv2` alone takes ~35 seconds on this single-core ARM11 CPU — this is normal,
  not a hang.
- `vcgencmd get_camera` is unreliable on this OS and may report `detected=0` even when
  the camera works; use `rpicam-hello --list-cameras` to actually verify detection.

### 2. Start the robot (Pi)

```bash
ssh imyanming@192.168.68.112
~/RobotAI_Project/start.sh
```

This launches both services in the background and prints the Pi's IP plus the stream
and motor-control endpoints (`http://<ip>:8000/stream.mjpg`, UDP `<ip>:9000`).

### 3. Mac (Host)

```bash
cd ~/RobotAI_Project
python3 -m venv venv && source venv/bin/activate   # first time only
pip install -r requirements.txt                     # first time only
source venv/bin/activate
python3 core/telepresence_controller.py
```

### Keyboard Shortcuts

| Key | Function |
|---|---|
| `V` | Toggle FPV stream / gesture-only mode |
| `T` | Start gesture accuracy test |
| `L` / `R` | Start / stop experiment recording |
| `1`–`5` | Set experiment ID |
| `Q` | Quit |

---

## Experimental Results

| Metric | Result |
|---|---|
| Gesture recognition accuracy | **98.1%** (157/160 trials) |
| Weakest gesture (Strafe Left) | 85% (17/20) |
| Watchdog halt response (mean) | **533 ms** (6 trials, all < 600 ms) |
| End-to-end command latency | **1260 ms** (dominated by MJPEG stream ~900 ms) |

---

## Troubleshooting

**Pi not connecting / IP changed?** Scan the local subnet for live hosts:
```bash
for i in $(seq 1 254); do ping -c 1 -W 1 192.168.68.$i &>/dev/null && echo "192.168.68.$i alive"; done
```

**Camera not working?** SSH into the Pi and check libcamera sees it (not `vcgencmd`, which is unreliable on this OS):
```bash
ssh imyanming@192.168.68.112
rpicam-hello --list-cameras
```

**Missing Python modules on the Mac side?**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**No video / no motor response after `start.sh`?** Check the two services are actually running and inspect their logs:
```bash
ssh imyanming@192.168.68.112
pgrep -fa 'pi_fast_stream|pi_udp_omni'
tail -n 30 ~/RobotAI_Project/logs/pi_fast_stream.log ~/RobotAI_Project/logs/pi_udp_omni.log
```

---

## Future Work

- **Pi camera gesture recognition:** move gesture classification onto the Pi itself
  using the existing `Picamera2`/libcamera capture pipeline, removing the dependency on
  streaming raw MJPEG to the host for control purposes (the stream would remain available
  for human FPV viewing). This would cut end-to-end command latency by eliminating the
  ~900 ms MJPEG round-trip currently dominating the 1260 ms figure above, at the cost of
  running a lightweight detector on the Pi 1 B+'s limited ARM11 CPU — likely requiring a
  much smaller/quantized model than the MediaPipe Hands pipeline currently run on the Mac.

---

## Hardware

| Component | Specification |
|---|---|
| Edge compute | Raspberry Pi 1 Model B+, ARM11 @ 700 MHz, 512 MB RAM |
| Edge motor driver | L298N dual H-bridge × 2 |
| Edge chassis | 4-wheel Mecanum omnidirectional platform |
| Host compute | MacBook, Apple M-series |
| Network | 802.11n Wi-Fi |

---

## Dependencies

**Mac (Host):** see `requirements.txt`
```bash
pip install -r requirements.txt
```

**Raspberry Pi (Edge):** installed via apt, not pip (pip is not used for system camera/GPIO
bindings on this OS):
```bash
sudo apt install -y python3-gpiozero python3-opencv python3-picamera2
```

---

## Citation

If you use this work, please cite:

```
Lin, Y.-M.; Hsu, T.-C. Finger-Count Gesture Control for Omnidirectional Mobile Robot
with Edge-Host Decoupled Architecture and Dependable Failsafe Design.
In Proceedings of ICKII 2026, Sendai, Japan, August 14–16, 2026.
```

---

## License

MIT License — see LICENSE file for details.
