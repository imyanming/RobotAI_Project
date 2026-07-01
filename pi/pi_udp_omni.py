"""
pi_udp_omni.py — Edge-side UDP command receiver and motor controller.

Runs on the Raspberry Pi only. Listens for single-character ASCII commands
(W/S/A/D/Q/E/SPACE) over UDP from the Host (Mac), drives the four Mecanum
wheels accordingly via gpiozero, and implements the two lower safety layers
described in the paper:
  - Motor safe-transition guard: safe_transition() always fully stops all
    motors and waits briefly before reversing direction, so an abrupt
    forward<->backward gesture change cannot reverse the H-bridges instantly.
  - UDP watchdog: watchdog_thread() independently monitors time since the
    last received command and force-stops the robot if that exceeds
    WATCHDOG_TIMEOUT, regardless of what the Host is doing — this is what
    halts the robot within ~533 ms of a Wi-Fi disconnect or Host crash.

Kept as a separate OS process from pi_fast_stream.py (video) so that a crash
or stall in the non-safety-critical video path can never block this process
from stopping the motors.
"""
from gpiozero import Motor
import socket
import threading
from time import sleep, time
from datetime import datetime

# ─────────────────────────────────────────
#  Motor initialization
#  Mecanum chassis layout: M1=front, M2=left, M3=back, M4=right.
#  Each Motor() pin pair drives one wheel's H-bridge in PWM mode.
# ─────────────────────────────────────────
motor_list = [
    ("M1 front", Motor(forward=5,  backward=6,  pwm=True, enable=12)),
    ("M2 left", Motor(forward=26, backward=16, pwm=True, enable=13)),
    ("M3 back", Motor(forward=23, backward=24, pwm=True, enable=18)),
    ("M4 right", Motor(forward=25, backward=27, pwm=True, enable=19)),
]

m1_front = motor_list[0][1]
m2_left  = motor_list[1][1]
m3_back  = motor_list[2][1]
m4_right = motor_list[3][1]

TRANS_SPEED      = 0.65   # Linear (forward/back/strafe) drive duty cycle
ROT_SPEED        = 0.30   # Rotation duty cycle
UDP_PORT         = 9000
WATCHDOG_TIMEOUT = 0.5    # Seconds of silence before the watchdog force-stops

CMD_LOG      = "/tmp/omni.log"
WATCHDOG_LOG = "/tmp/watchdog_log.txt"

# ─────────────────────────────────────────
#  Logging helpers
# ─────────────────────────────────────────
def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def _ts_hms():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def log_cmd(addr, cmd):
    line = f"[{_ts()}] CMD {cmd} from {addr}\n"
    with open(CMD_LOG, "a") as f:
        f.write(line)

def log_watchdog(silence_ms):
    line = f"WATCHDOG TRIGGERED at {_ts_hms()} (silent for {silence_ms}ms)\n"
    with open(WATCHDOG_LOG, "a") as f:
        f.write(line)
    print(f"🛡️  {line.strip()}")

def log_recovered():
    line = f"RECOVERED at {_ts_hms()}\n"
    with open(WATCHDOG_LOG, "a") as f:
        f.write(line)
    print(f"🔄  {line.strip()}")

# ─────────────────────────────────────────
#  Motor control functions (speed-parameterised)
#  Only M2 (left) and M4 (right) drive translation; M1/M3 only engage
#  together with M2/M4 for rotation, matching this chassis's 4-wheel layout.
# ─────────────────────────────────────────
def all_stop():
    for _, motor in motor_list:
        motor.stop()

def safe_transition():
    # Motor safe-transition guard (dependability layer #2): always fully
    # de-energise all four motors and pause briefly before issuing a new
    # direction. Without this, an instantaneous forward->backward command
    # would reverse the H-bridges while still under load, which is the
    # usual cause of motor-driver damage on cheap L298N boards.
    all_stop()
    sleep(0.08)

def move_forward(spd):
    safe_transition()
    m2_left.backward(spd)
    m4_right.forward(spd)

def move_backward(spd):
    safe_transition()
    m2_left.forward(spd)
    m4_right.backward(spd)

def move_left(spd):
    safe_transition()
    m1_front.backward(spd)
    m3_back.forward(spd)

def move_right(spd):
    safe_transition()
    m1_front.forward(spd)
    m3_back.backward(spd)

