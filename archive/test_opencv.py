import cv2
import numpy as np

print("啟動 Mac 內建鏡頭 (OpenCV 顏色追蹤)...")
cap = cv2.VideoCapture(0) # 0 代表 Mac 內建鏡頭

# 設定追蹤的顏色範圍 (HSV) - 預設為鮮豔的綠色
color_lower = np.array([35, 100, 100])
color_upper = np.array([85, 255, 255])

while cap.isOpened():
    success, frame = cap.read()
    if not success:
        break
        
    # 照鏡子翻轉 (Webcam 必備，這樣你往左揮，畫面才會在左邊)
    frame = cv2.flip(frame, 1)

    hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv_frame, color_lower, color_upper)
    mask = cv2.erode(mask, None, iterations=2)
    mask = cv2.dilate(mask, None, iterations=2)

    contours, _ = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if len(contours) > 0:
        largest_contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest_contour) > 500:
            ((x, y), radius) = cv2.minEnclosingCircle(largest_contour)
            # 畫出黃色追蹤圈
            cv2.circle(frame, (int(x), int(y)), int(radius), (0, 255, 255), 2)
            cv2.putText(frame, "Target Locked", (int(x)-40, int(y)-int(radius)-10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    cv2.imshow("Mac Sandbox - OpenCV Color Tracker", frame)
    # 按 'q' 離開
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
