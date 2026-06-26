# FULL PROJECT DUMP — RobotAI_Project
<!-- Generated: 2026-06-25 -->

---

# README.md

```markdown
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
ssh imyanming@192.168.68.102

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
ssh imyanming@192.168.68.102
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
ssh imyanming@192.168.68.102
rpicam-hello --list-cameras
```

**Missing Python modules on the Mac side?**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**No video / no motor response after `start.sh`?** Check the two services are actually running and inspect their logs:
```bash
ssh imyanming@192.168.68.102
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
```


---

# core/telepresence_controller.py

```python
"""
telepresence_controller.py — Host-side (Mac) main program.

Runs on the operator's laptop, not on the robot. Responsibilities:
  1. Capture the operator's hand via the Mac webcam and run MediaPipe Hands.
  2. Feed landmarks into GestureEngine to classify + latch a drive command.
  3. Send that command to the Pi over UDP at a fixed rate (CommandSender).
  4. Pull the robot's MJPEG video feed back over HTTP and composite it with
     a picture-in-picture view of the operator's own hand (RequestsStream).
  5. Optionally run the on-screen 8-gesture accuracy benchmark (GestureAccuracyTest)
     and log per-frame telemetry via ExperimentLogger.

The Raspberry Pi never runs any AI inference — it only executes the single-
character commands this script sends it. See pi/pi_udp_omni.py for that side.
"""
import cv2
import numpy as np
import requests
import threading
import time
import mediapipe as mp
import socket
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from gesture_engine import GestureEngine, _classify, _BOOST_CMD
from experiment_logger import ExperimentLogger

# ─────────────────────────────────────────
#  Network / communication settings
# ─────────────────────────────────────────
STREAM_URL   = "http://192.168.68.102:8000/stream.mjpg"
PI_HOST      = "192.168.68.102"
PI_PORT      = 9000
UDP_INTERVAL = 0.10
MAX_BUF      = 65536

# ─────────────────────────────────────────
#  Robot FPV stream receiver (pulls MJPEG from the Pi)
# ─────────────────────────────────────────
class RequestsStream:
    def __init__(self, url):
        self.url     = url
        self.frame   = None
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            print("🔗 戰車視角連線中...")
            res = requests.get(self.url, stream=True, timeout=30)
            buf = b''
            for chunk in res.iter_content(chunk_size=4096):
                if not self.running: break
                buf += chunk
                # Buffer anti-accumulation: if the host can't decode frames as
                # fast as the Pi sends them, drop everything except the most
                # recent JPEG start-of-image marker so display latency cannot
                # grow unbounded during a transient CPU stall.
                if len(buf) > MAX_BUF:
                    last_soi = buf.rfind(b'\xff\xd8')
                    buf = buf[last_soi:] if last_soi != -1 else b''
                # \xff\xd8 = JPEG Start Of Image, \xff\xd9 = End Of Image.
                # MJPEG-over-HTTP has no length-prefixed framing, so each
                # complete frame must be located by scanning for these markers.
                a = buf.find(b'\xff\xd8')
                b = buf.find(b'\xff\xd9')
                if a != -1 and b != -1 and b > a:
                    img = cv2.imdecode(
                        np.frombuffer(buf[a:b+2], np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        self.frame = img
                    buf = buf[b+2:]
        except Exception as e:
            print(f"⚠️ 戰車串流中斷: {e}")

    def read(self):
        return (True, self.frame.copy()) if self.frame is not None else (False, None)

    def release(self):
        self.running = False

# ─────────────────────────────────────────
#  UDP command sender (Host → Edge)
# ─────────────────────────────────────────
class CommandSender:
    def __init__(self, host, port):
        self.addr    = (host, port)
        self.sock    = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._last_t = 0

    def send(self, cmd) -> bool:
        # Rate-limited to UDP_INTERVAL (100 ms) regardless of camera/inference
        # FPS, so the Pi's watchdog always sees a predictable command cadence
        # to measure silence against. Returns True/False if a send was
        # attempted this call, or None if the interval hasn't elapsed yet.
        now = time.time()
        if now - self._last_t >= UDP_INTERVAL:
            try:
                self.sock.sendto(cmd.encode(), self.addr)
                self._last_t = now
                return True
            except Exception:
                return False
        return None

# ─────────────────────────────────────────
#  Command display labels / state colors (HUD only)
# ─────────────────────────────────────────
_LABEL = {
    "W":     "FORWARD ▲",     "S": "BACKWARD ▼",
    "A":     "STRAFE LEFT ◀", "D": "STRAFE RIGHT ▶",
    "Q":     "ROTATE CW ↻",   "E": "ROTATE CCW ↺",
    "SPACE": "STOP",
}
_STATE_COLOR = {
    "TRACKING": (100, 220, 100),
    "LOCKED":   (50,  200, 255),
    "LOST":     (60,  60,  200),
}

# ─────────────────────────────────────────
#  Keyboard shortcut reference (printed once at startup)
# ─────────────────────────────────────────
_KEYMAP = """
  Keyboard shortcuts
  ──────────────────────────────────────────
  V         Toggle FPV stream / gesture-only mode
  L / R     Toggle experiment recording  ● REC
  1 – 5     Set experiment ID
  E         Mark event in log
  T         Start / stop gesture accuracy test
  Q         Quit (and save log if recording)
  ──────────────────────────────────────────
"""

# ─────────────────────────────────────────
#  Gesture accuracy benchmark (8 poses x TRIALS each, triggered by 'T')
# ─────────────────────────────────────────
_TEST_GESTURES = [
    ("SPACE", "STOP",         "Fist — all fingers closed"),
    ("Q",     "ROTATE CW",    "Thumb only"),
    ("E",     "ROTATE CCW",   "Thumb + Index  (L-shape)"),
    ("W",     "FORWARD",      "Index finger only"),
    ("S",     "BACKWARD",     "Index + Middle"),
    ("A",     "STRAFE LEFT",  "3 fingers  (index, middle, ring)"),
    ("D",     "STRAFE RIGHT", "4 fingers  (index, middle, ring, pinky)"),
    ("BOOST", "BOOST",        "Open palm — all 5 fingers"),
]

_LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')


class GestureAccuracyTest:
    PREP_SECS   = 3.0
    DETECT_SECS = 2.0
    RESULT_SECS = 0.6
    TRIALS      = 20

    def __init__(self):
        self.active      = False
        self.phase       = "prep"
        self.gesture_idx = 0
        self.trial_idx   = 0
        self.results     = {}
        self.phase_start = 0.0
        self.last_result = None
        self._streak     = 0
        self._success    = False
        self._log_saved  = False

    def start(self):
        self.active      = True
        self.phase       = "prep"
        self.gesture_idx = 0
        self.trial_idx   = 0
        self.results     = {g[0]: [] for g in _TEST_GESTURES}
        self.phase_start = time.time()
        self.last_result = None
        self._streak     = 0
        self._success    = False
        self._log_saved  = False

    def stop(self):
        self.active = False

    def _target_cmd(self):
        return _TEST_GESTURES[self.gesture_idx][0]

    def _raw_matches(self, raw_cmd):
        target = self._target_cmd()
        return raw_cmd == (_BOOST_CMD if target == "BOOST" else target)

    def update(self, hand_lm, now):
        if not self.active:
            return None
        elapsed = now - self.phase_start

        if self.phase == "prep":
            if elapsed >= self.PREP_SECS:
                self.phase       = "detect"
                self.phase_start = now
                self._streak     = 0
                self._success    = False

        elif self.phase == "detect":
            if hand_lm is not None:
                raw_cmd, _ = _classify(hand_lm.landmark)
                if raw_cmd is not None and self._raw_matches(raw_cmd):
                    self._streak += 1
                    if self._streak >= 3:
                        self._success = True
                else:
                    self._streak = 0
            if self._success or elapsed >= self.DETECT_SECS:
                self.last_result = self._success
                self.results[self._target_cmd()].append(self._success)
                self.phase       = "result"
                self.phase_start = now

        elif self.phase == "result":
            if elapsed >= self.RESULT_SECS:
                self.trial_idx += 1
                if self.trial_idx >= self.TRIALS:
                    self.trial_idx    = 0
                    self.gesture_idx += 1
                    if self.gesture_idx >= len(_TEST_GESTURES):
                        self.phase = "summary"
                        return "summary"
                self.phase       = "prep"
                self.phase_start = now

        return self.phase

    def total_progress(self):
        done  = self.gesture_idx * self.TRIALS + self.trial_idx
        total = len(_TEST_GESTURES) * self.TRIALS
        return done, total

    def get_summary(self):
        rows = []
        total_ok, total_n = 0, 0
        for cmd, label, _ in _TEST_GESTURES:
            trials = self.results.get(cmd, [])
            n, ok  = len(trials), sum(trials)
            pct    = 100 * ok // n if n else 0
            total_ok += ok
            total_n  += n
            rows.append((label, cmd, ok, n, pct))
        overall = 100 * total_ok // total_n if total_n else 0
        return rows, overall

    def save_log(self):
        os.makedirs(_LOG_DIR, exist_ok=True)
        fname    = os.path.join(_LOG_DIR, f"accuracy_{time.strftime('%Y%m%d')}.txt")
        rows, overall = self.get_summary()
        total_ok = sum(sum(v) for v in self.results.values())
        total_n  = sum(len(v) for v in self.results.values())
        with open(fname, "w") as f:
            f.write(f"Gesture Accuracy Test — {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 56 + "\n")
            f.write(f"  {'Gesture':<22} {'Cmd':<6} {'Correct':>7}  {'Acc':>4}\n")
            f.write("-" * 56 + "\n")
            for label, cmd, ok, n, pct in rows:
                f.write(f"  {label:<22} {cmd:<6} {ok:>2}/{n:<2}     {pct:>3}%\n")
            f.write("=" * 56 + "\n")
            f.write(f"  {'OVERALL':<22} {'':6} {total_ok:>2}/{total_n:<2}     {overall:>3}%\n")
        return fname


# ─────────────────────────────────────────
#  Accuracy-test on-screen overlay rendering
# ─────────────────────────────────────────
def _draw_test_overlay(canvas, test, now):
    H, W = canvas.shape[:2]

    # ── Summary screen ───────────────────────────────────────────────────
    if test.phase == "summary":
        cv2.rectangle(canvas, (0, 0), (W, H), (10, 10, 30), -1)
        rows, overall = test.get_summary()

        cv2.putText(canvas, "ACCURACY RESULTS",
                    (W // 2 - 215, 72), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 220, 50), 3)
        cv2.line(canvas, (60, 92), (W - 60, 92), (70, 70, 70), 1)

        y = 152
        for label, cmd, ok, n, pct in rows:
            col = ((50, 220, 50)  if pct >= 80 else
                   (50, 200, 255) if pct >= 60 else (80, 80, 200))
            cv2.putText(canvas, label,       (80,  y), cv2.FONT_HERSHEY_SIMPLEX, 0.7,  col,          2)
            cv2.putText(canvas, f"({cmd})",  (390, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (150,150,150),1)
            cv2.putText(canvas, f"{ok}/{n}", (480, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7,  col,          2)
            bx = 565
            cv2.rectangle(canvas, (bx, y - 18), (bx + 220, y + 4), (38, 38, 38), -1)
            cv2.rectangle(canvas, (bx, y - 18), (bx + int(2.2 * pct), y + 4), col, -1)
            cv2.putText(canvas, f"{pct}%", (bx + 228, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, col, 2)
            y += 46

        cv2.line(canvas, (60, y + 4), (W - 60, y + 4), (70, 70, 70), 1)
        ov_col = ((50, 220, 50)  if overall >= 80 else
                  (50, 200, 255) if overall >= 60 else (80, 80, 200))
        cv2.putText(canvas, f"OVERALL  {overall}%",
                    (W // 2 - 135, y + 55), cv2.FONT_HERSHEY_SIMPLEX, 1.3, ov_col, 3)
        cv2.putText(canvas, "[ T ]  exit test mode",
                    (W // 2 - 130, H - 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (85, 85, 85), 1)
        return

    if test.gesture_idx >= len(_TEST_GESTURES):
        return
    cmd, label, instruction = _TEST_GESTURES[test.gesture_idx]
    done, total = test.total_progress()

    # ── Top bar ──────────────────────────────────────────────────────────
    cv2.rectangle(canvas, (0, 0), (W, 56), (18, 18, 48), -1)
    cv2.putText(canvas,
                f"ACCURACY TEST  |  {label} ({cmd})  —  {test.trial_idx + 1}/{test.TRIALS}",
                (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (255, 220, 50), 2)

    # ── Dark centre panel (left 592 px, clear of PIP area) ───────────────
    overlay = canvas.copy()
    cv2.rectangle(overlay, (40, 64), (592, H - 20), (8, 8, 36), -1)
    cv2.addWeighted(overlay, 0.75, canvas, 0.25, 0, canvas)

    cv2.putText(canvas, "SHOW THIS GESTURE:", (72, 116),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (110, 110, 185), 1)
    cv2.putText(canvas, instruction, (72, 168),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (215, 232, 255), 2)

    # ── Phase display ────────────────────────────────────────────────────
    if test.phase == "prep":
        elapsed   = now - test.phase_start
        remaining = max(0.0, test.PREP_SECS - elapsed)
        cv2.putText(canvas, "GET READY...", (72, 265),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (200, 200, 100), 2)
        cv2.putText(canvas, str(int(remaining) + 1), (255, 500),
                    cv2.FONT_HERSHEY_SIMPLEX, 6.0, (255, 200, 50), 12)

    elif test.phase == "detect":
        elapsed   = now - test.phase_start
        remaining = max(0.0, test.DETECT_SECS - elapsed)
        frac      = remaining / test.DETECT_SECS
        cv2.putText(canvas, "SHOW NOW!", (72, 265),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (80, 255, 140), 3)
        bx0, by0, bw, bh = 72, 305, 468, 26
        cv2.rectangle(canvas, (bx0, by0), (bx0 + bw, by0 + bh), (44, 44, 44), -1)
        fc = (50, max(0, int(80 + 150 * frac)), max(0, int(200 * frac)))
        cv2.rectangle(canvas, (bx0, by0), (bx0 + int(bw * frac), by0 + bh), fc, -1)
        cv2.rectangle(canvas, (bx0, by0), (bx0 + bw, by0 + bh), (80, 80, 80), 1)
        cv2.putText(canvas, f"{remaining:.1f}s", (bx0 + bw + 10, by0 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 180, 180), 2)

    elif test.phase == "result":
        if test.last_result:
            cv2.putText(canvas, "OK!", (90, 445),
                        cv2.FONT_HERSHEY_SIMPLEX, 5.5, (50, 220, 80), 10)
        else:
            cv2.putText(canvas, "MISS", (90, 445),
                        cv2.FONT_HERSHEY_SIMPLEX, 4.0, (80, 80, 220), 8)

    # ── Last result hint (shown during prep / detect phases) ─────────────
    if test.last_result is not None and test.phase != "result":
        txt = "Last:  OK" if test.last_result else "Last:  MISS"
        col = (50, 200, 80) if test.last_result else (80, 80, 200)
        cv2.putText(canvas, txt, (72, H - 46),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, col, 2)

    # ── Overall progress bar ─────────────────────────────────────────────
    pb_x, pb_y, pb_w, pb_h = 72, H - 18, 468, 12
    cv2.rectangle(canvas, (pb_x, pb_y - pb_h), (pb_x + pb_w, pb_y), (40, 40, 40), -1)
    if total:
        cv2.rectangle(canvas, (pb_x, pb_y - pb_h),
                      (pb_x + int(pb_w * done / total), pb_y), (50, 175, 100), -1)
    cv2.rectangle(canvas, (pb_x, pb_y - pb_h), (pb_x + pb_w, pb_y), (75, 75, 75), 1)
    cv2.putText(canvas, f"{done}/{total}", (pb_x + pb_w + 8, pb_y - 1),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (115, 115, 115), 1)


# ─────────────────────────────────────────
#  Main loop
# ─────────────────────────────────────────
def main():
    print("🧠 載入 MediaPipe 單手追蹤模型...")
    mp_hands = mp.solutions.hands
    hands    = mp_hands.Hands(
        static_image_mode=False, max_num_hands=1,
        min_detection_confidence=0.7, min_tracking_confidence=0.6)
    mp_draw  = mp.solutions.drawing_utils
    engine   = GestureEngine()
    logger   = ExperimentLogger()
    test     = GestureAccuracyTest()

    print("📷 啟動 Mac 視訊鏡頭...")
    mac_cam = cv2.VideoCapture(0)

    print("📡 啟動戰車 FPV 串流...")
    tank_stream = RequestsStream(STREAM_URL)
    sender      = CommandSender(PI_HOST, PI_PORT)

    print(_KEYMAP)

    BG_W, BG_H   = 960, 720
    PIP_W, PIP_H = 320, 240

    cmd, speed   = "SPACE", 0.0
    show_stream  = True

    fps, fps_n, fps_t = 0, 0, time.time()

    while True:
        now = time.time()

        # ── 1. Read Mac webcam, mirror it so the operator's on-screen
        #      movement matches their own hand direction ─────────────
        ret, mac_frame = mac_cam.read()
        if not ret: continue
        mac_frame = cv2.flip(mac_frame, 1)

        # ── 2. Main background: robot's FPV feed, or a placeholder
        #      while gesture-only mode is active or stream not yet up ─
        if show_stream:
            ok, tank_frame = tank_stream.read()
            if ok:
                main_bg = cv2.resize(tank_frame, (BG_W, BG_H))
            else:
                main_bg = np.zeros((BG_H, BG_W, 3), dtype=np.uint8)
                cv2.putText(main_bg, "WAITING FOR TANK FPV...", (240, 360),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        else:
            main_bg = np.zeros((BG_H, BG_W, 3), dtype=np.uint8)

        # ── 3. Gesture recognition: MediaPipe needs RGB input, OpenCV
        #      captures in BGR, hence the color conversion ─────────────
        results = hands.process(cv2.cvtColor(mac_frame, cv2.COLOR_BGR2RGB))

        hand_lm = results.multi_hand_landmarks[0] if results.multi_hand_landmarks else None
        if hand_lm:
            mp_draw.draw_landmarks(mac_frame, hand_lm, mp_hands.HAND_CONNECTIONS)

        cmd, speed = engine.update(hand_lm)
        state      = engine.get_state()
        dbg        = engine.get_debug_info()

        # ── 4. Send the locked command to the Pi over UDP (rate-limited
        #      inside CommandSender; see send() above) ──────────────────
        sent = sender.send(cmd)
        if sent is True:
            logger.log_udp(True)
        elif sent is False:
            logger.log_udp(False)

        # ── 5. Record this frame's telemetry if an experiment is being
        #      logged (no-op when logger.is_recording() is False) ──────
        logger.log_frame(
            ts=now, raw_cmd=dbg['pending'], locked_cmd=cmd,
            speed=speed, state=state, fps=fps,
            pending=dbg['pending'], streak=dbg['streak'])

        # ── 6. Gesture-only mode: show the active command as large
        #      centred text instead of the (unavailable/hidden) FPV feed ──
        if not show_stream and not test.active:
            lbl = _LABEL.get(cmd, cmd)
            clr = ((50, 255, 100) if cmd in ("W", "S") else
                   (255, 220, 50) if cmd in ("A", "D", "Q", "E") else
                   (180, 180, 180))
            cv2.putText(main_bg, lbl,
                        (BG_W//2 - 220, BG_H//2 - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 2.4, clr, 5)
            if cmd != "SPACE":
                cv2.putText(main_bg, f"{speed:.0%}",
                            (BG_W//2 - 50, BG_H//2 + 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.6, clr, 3)
            cv2.putText(main_bg, "[ V ] stream  [ L ] rec  [ Q ] quit",
                        (BG_W//2 - 240, BG_H - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (70, 70, 70), 1)

        # ── 7. Picture-in-picture inset of the operator's own camera, so
        #      they can verify their gesture is being tracked correctly
        #      while watching the robot's FPV feed ───────────────────────
        pip = cv2.resize(mac_frame, (PIP_W, PIP_H))
        main_bg[BG_H-PIP_H-20:BG_H-20, BG_W-PIP_W-20:BG_W-20] = pip
        cv2.rectangle(main_bg,
                      (BG_W-PIP_W-20, BG_H-PIP_H-20), (BG_W-20, BG_H-20),
                      (0, 255, 255), 2)
        cv2.putText(main_bg, "MAC SENSOR",
                    (BG_W-PIP_W-15, BG_H-PIP_H-25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # ── 8. HUD / accuracy-test overlay (mutually exclusive: the test
        #      overlay replaces the normal status bar while test.active) ──
        fps_n += 1
        if time.time() - fps_t >= 1.0:
            fps, fps_n, fps_t = fps_n, 0, time.time()

        if test.active:
            phase = test.update(hand_lm, now)
            if phase == "summary" and not test._log_saved:
                fname = test.save_log()
                test._log_saved = True
                print(f"Accuracy log saved -> {fname}")
            _draw_test_overlay(main_bg, test, now)
        else:
            label       = _LABEL.get(cmd, cmd)
            speed_text  = f"  {speed:.0%}" if cmd != "SPACE" else ""
            cmd_color   = ((50, 255, 100) if cmd in ("W", "S") else
                           (255, 220, 50) if cmd in ("A", "D", "Q", "E") else
                           (220, 220, 220))
            state_color = _STATE_COLOR.get(state, (200, 200, 200))

            cv2.rectangle(main_bg, (0, 0), (BG_W, 56), (18, 18, 18), -1)

            if show_stream:
                cv2.putText(main_bg, f"STATUS: {label}{speed_text}", (16, 36),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, cmd_color, 2)
            else:
                cv2.putText(main_bg, "MODE: GESTURE ONLY", (16, 36),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.85, (80, 180, 255), 2)

            cv2.putText(main_bg, f"[{state}]", (BG_W - 230, 36),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, state_color, 2)
            cv2.putText(main_bg, f"{fps} FPS", (BG_W - 110, 36),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (130, 130, 130), 1)

            if logger.is_recording():
                blink = int(time.time() * 2) % 2 == 0
                if blink:
                    cv2.circle(main_bg, (BG_W - 270, 30), 8, (0, 0, 220), -1)
                cv2.putText(main_bg, "REC", (BG_W - 258, 36),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 220), 2)

        cv2.imshow("Telepresence Command Center", main_bg)

        # ── 9. Keyboard input (see _KEYMAP above for the full shortcut list) ──
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            logger.finalize()
            break

        elif key == ord('t'):
            if test.active:
                test.stop()
                print("Test mode OFF")
            else:
                test.start()
                print("Accuracy test started — 8 gestures x 20 trials")

        elif key == ord('v'):
            show_stream = not show_stream
            if show_stream:
                tank_stream = RequestsStream(STREAM_URL)
                print("📡 串流模式")
            else:
                tank_stream.release()
                print("🖐  純手勢模式")

        elif key in (ord('l'), ord('r')):
            rec = logger.toggle_recording()
            print("● REC 開始" if rec else "■ REC 停止")

        elif ord('1') <= key <= ord('5'):
            logger.set_experiment_id(key - ord('0'))

        elif key == ord('e'):
            logger.mark_event()

    mac_cam.release()
    tank_stream.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
```


