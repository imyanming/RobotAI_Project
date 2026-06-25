import cv2

# 這是你樹莓派的真實 IP 網址
STREAM_URL = "http://192.168.68.105:8000/stream.mjpg"

def main():
    print(f"📡 正在連接戰車第一人稱視角: {STREAM_URL}")
    cap = cv2.VideoCapture(STREAM_URL)
    
    if not cap.isOpened():
        print("⚠️ 無法連線至影像串流！請確認樹莓派程式已執行，且區網連線正常。")
        return

    print("✅ 連線成功！正在讀取即時畫面... (按 Q 鍵可退出)")
    while True:
        success, frame = cap.read()
        if not success:
            print("⚠️ 遺失影像影格")
            break

        # 顯示戰車視野
        cv2.imshow("戰車第一人稱視角 (FPV Mode)", frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
