import cv2
from ultralytics import YOLO

print("載入 YOLOv8 奈米模型中... (這可能需要幾秒鐘)")
# 它會自動幫你下載 yolov8n.pt 到資料夾中
model = YOLO('yolov8n.pt') 

print("啟動 Mac 內建鏡頭 (YOLOv8 物件偵測)...")
cap = cv2.VideoCapture(0)

while cap.isOpened():
    success, frame = cap.read()
    if not success:
        break
        
    frame = cv2.flip(frame, 1)

    # 執行預測，強制使用 M 系列晶片的 MPS 加速，並只抓「人」 (classes=[0])
    results = model.predict(frame, device='mps', verbose=False, classes=[0])
    
    # 取得 Bounding Box 資訊
    boxes = results[0].boxes
    
    for box in boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        conf = box.conf[0].item()
        
        # 畫出綠色追蹤框
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"Person {conf:.2f}", (x1, y1 - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    cv2.imshow("Mac Sandbox - YOLOv8 Tracker", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
