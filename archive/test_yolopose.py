import cv2
from ultralytics import YOLO

print("🧠 載入 YOLOv8 Pose 模型中... (強制啟用 M5 MPS 加速)")
model = YOLO('yolov8n-pose.pt') 

print("📷 啟動 Mac 內建鏡頭...")
cap = cv2.VideoCapture(0)

while cap.isOpened():
    success, frame = cap.read()
    if not success:
        break
        
    # 照鏡子翻轉，確保你舉右手，畫面也是右手
    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape

    # 執行姿態預測
    results = model.predict(frame, device='mps', verbose=False)
    annotated_frame = results[0].plot() # 畫出全身彩色骨架

    # 🎮 虛擬搖桿核心邏輯
    if results[0].keypoints is not None and len(results[0].keypoints.xy[0]) > 10:
        # 抓取「右手腕」的座標 (索引 10)
        right_wrist = results[0].keypoints.xy[0][10]
        rx, ry = int(right_wrist[0]), int(right_wrist[1])
        
        # 如果右手腕有出現在畫面上 (座標不為 0)
        if rx != 0 and ry != 0:
            # 畫出一個超大的紅色瞄準心在你的右手腕上
            cv2.circle(annotated_frame, (rx, ry), 20, (0, 0, 255), -1)
            cv2.putText(annotated_frame, "JOYSTICK", (rx+25, ry), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

            # --- 判斷手腕位置來決定控制指令 ---
            # 假設把畫面分成左、中、右三區
            if rx < w // 3:
                action = "LEFT (A)"
            elif rx > 2 * (w // 3):
                action = "RIGHT (D)"
            elif ry < h // 3:
                action = "FORWARD (W)"
            else:
                action = "STOP (Space)"
                
            # 將目前的指令印在畫面左上角
            cv2.putText(annotated_frame, f"CMD: {action}", (20, 50), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 255), 4)

    # 畫出九宮格輔助線幫助你瞄準
    cv2.line(annotated_frame, (w//3, 0), (w//3, h), (255, 255, 255), 1)
    cv2.line(annotated_frame, (2*w//3, 0), (2*w//3, h), (255, 255, 255), 1)
    cv2.line(annotated_frame, (0, h//3), (w, h//3), (255, 255, 255), 1)

    cv2.imshow("Mac Brain - YOLO Pose Joystick", annotated_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
