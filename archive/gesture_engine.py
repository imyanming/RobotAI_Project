TRANS_SPEED = 0.6
ROT_SPEED   = 0.35

_CONFIRM_FRAMES = 3   # consecutive frames required before committing a gesture
_BOOST_CMD      = "__BOOST__"


class GestureEngine:
    """
    Finger-count gesture recogniser — no trajectory tracking.

    Finger combination → command mapping
    ─────────────────────────────────────
    0  fingers (fist)                       → SPACE  (stop)
    thumb only                              → E      (CCW rotate)
    thumb + index                           → Q      (CW  rotate)
    index only                              → W      (forward)
    index + middle                          → S      (backward)
    index + middle + ring                   → A      (strafe left)
    index + middle + ring + pinky           → D      (strafe right)
    all 5 fingers                           → BOOST  (hold direction, speed → 100 %)

    Unrecognised combinations hold the current locked state.

    Confirmation: same gesture must appear CONFIRM_FRAMES consecutive frames
    before it commits.  Once committed the command is latched until changed.
    """

    def __init__(self):
        self._locked_cmd   = "SPACE"
        self._locked_speed = 0.0
        self._pending      = None
        self._streak       = 0

    # ── public ──────────────────────────────────────────────────────

    def reset(self):
        """Full reset — call at program startup only."""
        self._locked_cmd   = "SPACE"
        self._locked_speed = 0.0
        self._pending      = None
        self._streak       = 0

    def update(self, hand_landmarks) -> tuple:
        """Process one frame.  Returns (command: str, speed: float)."""
        lm = hand_landmarks.landmark

        raw_cmd, raw_speed = _classify(lm)

        # Unrecognised pose → freeze locked state, reset streak
        if raw_cmd is None:
            self._pending = None
            self._streak  = 0
            return self._locked_cmd, self._locked_speed

        # 5-finger boost: resolve to current locked direction at full speed
        if raw_cmd == _BOOST_CMD:
            raw_cmd   = self._locked_cmd
            raw_speed = 1.0 if self._locked_cmd != "SPACE" else 0.0

        # Confirmation gate
        if raw_cmd == self._pending:
            self._streak += 1
        else:
            self._pending = raw_cmd
            self._streak  = 1

        if self._streak >= _CONFIRM_FRAMES:
            self._locked_cmd   = raw_cmd
            self._locked_speed = raw_speed
            self._streak       = _CONFIRM_FRAMES   # clamp to avoid overflow

        return self._locked_cmd, self._locked_speed


# ── classifier ────────────────────────────────────────────────────────────────

def _ext(lm):
    """
    Return (thumb, index, middle, ring, pinky) booleans for finger extension.

    Thumb : tip(4) x-distance from wrist(0) exceeds ip(3) x-distance.
    Others: tip.y < pip.y  (tip above PIP joint in screen coordinates).
    """
    thumb  = abs(lm[4].x - lm[0].x) > abs(lm[3].x - lm[0].x) * 1.1
    index  = lm[8].y  < lm[6].y
    middle = lm[12].y < lm[10].y
    ring   = lm[16].y < lm[14].y
    pinky  = lm[20].y < lm[18].y
    return thumb, index, middle, ring, pinky


def _classify(lm):
    """
    Map landmark geometry to (cmd, speed).
    Returns (None, None) for unrecognised combinations.
    """
    t, i, m, r, p = _ext(lm)

    # ── fist ──────────────────────────────────────────────────────────
    if not any((t, i, m, r, p)):
        return "SPACE", 0.0

    # ── all 5 → boost ─────────────────────────────────────────────────
    if all((t, i, m, r, p)):
        return _BOOST_CMD, 1.0

    # ── rotation (thumb-based) ────────────────────────────────────────
    if (t, i, m, r, p) == (True,  False, False, False, False):
        return "E", ROT_SPEED              # thumb only  → CCW

    if (t, i, m, r, p) == (True,  True,  False, False, False):
        return "Q", ROT_SPEED              # thumb + index → CW

    # ── translation (index-finger chain, no thumb) ────────────────────
    if (t, i, m, r, p) == (False, True,  False, False, False):
        return "W", TRANS_SPEED            # index only

    if (t, i, m, r, p) == (False, True,  True,  False, False):
        return "S", TRANS_SPEED            # index + middle

    if (t, i, m, r, p) == (False, True,  True,  True,  False):
        return "A", TRANS_SPEED            # index + middle + ring

    if (t, i, m, r, p) == (False, True,  True,  True,  True):
        return "D", TRANS_SPEED            # index + middle + ring + pinky

    return None, None                      # unrecognised