---

# core/gesture_engine.py

```python
TRANS_SPEED = 0.65
ROT_SPEED   = 0.30

_CONFIRM_FRAMES = 3   # consecutive frames to lock a new gesture
_LOST_THRESH    = 5   # absent frames before declaring LOST
_BOOST_CMD      = "__BOOST__"


class GestureEngine:
    """
    Finger-count static-pose gesture recogniser.

    update(hand_landmarks | None) → (cmd, speed)
    get_state()                   → "TRACKING" | "LOCKED" | "LOST"

    Finger → command mapping
    ──────────────────────────────────────────────
    0  fingers  (fist)                      SPACE   stop / clear lock
    thumb only                              Q       CW  rotate
    thumb + index  (L-shape)                E       CCW rotate
    index only                              W       forward
    index + middle                          S       backward
    index + middle + ring                   A       strafe left
    index + middle + ring + pinky           D       strafe right
    all 5 fingers                           BOOST   hold direction, speed → 100 %

    States
    ──────
    TRACKING  hand present, no command locked yet
    LOCKED    a command is active (hand present or brief absence ≤ LOST_THRESH)
    LOST      hand absent > LOST_THRESH frames; locked cmd still sent
    """

    def __init__(self):
        self._locked_cmd   = "SPACE"
        self._locked_speed = 0.0
        self._pending      = None
        self._streak       = 0
        self._lost_frames  = 0

    # ── public ──────────────────────────────────────────────────────

    def get_debug_info(self) -> dict:
        """Return internal state for logging / HUD display."""
        return {
            'pending':     self._pending,
            'streak':      self._streak,
            'lost_frames': self._lost_frames,
        }

    def reset(self):
        """Full reset — for program startup only."""
        self._locked_cmd   = "SPACE"
        self._locked_speed = 0.0
        self._pending      = None
        self._streak       = 0
        self._lost_frames  = 0

    def get_state(self) -> str:
        if self._lost_frames >= _LOST_THRESH:
            return "LOST"
        if self._lost_frames > 0 or self._locked_cmd != "SPACE":
            return "LOCKED"
        return "TRACKING"

    def update(self, hand_landmarks) -> tuple:
        """
        Pass MediaPipe hand_landmarks when hand is detected, or None when absent.
        Returns (command: str, speed: float).
        """
        if hand_landmarks is None:
            self._lost_frames = min(self._lost_frames + 1, _LOST_THRESH + 1)
            self._pending = None
            self._streak  = 0
            return self._locked_cmd, self._locked_speed

        self._lost_frames = 0
        lm = hand_landmarks.landmark

        raw_cmd, raw_speed = _classify(lm)

        if raw_cmd is None:
            self._pending = None
            self._streak  = 0
            return self._locked_cmd, self._locked_speed

        if raw_cmd == _BOOST_CMD:
            raw_cmd   = self._locked_cmd
            raw_speed = 1.0 if self._locked_cmd != "SPACE" else 0.0

        if raw_cmd == self._pending:
            self._streak += 1
        else:
            self._pending = raw_cmd
            self._streak  = 1

        if self._streak >= _CONFIRM_FRAMES:
            self._locked_cmd   = raw_cmd
            self._locked_speed = raw_speed
            self._streak       = _CONFIRM_FRAMES

        return self._locked_cmd, self._locked_speed


# ── classifier ────────────────────────────────────────────────────────────────

def _ext(lm):
    """Return (thumb, index, middle, ring, pinky) extension booleans."""
    thumb  = abs(lm[4].x - lm[0].x) > abs(lm[3].x - lm[0].x) * 1.1
    index  = lm[8].y  < lm[6].y
    middle = lm[12].y < lm[10].y
    ring   = lm[16].y < lm[14].y
    pinky  = lm[20].y < lm[18].y
    return thumb, index, middle, ring, pinky


def _classify(lm):
    """Returns (cmd, speed) or (None, None) for unrecognised poses."""
    t, i, m, r, p = _ext(lm)

    if not any((t, i, m, r, p)):
        return "SPACE", 0.0

    if all((t, i, m, r, p)):
        return _BOOST_CMD, 1.0

    if (t, i, m, r, p) == (True,  False, False, False, False):
        return "Q", ROT_SPEED

    if (t, i, m, r, p) == (True,  True,  False, False, False):
        return "E", ROT_SPEED

    if (t, i, m, r, p) == (False, True,  False, False, False):
        return "W", TRANS_SPEED

    if (t, i, m, r, p) == (False, True,  True,  False, False):
        return "S", TRANS_SPEED

    if (t, i, m, r, p) == (False, True,  True,  True,  False):
        return "A", TRANS_SPEED

    if (t, i, m, r, p) == (False, True,  True,  True,  True):
        return "D", TRANS_SPEED

    return None, None
```


