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
from gesture_engine import GestureEngine, _classify, _CLUTCH_CMD
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
    "W":          "FORWARD ▲",     "S": "BACKWARD ▼",
    "A":          "STRAFE LEFT ◀", "D": "STRAFE RIGHT ▶",
    "Q":          "ROTATE CW ↻",   "E": "ROTATE CCW ↺",
    "SPACE":      "STOP",
    _CLUTCH_CMD:  "SYSTEM WAKE UP",
}

_STATE_COLOR = {
    "IDLE":     (150, 150, 150),
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
    ("SPACE",      "STOP",         "Fist — all fingers closed"),
    ("Q",          "ROTATE CW",    "Thumb only"),
    ("E",          "ROTATE CCW",   "Thumb + Index  (L-shape)"),
    ("W",          "FORWARD",      "Index finger only"),
    ("S",          "BACKWARD",     "Index + Middle"),
    ("A",          "STRAFE LEFT",  "3 fingers  (index, middle, ring)"),
    ("D",          "STRAFE RIGHT", "4 fingers  (index, middle, ring, pinky)"),
    (_CLUTCH_CMD,  "WAKE UP",      "Open palm — all 5 fingers"),
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
        return raw_cmd == self._target_cmd()

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