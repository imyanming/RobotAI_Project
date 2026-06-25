"""
pi_fast_stream.py — Edge-side MJPEG video server.

Runs on the Raspberry Pi only. Captures frames from the camera via Picamera2
(libcamera) and serves them as an HTTP multipart/x-mixed-replace MJPEG stream
on port 8000, so the Host (Mac) and any standard browser can display the
robot's FPV feed without a dedicated video codec. This process is independent
of pi_udp_omni.py (motor control) — see the watchdog/process-isolation note
in that file for why they are kept separate.

Note: cv2.VideoCapture() cannot read this camera (IMX219) directly on this
OS/kernel combo — it only exposes raw Bayer data over plain V4L2. Picamera2
must be used for capture; OpenCV here is used only for JPEG encoding.
"""
import cv2
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from picamera2 import Picamera2

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Allows multiple simultaneous client connections (e.g. Mac host + browser)."""
    pass

class StreamingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                # Each iteration captures one frame, JPEG-encodes it, and writes
                # it as one part of the multipart stream. This loop runs until
                # the client disconnects, which raises inside wfile.write()
                # below and is caught by the except clause.
                while True:
                    frame = picam2.capture_array()
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    frame_bytes = buffer.tobytes()

                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame_bytes))
                    self.end_headers()
                    self.wfile.write(frame_bytes)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                # Expected when the client (Mac/browser) disconnects or the
                # network drops; not a fatal server error, so we just return
                # and let the HTTP server accept the next connection.
                pass
        else:
            self.send_error(404)

print('📷 正在啟動樹莓派相機...')

try:
    picam2 = Picamera2()
    config = picam2.create_video_configuration(main={'size': (640, 480), 'format': 'RGB888'})
    picam2.configure(config)
    picam2.start()
    time.sleep(1)
except Exception as e:
    print('\n❌ 嚴重錯誤：Python 抓不到攝影機！')
    print(f'👉 請檢查：1. 相機排線是否插緊？ 2. 有沒有在 raspi-config 中啟用相機？ ({e})')
else:
    server = ThreadedHTTPServer(('', 8000), StreamingHandler)
    print('🚀 戰車視覺廣播站已在 Port 8000 啟動...')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        picam2.stop()
        server.socket.close()
        print('\n🛑 廣播站已關閉')