---

# core/experiment_logger.py

```python
"""
ExperimentLogger — per-frame telemetry recorder for gesture-robot experiments.

Usage in telepresence_controller.py
───────────────────
    logger = ExperimentLogger()

    # every frame
    dbg  = engine.get_debug_info()
    logger.log_frame(time.time(), dbg['pending'], cmd, speed, state, fps,
                     dbg['pending'], dbg['streak'])

    # after UDP send
    logger.log_udp(sent=True/False)

    # keyboard shortcuts
    if key == ord('l') or key == ord('r'):  logger.toggle_recording()
    if key in [ord('1')…ord('5')]:          logger.set_experiment_id(key - ord('0'))
    if key == ord('e'):                     logger.mark_event()

    # on quit
    logger.finalize()
"""

import csv
import os
import time
from collections import defaultdict
from datetime import datetime

_LOGS_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')

_CSV_FIELDS = [
    'elapsed_s', 'exp_id', 'raw_cmd', 'locked_cmd',
    'speed', 'state', 'fps', 'pending', 'streak',
]


class ExperimentLogger:
    """
    Collects per-frame telemetry during robot experiments and produces
    a CSV data file plus a human-readable summary report.
    """

    def __init__(self, logs_dir: str = _LOGS_DIR):
        self._logs_dir = logs_dir
        os.makedirs(logs_dir, exist_ok=True)

        self._recording        = False
        self._exp_id           = None
        self._session_ts       = None
        self._start_time       = 0.0

        # per-session accumulators (reset on each start)
        self._frames: list     = []
        self._events: list     = []
        self._udp_ok           = 0
        self._udp_fail         = 0

        # derived-metric trackers
        self._prev_state       = None
        self._prev_locked_cmd  = "SPACE"
        self._lost_start_ts    = None
        self._lost_durations: list = []
        self._streak_start_ts  = None
        self._lock_events: list = []

    # ── public API ───────────────────────────────────────────────────

    def toggle_recording(self) -> bool:
        """Toggle recording on/off.  Returns the new recording state."""
        if self._recording:
            self._stop()
        else:
            self._start()
        return self._recording

    def set_experiment_id(self, exp_id: int) -> None:
        self._exp_id = exp_id
        print(f"[Logger] 實驗編號 → {exp_id}")

    def mark_event(self, description: str = "MANUAL_EVENT") -> None:
        """Stamp a named event at the current timestamp."""
        if not self._recording:
            print("[Logger] 未在記錄中，忽略事件標記")
            return
        ts  = time.time()
        rel = ts - self._start_time
        self._events.append({'elapsed_s': round(rel, 3), 'description': description})
        print(f"[Logger] 事件 ▶ {description}  (+{rel:.1f}s)")

    def log_frame(self, ts: float, raw_cmd, locked_cmd: str,
                  speed: float, state: str, fps: float,
                  pending, streak: int) -> None:
        """Record one processed frame.  Call every frame when recording."""
        if not self._recording:
            return

        elapsed = ts - self._start_time

        # ── lock-time tracking ──────────────────────────────────
        if streak == 1 and pending is not None and pending != "SPACE":
            self._streak_start_ts = ts          # new gesture started confirming

        if locked_cmd != self._prev_locked_cmd and locked_cmd != "SPACE":
            if self._streak_start_ts is not None:
                self._lock_events.append({
                    'elapsed_s': round(elapsed, 3),
                    'cmd':       locked_cmd,
                    'lock_ms':   round((ts - self._streak_start_ts) * 1000, 1),
                })
            self._streak_start_ts = None

        if pending is None:
            self._streak_start_ts = None

        # ── LOST-duration tracking ──────────────────────────────
        if state == "LOST" and self._prev_state != "LOST":
            self._lost_start_ts = ts
        elif state != "LOST" and self._prev_state == "LOST" and self._lost_start_ts:
            self._lost_durations.append(round((ts - self._lost_start_ts) * 1000, 1))
            self._lost_start_ts = None

        self._prev_state      = state
        self._prev_locked_cmd = locked_cmd

        self._frames.append({
            'elapsed_s':  round(elapsed, 3),
            'exp_id':     self._exp_id or 0,
            'raw_cmd':    raw_cmd or "NONE",
            'locked_cmd': locked_cmd,
            'speed':      round(speed, 2),
            'state':      state,
            'fps':        round(fps, 1),
            'pending':    pending or "NONE",
            'streak':     streak,
        })

    def log_udp(self, sent: bool) -> None:
        """Record a UDP send attempt result."""
        if not self._recording:
            return
        if sent:
            self._udp_ok += 1
        else:
            self._udp_fail += 1

    def is_recording(self) -> bool:
        return self._recording

    def finalize(self) -> str:
        """Stop recording if active, write files, print and return summary."""
        if self._recording:
            self._stop()
        if not self._frames:
            msg = "[Logger] 沒有記錄到任何資料。"
            print(msg)
            return msg
        return self._save()

    # ── private ──────────────────────────────────────────────────────

    def _start(self) -> None:
        self._session_ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._start_time      = time.time()
        self._recording       = True
        self._frames          = []
        self._events          = []
        self._udp_ok          = 0
        self._udp_fail        = 0
        self._prev_state      = None
        self._prev_locked_cmd = "SPACE"
        self._lost_start_ts   = None
        self._lost_durations  = []
        self._streak_start_ts = None
        self._lock_events     = []
        print(f"[Logger] ● REC  session={self._session_ts}  "
              f"實驗={self._exp_id or '未設定'}")

    def _stop(self) -> None:
        self._recording = False
        dur = time.time() - self._start_time
        print(f"[Logger] ■ STOP  {len(self._frames)} 幀  {dur:.1f}s")

    def _save(self) -> str:
        ts       = self._session_ts
        csv_path = os.path.join(self._logs_dir, f"experiment_{ts}.csv")
        txt_path = os.path.join(self._logs_dir, f"summary_{ts}.txt")

        # ── write CSV ──────────────────────────────────────────────
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
            w.writeheader()
            for fr in self._frames:
                w.writerow({k: fr[k] for k in _CSV_FIELDS})

        # ── derived statistics ─────────────────────────────────────
        duration  = self._frames[-1]['elapsed_s'] if self._frames else 0
        fps_vals  = [fr['fps'] for fr in self._frames if fr['fps'] > 0]
        avg_fps   = sum(fps_vals) / len(fps_vals)  if fps_vals else 0
        max_fps   = max(fps_vals)                   if fps_vals else 0
        min_fps   = min(fps_vals)                   if fps_vals else 0

        # command activation counts (transitions into each non-SPACE cmd)
        cmd_counts: dict = defaultdict(int)
        prev = "SPACE"
        for fr in self._frames:
            lc = fr['locked_cmd']
            if lc != prev and lc != "SPACE":
                cmd_counts[lc] += 1
            prev = lc

        total_udp = self._udp_ok + self._udp_fail
        udp_rate  = (self._udp_ok / total_udp * 100) if total_udp > 0 else 0

        lost_count = len(self._lost_durations)
        avg_lost   = (sum(self._lost_durations) / lost_count) if lost_count else 0

        avg_lock  = (sum(e['lock_ms'] for e in self._lock_events) /
                     len(self._lock_events)) if self._lock_events else 0

        # ── build summary text ─────────────────────────────────────
        div  = "─" * 54
        W    = 54

        def row(label, value):
            return f"  {label:<24}{value}"

        lines = [
            "=" * W,
            f"  Experiment Summary  —  {ts}".center(W),
            "=" * W,
            row("Experiment ID",    str(self._exp_id or "—")),
            row("Duration",         f"{duration:.1f} s"),
            row("Total frames",     str(len(self._frames))),
            div,
            "  FPS",
            row("  Average",        f"{avg_fps:.1f}"),
            row("  Max",            f"{max_fps:.1f}"),
            row("  Min",            f"{min_fps:.1f}"),
            div,
            "  UDP Transmission",
            row("  Sent OK",        str(self._udp_ok)),
            row("  Failed",         str(self._udp_fail)),
            row("  Success rate",   f"{udp_rate:.1f} %"),
            div,
            "  Gesture Lock Events",
        ]

        cmd_order = ["W", "S", "A", "D", "Q", "E"]
        for cmd in cmd_order:
            if cmd in cmd_counts:
                lines.append(row(f"  {cmd} activations", str(cmd_counts[cmd])))
        other = {k: v for k, v in cmd_counts.items() if k not in cmd_order}
        for k, v in sorted(other.items()):
            lines.append(row(f"  {k} activations", str(v)))

        lines += [
            row("  Avg lock time",  f"{avg_lock:.0f} ms"),
            div,
            "  Hand Tracking",
            row("  LOST events",    str(lost_count)),
            row("  Avg LOST dur.",  f"{avg_lost:.0f} ms"),
        ]

        if self._events:
            lines += [div, "  Manual Events"]
            for ev in self._events:
                lines.append(f"  +{ev['elapsed_s']:6.1f}s  {ev['description']}")

        lines += [
            div,
            row("  CSV",  csv_path),
            row("  TXT",  txt_path),
            "=" * W,
        ]

        summary = "\n".join(lines)
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(summary)

        print(summary)
        return summary
```


