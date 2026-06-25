import cv2
import numpy as np
import requests
import threading
import time
import mediapipe as mp

STREAM_URL = "http://192.168.68.105:8000/stream.mjpg"

class RequestsStream:
    def __init__(self, url):
        self.url = url
        self.frame = None
        self.running = True
        self.thread = threading.Thread(target=self.update)
        self.thread.daemon = True
        self.thread.start()

    def update(self):
        try:
            print("🔗 正在敲門，等待樹莓派相機暖機 (約需 3-5 秒)...")
            res = requests.get(self.url, stream=True, timeout=10)
            byte_buffer = b''
            
            for chunk in res.iter_content(chunk_size=4096):
                if not self.running:
                    break
                byte_buffer += chunk
                
                a = byte_buffer.find(b'\xff\xd8')
                b = byte_buffer.find(b'\xff\xd9')
                
                if a != -1 and b != -1 and b > a:
                    jpg = byte_buffer[a:b+2]
                    byte_buffer = byte_buffer[b+2:] 
                    
                    img_array = np.frombuffer(jpg, dtype=np.uint8)
                    decoded = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if decoded is not None:
                        # 鏡像翻轉，操作起來才像照鏡子
                        self.frame = cv2.flip(decoded, 1)
        except Exception as e:
            print(f"⚠️ 網路串流中斷: {e}")

    def read(self):
        if self.frame is not None:
            return True, self.frame.copy()
        return False, None

    def release(self):
        self.running = False

def main():
    print("🧠 載入 MediaPipe Hands 模型中...")
    
    # 穩定版可以直接用最標準的 mp.solutions 寫法！
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.7
    )
    mp_draw = mp.solutions.drawing_utils

    print(f"📡 啟提現代化零延遲接收器...")
    stream = RequestsStream(STREAM_URL)
    
    wait_time = 0
    while stream.frame is None and wait_time < 100: 
        time.sleep(0.1)
        wait_time += 1
        
    if stream.frame is None:
        print("⚠️ 無法連線！請按 Ctrl+C 重啟樹莓派程式。")
        return

    print("✅ 大腦與眼睛連接成功！開始極速分析... (按 Q 鍵退出)")

    history_cx = []
    history_cy = []
    MAX_HISTORY = 3 

    while True:
        success, frame = stream.read()
        if not success:
            continue
            
        h, w, _ = frame.shape
        
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(img_rgb)

        action = "STOP (Space) - No Hand"

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                mp_draw.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)
                
                # 抓取中指根部
                cx = int(hand_landmarks.landmark[9].x * w)
                cy = int(hand_landmarks.landmark[9].y * h)
                
                history_cx.append(cx)
                history_cy.append(cy)
                if len(history_cx) > MAX_HISTORY:
                    history_cx.pop(0)
                    history_cy.pop(0)
                    
                smooth_cx = int(np.mean(history_cx))
                smooth_cy = int(np.mean(history_cy))
                
                cv2.circle(frame, (smooth_cx, smooth_cy), 15, (0, 255, 0), -1)
                cv2.putText(frame, "JOYSTICK", (smooth_cx+20, smooth_cy-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                if smooth_cx < w // 3:
                    action = "LEFT (A)"
                elif smooth_cx > 2 * (w // 3):
                    action = "RIGHT (D)"
                elif smooth_cy < h // 3:
                    action = "FORWARD (W)"
                else:
                    action = "STOP (Space) - Center"
        else:
            history_cx.clear()
            history_cy.clear()

        cv2.putText(frame, f"CMD: {action}", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 3)
        cv2.line(frame, (w//3, 0), (w//3, h), (255, 255, 255), 1)
        cv2.line(frame, (2*w//3, 0), (2*w//3, h), (255, 255, 255), 1)
        cv2.line(frame, (0, h//3), (w, h//3), (255, 255, 255), 1)

        cv2.imshow("Mac Brain - MediaPipe Hand Control", frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    stream.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
