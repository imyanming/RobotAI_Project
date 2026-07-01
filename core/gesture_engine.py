"""
gesture_engine.py — Finger-count gesture classifier and latch state machine.

Classifies single-hand MediaPipe landmarks into one of eight commands, then
manages the IDLE / TRACKING / LOCKED / LOST state machine that prevents
unintentional motion (the 'Midas Touch' problem) by requiring an explicit
CLUTCH (open-palm) wake gesture before any motion command is accepted.
"""
TRANS_SPEED = 0.65
ROT_SPEED   = 0.30

_CONFIRM_FRAMES = 3   # consecutive frames to lock a new gesture
_LOST_THRESH    = 5   # absent frames before declaring LOST
_CLUTCH_CMD     = "__CLUTCH__"


class GestureEngine:
    """
    Finger-count static-pose gesture recogniser.

    update(hand_landmarks | None) → (cmd, speed)
    get_state()                   → "IDLE" | "TRACKING" | "LOCKED" | "LOST"

    Finger → command mapping
    ──────────────────────────────────────────────
    0  fingers  (fist)                      SPACE   stop / lock to IDLE
    thumb only                              E       CCW rotate
    thumb + index  (L-shape)                Q       CW  rotate
    index only                              W       forward
    index + middle                          S       backward
    index + middle + ring                   A       strafe left
    index + middle + ring + pinky           D       strafe right
    all 5 fingers                           CLUTCH  wake up from IDLE

    States
    ──────
    IDLE      system asleep, ignores all gestures except CLUTCH (all 5 fingers)
    TRACKING  hand present, system awake, no movement command locked yet
    LOCKED    a command is active (hand present or brief absence ≤ LOST_THRESH)
    LOST      hand absent > LOST_THRESH frames; locked cmd still sent
    """

    def __init__(self):
        self.state         = 'IDLE'
        self._locked_cmd   = "SPACE"
        self._locked_speed = 0.0
        self._pending      = None
        self._streak       = 0
        self._lost_frames  = 0

    # ── public ──────────────────────────────────────────────────────

    def get_debug_info(self) -> dict:
        """Return internal state for logging / HUD display."""
        return {
            'state':       self.state,
            'pending':     self._pending,
            'streak':      self._streak,
            'lost_frames': self._lost_frames,
        }

    def reset(self):
        """Full reset — for program startup only."""
        self.state         = 'IDLE'
        self._locked_cmd   = "SPACE"
        self._locked_speed = 0.0
        self._pending      = None
        self._streak       = 0
        self._lost_frames  = 0

    def get_state(self) -> str:
        if self.state == 'IDLE':
            return "IDLE"
        if self._lost_frames >= _LOST_THRESH:
            return "LOST"
        if self._lost_frames > 0 or self._locked_cmd != "SPACE":
            return "LOCKED"
        return self.state

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

        if raw_cmd == self._pending:
            self._streak += 1
        else:
            self._pending = raw_cmd
            self._streak  = 1

        if self._streak >= _CONFIRM_FRAMES:
            confirmed_gesture = raw_cmd
            confirmed_speed = raw_speed
            self._streak = _CONFIRM_FRAMES

            if self.state == 'IDLE':
                if confirmed_gesture == _CLUTCH_CMD:
                    self.state = 'TRACKING'
                    print("System Awakened!")
                self._locked_cmd = "SPACE"
                self._locked_speed = 0.0
                return 'SPACE', 0.0

            else:
                if confirmed_gesture == 'SPACE':  # Fist confirmed: force-stop and return to IDLE
                    self.state = 'IDLE'
                    self._locked_cmd = "SPACE"
                    self._locked_speed = 0.0
                    print("System Locked (IDLE).")
                    return 'SPACE', 0.0

                elif confirmed_gesture == _CLUTCH_CMD:
                    # Open palm while already awake: stay in TRACKING
                    return 'SPACE', 0.0

                self._locked_cmd   = confirmed_gesture
                self._locked_speed = confirmed_speed
                if self.state == 'TRACKING':
                    self.state = 'LOCKED'

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
        return _CLUTCH_CMD, 0.0

    if (t, i, m, r, p) == (True,  False, False, False, False):
        return "E", ROT_SPEED

    if (t, i, m, r, p) == (True,  True,  False, False, False):
        return "Q", ROT_SPEED

    if (t, i, m, r, p) == (False, True,  False, False, False):
        return "W", TRANS_SPEED

    if (t, i, m, r, p) == (False, True,  True,  False, False):
        return "S", TRANS_SPEED

    if (t, i, m, r, p) == (False, True,  True,  True,  False):
        return "A", TRANS_SPEED

    if (t, i, m, r, p) == (False, True,  True,  True,  True):
        return "D", TRANS_SPEED

    return None, None