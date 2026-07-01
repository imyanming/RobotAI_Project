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
        print(f"[Logger] Experiment ID → {exp_id}")

    def mark_event(self, description: str = "MANUAL_EVENT") -> None:
        """Stamp a named event at the current timestamp."""
        if not self._recording:
            print("[Logger] Not recording — event mark ignored")
            return
        ts  = time.time()
        rel = ts - self._start_time
        self._events.append({'elapsed_s': round(rel, 3), 'description': description})
        print(f"[Logger] Event: {description}  (+{rel:.1f}s)")

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
            msg = "[Logger] No data recorded。"
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
              f"exp={self._exp_id or 'unset'}")

    def _stop(self) -> None:
        self._recording = False
        dur = time.time() - self._start_time
        print(f"[Logger] ■ STOP  {len(self._frames)} frames  {dur:.1f}s")

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
