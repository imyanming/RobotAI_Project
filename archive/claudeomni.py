from gpiozero import Motor
import socket
import threading
from time import sleep, time

# ─────────────────────────────────────────
#  馬達初始化
# ─────────────────────────────────────────
motor_list = [
    ("M1 前", Motor(forward=5,  backward=6,  pwm=True, enable=12)),
    ("M2 左", Motor(forward=26, backward=16, pwm=True, enable=13)),
    ("M3 後", Motor(forward=23, backward=24, pwm=True, enable=18)),
    ("M4 右", Motor(forward=25, backward=27, pwm=True, enable=19)),
]
m1_front = motor_list[0][1]
m2_left  = motor_list[1][1]
m3_back  = motor_list[2][1]
m4_right = motor_list[3][1]

UDP_PORT         = 9000
WATCHDOG_TIMEOUT = 0.5

# 檔位 → PWM 速度
GEAR_TO_SPEED = {0: 0.0, 1: 0.20, 2: 0.35, 3: 0.50, 4: 0.70, 5: 0.90}

# ─────────────────────────────────────────
#  馬達控制
# ─────────────────────────────────────────
def all_stop():
    for _, m in motor_list:
        m.stop()

def safe_transition():
    all_stop()
    sleep(0.08)

def move_forward(speed):
    safe_transition()
    m2_left.backward(speed)
    m4_right.forward(speed)

def move_backward(speed):
    safe_transition()
    m2_left.forward(speed)
    m4_right.backward(speed)

def move_left(speed):
    safe_transition()
    m1_front.backward(speed)
    m3_back.forward(speed)

def move_right(speed):
    safe_transition()
    m1_front.forward(speed)
    m3_back.backward(speed)

def rotate_cw(speed):
    safe_transition()
    m1_front.backward(speed)
    m2_left.forward(speed)
    m3_back.backward(speed)
    m4_right.forward(speed)

def rotate_ccw(speed):
    safe_transition()
    m1_front.forward(speed)
    m2_left.backward(speed)
    m3_back.forward(speed)
    m4_right.backward(speed)

# ─────────────────────────────────────────
#  指令解析："W_3" → ("W", 0.50)
# ─────────────────────────────────────────
def parse_cmd(msg):
    msg = msg.strip().upper()
    if "_" in msg:
        parts = msg.split("_", 1)
        cmd = parts[0]
        try:
            gear = max(0, min(5, int(parts[1])))
        except ValueError:
            gear = 3
    else:
        cmd  = msg
        gear = 3
    return cmd, GEAR_TO_SPEED[gear]

CMD_MAP = {
    "W": move_forward, "S": move_backward,
    "A": move_left,    "D": move_right,
    "Q": rotate_cw,    "E": rotate_ccw,
    "SPACE": None,
}
LABELS = {
    "W": "⬆️  前進", "S": "⬇️  後退",
    "A": "⬅️  左移", "D": "➡️  右移",
    "Q": "↻  順時針", "E": "↺  逆時針",
    "SPACE": "🛑  停止",
}

# ─────────────────────────────────────────
#  看門狗
# ─────────────────────────────────────────
last_recv_time  = time()
watchdog_active = True

def watchdog_thread():
    while watchdog_active:
        if time() - last_recv_time > WATCHDOG_TIMEOUT:
            all_stop()
        sleep(0.1)

# ─────────────────────────────────────────
#  主程式
# ─────────────────────────────────────────
def main():
    global last_recv_time, watchdog_active

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', UDP_PORT))
    sock.settimeout(1.0)

    threading.Thread(target=watchdog_thread, daemon=True).start()

    print(f"🛡️  pi_udp_omni 啟動，監聽 UDP Port {UDP_PORT}")
    print(f"📶 支援格式：'W_5'（新版）或 'W'（舊版）")
    print(f"⏱️  斷線煞車：{WATCHDOG_TIMEOUT}s")
    print("──────────────────────────────────────")

    last_cmd = ""

    try:
        while True:
            try:
                data, addr = sock.recvfrom(64)
            except socket.timeout:
                continue

            raw = data.decode().strip()
            last_recv_time = time()

            # ← 這行很重要：確認封包有到
            print(f"[收到] {addr[0]} → '{raw}'")

            cmd, speed = parse_cmd(raw)

            if cmd not in CMD_MAP:
                print(f"  ⚠️  未知指令: {cmd}")
                continue

            if cmd == "SPACE" or speed == 0.0:
                if last_cmd != "SPACE":
                    all_stop()
                    last_cmd = "SPACE"
                    print(f"  🛑  停止")
                continue

            if cmd == last_cmd:
                continue

            CMD_MAP[cmd](speed)
            last_cmd = cmd
            print(f"  {LABELS.get(cmd, cmd)}  速度 {int(speed*100)}%")

    except KeyboardInterrupt:
        print("\n⚠️  Ctrl+C")
    finally:
        watchdog_active = False
        all_stop()
        sock.close()
        print("✅ 馬達已安全關閉")

if __name__ == "__main__":
    main()
