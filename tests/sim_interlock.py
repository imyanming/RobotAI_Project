"""
sim_interlock.py — Software verification of the edge node's restart interlock.

Runs the real pi/pi_udp_omni.py (unmodified) on any PC: gpiozero.Motor is
replaced by a recorder, while UDP traffic (localhost) and watchdog timing are
real. Scenario:
  1. Pi starts while the Host is already sending W   → must not move
  2. SPACE (fist), then W                            → drives forward
  3. 1.2 s of silence (Wi-Fi drop)                   → watchdog all-stop
  4. Link returns, Host still retransmits W          → must NOT resume
  5. SPACE, then Q                                   → rotates (CW pattern)
  6. Watchdog log contains TRIGGERED and RECOVERED

Usage:
  python tests/sim_interlock.py                      # current pi_udp_omni.py
  python tests/sim_interlock.py path/to/other.py     # e.g. the experiment-2026-06 version

Exit code 0 if all checks pass. Takes about 7 s.
"""
import importlib.util
import os
import socket
import sys
import tempfile
import threading
import time
import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")   # the Pi program prints arrows/emoji

calls = []   # (time, motor, action)
lock  = threading.Lock()

class FakeMotor:
    """Stand-in for gpiozero.Motor that records every call."""
    def __init__(self, forward, backward, pwm=True, enable=None):
        self.name = f"pin{forward}"
    def forward(self, spd):  self._rec("fwd")
    def backward(self, spd): self._rec("bwd")
    def stop(self):          self._rec("stop")
    def _rec(self, action):
        with lock:
            calls.append((time.time(), self.name, action))

gz = types.ModuleType("gpiozero")
gz.Motor = FakeMotor
sys.modules["gpiozero"] = gz

target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "pi", "pi_udp_omni.py")
spec = importlib.util.spec_from_file_location("omni", target)
omni = importlib.util.module_from_spec(spec)
spec.loader.exec_module(omni)

tmp = tempfile.mkdtemp()
omni.CMD_LOG      = os.path.join(tmp, "omni.log")
omni.WATCHDOG_LOG = os.path.join(tmp, "watchdog_log.txt")
names = {m.name: label.split()[1] for label, m in omni.motor_list}   # pin5 -> front

threading.Thread(target=omni.main, daemon=True).start()
time.sleep(0.3)
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_for(cmd, secs):
    # Mimic the Host: one packet every 100 ms
    end = time.time() + secs
    while time.time() < end:
        tx.sendto(cmd.encode(), ("127.0.0.1", omni.UDP_PORT))
        time.sleep(0.1)

def drives_since(t0):
    with lock:
        return [(names[m], a) for (t, m, a) in calls if t >= t0 and a != "stop"]

results = []
def check(label, ok):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}")

t = time.time(); send_for("W", 0.6)
check("startup: W without prior SPACE is ignored", drives_since(t) == [])

send_for("SPACE", 0.3); t = time.time(); send_for("W", 0.6)
check("after SPACE, W drives forward",
      sorted(set(drives_since(t))) == [("left", "bwd"), ("right", "fwd")])

t = time.time(); time.sleep(1.2)
with lock:
    stops = [a for (tt, m, a) in calls if tt >= t and a == "stop"]
check("silence triggers watchdog all_stop", len(stops) >= 4)

t = time.time(); send_for("W", 1.0)
check("after reconnect, retransmitted W is ignored (no auto-resume)", drives_since(t) == [])

send_for("SPACE", 0.3); t = time.time(); send_for("Q", 0.6)
check("after SPACE, Q rotates with the CW motor pattern",
      sorted(set(drives_since(t))) == [("back", "bwd"), ("front", "bwd"), ("left", "fwd"), ("right", "fwd")])

log = open(omni.WATCHDOG_LOG).read()
check("watchdog log written (TRIGGERED + RECOVERED)",
      "WATCHDOG TRIGGERED" in log and "RECOVERED" in log)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
