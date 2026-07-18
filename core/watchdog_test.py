"""
Watchdog response-time test for the omnidirectional robot base.

Protocol per trial:
  1. Send UDP 'Q' every 100 ms for 3 s  (robot rotates)
  2. Stop sending for 2 s               (halt transmission to simulate connectivity loss)
     → Pi watchdog fires ~500 ms into the silence
  3. Repeat 6 times

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
PI_HOST       = "192.168.68.103"
PI_PORT       = 9000
PI_USER       = "imyanming"
PI_PASS       = os.environ.get("PI_PASS", "")  # Set via: export PI_PASS=yourpassword
PI_SCRIPT     = f"/home/{PI_USER}/RobotAI_Project/core/pi_udp_omni.py"
LOCAL_SCRIPT  = os.path.join(os.path.dirname(__file__), '..', 'pi', 'pi_udp_omni.py')
WATCHDOG_LOG  = "/tmp/watchdog_log.txt"
RESULTS_DIR   = os.path.join(os.path.dirname(__file__), '..', 'logs')

TRIALS        = 6
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
    if not PI_PASS:
        print("ERROR: PI_PASS environment variable is not set.")
        print("Set it before running this script, e.g.:")
        print("  export PI_PASS=yourpassword")
        sys.exit(1)

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
