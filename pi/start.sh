#!/bin/bash
# RobotAI Project — Pi edge launcher
# Starts the camera stream server and the UDP motor controller in the background.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$DIR/core"
LOGS="$DIR/logs"
mkdir -p "$LOGS"

# Stop any previous instances first (bracket trick avoids self-matching this command line)
pkill -f '[p]i_fast_stream.py' 2>/dev/null
pkill -f '[p]i_udp_omni.py' 2>/dev/null
sleep 1

setsid nohup python3 -u "$CORE/pi_fast_stream.py" > "$LOGS/pi_fast_stream.log" 2>&1 < /dev/null &
setsid nohup python3 -u "$CORE/pi_udp_omni.py" > "$LOGS/pi_udp_omni.log" 2>&1 < /dev/null &

sleep 1
IP=$(hostname -I | awk '{print $1}')

echo "✅ Robot ready!"
echo "   IP: $IP"
echo "   📷 Camera stream:  http://$IP:8000/stream.mjpg"
echo "   🎮 Motor control:  UDP $IP:9000"