def rotate_cw(spd):
    safe_transition()
    m1_front.backward(spd)
    m2_left.forward(spd)
    m3_back.backward(spd)
    m4_right.forward(spd)

def rotate_ccw(spd):
    safe_transition()
    m1_front.forward(spd)
    m2_left.backward(spd)
    m3_back.forward(spd)
    m4_right.backward(spd)

# Command → (function, speed)
CMD_MAP = {
    "W": (move_forward,  TRANS_SPEED),
    "S": (move_backward, TRANS_SPEED),
    "A": (move_left,     TRANS_SPEED),
    "D": (move_right,    TRANS_SPEED),
    "Q": (rotate_cw,     ROT_SPEED),
    "E": (rotate_ccw,    ROT_SPEED),
}

# ─────────────────────────────────────────
#  Watchdog: dependability layer #1 — auto-stop on communication loss.
#  Runs on its own daemon thread, independent of the UDP recv loop in
#  main(), so it keeps firing even if the Host stops sending entirely
#  (Wi-Fi drop, Host crash, etc.) rather than relying on a timeout inside
#  the blocking recvfrom() call below.
# ─────────────────────────────────────────
last_recv_time  = time()
watchdog_active = True
last_cmd        = ""
_watchdog_fired = False   # edge-trigger: log only on transition to fired state

def watchdog_thread():
    global watchdog_active, last_cmd, _watchdog_fired
    while watchdog_active:
        if time() - last_recv_time > WATCHDOG_TIMEOUT:
            if not _watchdog_fired:
                # Log only once per silence episode (edge-triggered), not
                # every 100ms poll while still silent.
                silence_ms = int((time() - last_recv_time) * 1000)
                log_watchdog(silence_ms)
                _watchdog_fired = True
            all_stop()
            last_cmd = ""
        else:
            _watchdog_fired = False
        sleep(0.1)

# ─────────────────────────────────────────
#  Main: UDP receive loop
# ─────────────────────────────────────────
def main():
    global last_recv_time, watchdog_active, last_cmd, _watchdog_fired

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', UDP_PORT))
    sock.settimeout(1.0)

    wd = threading.Thread(target=watchdog_thread, daemon=True)
    wd.start()

    print(f"pi_udp_omni started, listening on UDP port {UDP_PORT}")
    print(f"Translation: {int(TRANS_SPEED*100)}%  Rotation: {int(ROT_SPEED*100)}%  "
          f"Watchdog timeout: {WATCHDOG_TIMEOUT}s")
    print(f"CMD log      → {CMD_LOG}")
    print(f"Watchdog log → {WATCHDOG_LOG}")
    print("──────────────────────────────────────────")
    print("  Commands: W / S / A / D / Q / E / SPACE")
    print("──────────────────────────────────────────")

    labels = {
        "W": "Forward",    "S": "Backward",
        "A": "Strafe L",   "D": "Strafe R",
        "Q": "Rotate CW",  "E": "Rotate CCW",
        "SPACE": "Stop",
    }

    try:
        while True:
            try:
                data, addr = sock.recvfrom(64)
            except socket.timeout:
                continue

            cmd = data.decode().strip().upper()
            # Snapshot _watchdog_fired before touching last_recv_time: if the
            # watchdog had fired, this packet is the first one received after
            # a disconnect, so we log a RECOVERED event below.
            recovering = _watchdog_fired
            last_recv_time = time()
            log_cmd(addr[0], cmd)

            if recovering:
                log_recovered()
                _watchdog_fired = False

            # ── Dispatch command ────────────────────────────────────
            if cmd == "SPACE":
                all_stop()
                if last_cmd != "SPACE":
                    last_cmd = "SPACE"
                    print(f"[{addr[0]}] {labels['SPACE']}")

            elif cmd in CMD_MAP:
                if cmd != last_cmd:
                    fn, spd = CMD_MAP[cmd]
                    fn(spd)
                    last_cmd = cmd
                    print(f"[{addr[0]}] {labels.get(cmd, cmd)}")

    except KeyboardInterrupt:
        print("\nCtrl+C — emergency stop, halting all motors")
    finally:
        watchdog_active = False
        all_stop()
        sock.close()
        print("All motors stopped safely.")

if __name__ == "__main__":
    main()