---

# core/watchdog_test.py

```python
"""
Watchdog response-time test for the omnidirectional robot base.

Protocol per trial:
  1. Send UDP 'Q' every 100 ms for 3 s  (robot rotates)
  2. Stop sending for 2 s               (simulate WiFi disconnect)
     → Pi watchdog fires ~500 ms into the silence
  3. Repeat 5 times

After all trials:
  - SSH to Pi, read /tmp/watchdog_log.txt
  - Parse "silent for Xms" from each WATCHDOG TRIGGERED line
  - Print summary table + save to logs/watchdog_results.txt
"""
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime

# ─────────────────────────────────────────
#  Config
# ─────────────────────────────────────────
PI_HOST       = "192.168.68.102"
PI_PORT       = 9000
PI_USER       = "imyanming"
PI_PASS       = "1234"
PI_SCRIPT     = f"/home/{PI_USER}/RobotAI_Project/core/pi_udp_omni.py"
LOCAL_SCRIPT  = os.path.join(os.path.dirname(__file__), '..', 'pi', 'pi_udp_omni.py')
WATCHDOG_LOG  = "/tmp/watchdog_log.txt"
RESULTS_DIR   = os.path.join(os.path.dirname(__file__), '..', 'logs')

TRIALS        = 5
SEND_SECS     = 3.0
SILENCE_SECS  = 2.0
SEND_INTERVAL = 0.10
BOUND_MS      = 600

_SSH_OPTS = ['-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=10',
             '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2']

# ─────────────────────────────────────────
#  SSH / SCP helpers
# ─────────────────────────────────────────
def _ssh(cmd, timeout=10):
    r = subprocess.run(
        ['sshpass', '-p', PI_PASS, 'ssh'] + _SSH_OPTS + [f'{PI_USER}@{PI_HOST}', cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.stdout

def _ssh_kill(cmd):
    """Run a kill command; ignore exit-255 (expected when target process dies)."""
    subprocess.run(
        ['sshpass', '-p', PI_PASS, 'ssh'] + _SSH_OPTS + [f'{PI_USER}@{PI_HOST}', cmd],
        capture_output=True, timeout=10,
    )

def _ssh_start(cmd, timeout=15):
    """Fire-and-forget: start a background process; SSH may not close cleanly — that's OK."""
    try:
        subprocess.run(
            ['sshpass', '-p', PI_PASS, 'ssh'] + _SSH_OPTS + [f'{PI_USER}@{PI_HOST}', cmd],
            capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pass  # process was already backgrounded on Pi; SSH just didn't exit cleanly

def _scp(local, remote, timeout=15):
    subprocess.run(
        ['sshpass', '-p', PI_PASS, 'scp'] + _SSH_OPTS + [local, f'{PI_USER}@{PI_HOST}:{remote}'],
        check=True, capture_output=True, timeout=timeout,
    )

# ─────────────────────────────────────────
#  Deploy + restart
# ─────────────────────────────────────────
def deploy_and_restart():
    print(f"  Uploading pi_udp_omni.py → {PI_HOST}:{PI_SCRIPT}")
    _scp(LOCAL_SCRIPT, PI_SCRIPT, timeout=15)

    print("  Stopping old pi_udp_omni.py process...")
    _ssh_kill('pkill -f pi_udp_omni.py; true')

    print("  Starting pi_udp_omni.py...")
    # </dev/null detaches stdin so the SSH session closes instead of hanging
    _ssh_start(f'cd /home/{PI_USER}/RobotAI_Project/core && nohup python3 pi_udp_omni.py </dev/null >/tmp/pi_udp_omni.log 2>&1 &')

    print("  Waiting 5s for process to start...")
    time.sleep(5)
    print("  Deploy done — continuing")

# ─────────────────────────────────────────
#  Trial loop
# ─────────────────────────────────────────
def run_trials():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for trial in range(1, TRIALS + 1):
            print(f"  Trial {trial}/{TRIALS}: "
                  f"sending Q for {SEND_SECS:.0f}s …", end='', flush=True)
            deadline = time.time() + SEND_SECS
            while time.time() < deadline:
                sock.sendto(b'Q', (PI_HOST, PI_PORT))
                time.sleep(SEND_INTERVAL)

            print(f" silent for {SILENCE_SECS:.0f}s …", end='', flush=True)
            time.sleep(SILENCE_SECS)
            print(" OK")
    finally:
        # Ensure motors stop even if an exception occurs mid-trial
        sock.sendto(b'SPACE', (PI_HOST, PI_PORT))
        sock.close()

# ─────────────────────────────────────────
#  Log parsing
# ─────────────────────────────────────────
def fetch_and_parse():
    time.sleep(0.4)   # let Pi flush the final log entry
    log_text = _ssh(f'cat {WATCHDOG_LOG}')
    # "WATCHDOG TRIGGERED at HH:MM:SS.mmm (silent for 523ms)"
    response_times = [int(m) for m in re.findall(r'silent for (\d+)ms', log_text)]
    return response_times, log_text

# ─────────────────────────────────────────
#  Summary + save
# ─────────────────────────────────────────
def report(response_times, log_text):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    mean_ms = round(sum(response_times) / len(response_times)) if response_times else 0
    all_ok  = all(ms <= BOUND_MS for ms in response_times)

    # Terminal output (with emoji)
    sep = "─" * 36
    print(f"\n{sep}")
    for i, ms in enumerate(response_times, 1):
        mark = "✅" if ms <= BOUND_MS else "❌"
        print(f"  Trial {i}: {ms}ms {mark}")
    print(sep)
    print(f"  Mean: {mean_ms}ms")
    print(f"  All within {BOUND_MS}ms bound: {'YES' if all_ok else 'NO'}")
    print(sep)

    # File output (plain text)
    file_rows = []
    for i, ms in enumerate(response_times, 1):
        mark = "PASS" if ms <= BOUND_MS else "FAIL"
        file_rows.append(f"  Trial {i}: {ms:>4}ms  [{mark}]")

    file_lines = [
        f"Watchdog Response-Time Test — {now_str}",
        f"Trials: {TRIALS}  |  Send: {SEND_SECS}s  |  Silence: {SILENCE_SECS}s  |  Bound: {BOUND_MS}ms",
        "─" * 44,
        *file_rows,
        "─" * 44,
        f"  Mean: {mean_ms}ms",
        f"  All within {BOUND_MS}ms bound: {'YES' if all_ok else 'NO'}",
        "",
        "--- Raw Pi watchdog log ---",
        log_text.rstrip(),
    ]

    fname = os.path.join(RESULTS_DIR, 'watchdog_results.txt')
    with open(fname, 'w') as f:
        f.write('\n'.join(file_lines) + '\n')
    print(f"\n  Results saved → {fname}")

# ─────────────────────────────────────────
#  Main
# ─────────────────────────────────────────
def main():
    sep = "=" * 36
    print(sep)
    print("  Watchdog Response-Time Test")
    print(sep)
    print()

    # 1. Deploy updated Pi script
    print("[1/4] Deploying pi_udp_omni.py …")
    deploy_and_restart()
    print()

    # 2. Clear Pi log
    print(f"[2/4] Clearing {WATCHDOG_LOG} on Pi …")
    _ssh(f'> {WATCHDOG_LOG}')
    print("  Done")
    print()

    # 3. Run trials
    print(f"[3/4] Running {TRIALS} trials …")
    run_trials()
    print()

    # 4. Fetch log, parse, report
    print(f"[4/4] Fetching {WATCHDOG_LOG} from Pi …")
    response_times, log_text = fetch_and_parse()

    if len(response_times) < TRIALS:
        print(f"  WARNING: expected {TRIALS} WATCHDOG entries, "
              f"got {len(response_times)}")
        print("  Raw log:\n", log_text or "  (empty)")
        if not response_times:
            sys.exit(1)

    report(response_times, log_text)


if __name__ == '__main__':
    main()
```

