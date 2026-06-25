import cv2
import numpy as np
import requests
import threading
import time
import mediapipe as mp
import socket
from gesture_engine import GestureEngine

# ─────────────────────────────────────────
#  網路與通訊設定
# ─────────────────────────────────────────
STREAM_URL   = "http://192.168.68.105:8000/stream.mjpg"
PI_HOST      = "192.168.68.105"
PI_PORT      = 9000
UDP_INTERVAL = 0.10      # s — 每 100ms 送一次指令，減少 Pi 負擔
MAX_BUF      = 65536     # bytes — stream buffer 上限，防延遲堆積

# ─────────────────────────────────────────
#  戰車 FPV 串流接收器
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
                # buffer 過大 → 丟棄舊資料，只保留最新幀起始處
                if len(buf) > MAX_BUF:
                    last_soi = buf.rfind(b'\xff\xd8')
                    buf = buf[last_soi:] if last_soi != -1 else b''
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
#  UDP 指令傳送器（固定間隔，不重複計時）
# ─────────────────────────────────────────
class CommandSender:
    def __init__(self, host, port):
        self.addr    = (host, port)
        self.sock    = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._last_t = 0

    def send(self, cmd):
        now = time.time()
        if now - self._last_t >= UDP_INTERVAL:
            try:
                self.sock.sendto(cmd.encode(), self.addr)
                self._last_t = now
            except:
                pass

# ─────────────────────────────────────────
#  指令顯示文字
# ─────────────────────────────────────────
_LABEL = {
    "W": "FORWARD ▲",  "S": "BACKWARD ▼",
    "A": "STRAFE LEFT ◀", "D": "STRAFE RIGHT ▶",
    "Q": "ROTATE RIGHT ↻", "E": "ROTATE LEFT ↺",
    "SPACE": "STOP",
}

# ─────────────────────────────────────────
#  主程式：單手靜態姿勢辨識版本
# ─────────────────────────────────────────
def main():
    print("🧠 載入 MediaPipe 單手追蹤模型...")
    mp_hands = mp.solutions.hands
    hands    = mp_hands.Hands(
        static_image_mode=False, max_num_hands=1,
        min_detection_confidence=0.7, min_tracking_confidence=0.6)
    mp_draw  = mp.solutions.drawing_utils
    engine   = GestureEngine()

    print("📷 啟動 Mac 視訊鏡頭...")
    mac_cam = cv2.VideoCapture(0)

    print("📡 啟動戰車 FPV 串流...")
    tank_stream = RequestsStream(STREAM_URL)
    sender      = CommandSender(PI_HOST, PI_PORT)

    BG_W, BG_H   = 960, 720
    PIP_W, PIP_H = 320, 240

    cmd, speed = "SPACE", 0.0   # 鎖定狀態：手離開時持續送上一個指令
    show_stream = True          # V 鍵切換：True=FPV串流 / False=純手勢黑底

    fps, fps_n, fps_t = 0, 0, time.time()

    while True:
        # 1. Mac 鏡頭
        ret, mac_frame = mac_cam.read()
        if not ret: continue
        mac_frame = cv2.flip(mac_frame, 1)

        # 2. 主畫面背景
        if show_stream:
            ok, tank_frame = tank_stream.read()
            if ok:
                main_bg = cv2.resize(tank_frame, (BG_W, BG_H))
            else:
                main_bg = np.zeros((BG_H, BG_W, 3), dtype=np.uint8)
                cv2.putText(main_bg, "WAITING FOR TANK FPV...", (300, 360),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        else:
            # 純手勢模式：黑底 + 大字狀態，跳過串流解碼降低 CPU
            main_bg = np.zeros((BG_H, BG_W, 3), dtype=np.uint8)
            lbl   = _LABEL.get(cmd, cmd)
            spd_t = f"{speed:.0%}" if cmd != "SPACE" else ""
            clr   = ((50, 255, 100) if cmd in ("W", "S") else
                     (255, 220, 50) if cmd in ("A", "D", "Q", "E") else
                     (200, 200, 200))
            cv2.putText(main_bg, lbl,  (BG_W//2 - 200, BG_H//2 - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 2.2, clr, 4)
            cv2.putText(main_bg, spd_t, (BG_W//2 - 60, BG_H//2 + 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, clr, 3)
            cv2.putText(main_bg, "[ V ] stream on",
                        (BG_W//2 - 130, BG_H - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)

        # 3. 手勢辨識（單手靜態姿勢）
        results = hands.process(cv2.cvtColor(mac_frame, cv2.COLOR_BGR2RGB))

        if results.multi_hand_landmarks:
            hand_lm = results.multi_hand_landmarks[0]
            mp_draw.draw_landmarks(mac_frame, hand_lm, mp_hands.HAND_CONNECTIONS)
            cmd, speed = engine.update(hand_lm)
        # 手離開鏡頭：保持 cmd/speed 不變，只有握拳或新手勢才改變

        sender.send(cmd)

        # 4. PIP 畫面合成
        pip = cv2.resize(mac_frame, (PIP_W, PIP_H))
        main_bg[BG_H-PIP_H-20:BG_H-20, BG_W-PIP_W-20:BG_W-20] = pip
        cv2.rectangle(main_bg,
                      (BG_W-PIP_W-20, BG_H-PIP_H-20), (BG_W-20, BG_H-20),
                      (0, 255, 255), 2)
        cv2.putText(main_bg, "MAC SENSOR",
                    (BG_W-PIP_W-15, BG_H-PIP_H-25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # 5. 狀態列 + FPS
        fps_n += 1
        if time.time() - fps_t >= 1.0:
            fps, fps_n, fps_t = fps_n, 0, time.time()

        label      = _LABEL.get(cmd, cmd)
        speed_text = f"  {speed:.0%}" if cmd != "SPACE" else ""
        text_color = ((50, 255, 100)  if cmd in ("W", "S") else
                      (255, 220, 50)  if cmd in ("A", "D", "Q", "E") else
                      (255, 255, 255))

        cv2.rectangle(main_bg, (0, 0), (BG_W, 50), (20, 20, 20), -1)
        if not show_stream:
            cv2.putText(main_bg, "MODE: GESTURE ONLY", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 180, 255), 2)
        else:
            cv2.putText(main_bg, f"STATUS: {label}{speed_text}", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, text_color, 2)
        cv2.putText(main_bg, f"{fps} FPS", (BG_W - 115, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (140, 140, 140), 1)

        cv2.imshow("Telepresence Command Center", main_bg)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord('v'):
            show_stream = not show_stream
            if show_stream:
                # 重新啟動串流
                tank_stream = RequestsStream(STREAM_URL)
                print("📡 串流模式")
            else:
                # 停止串流，釋放資源
                tank_stream.release()
                print("🖐  純手勢模式")

    mac_cam.release()
    tank_stream.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
