import cv2
import asyncio
import websockets
import base64
import numpy as np

cap = cv2.VideoCapture(3)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

async def stream_video(websocket):
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame")
            break
        
        _, buffer = cv2.imencode('.jpg', frame)
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')

        try:
            await websocket.send(jpg_as_text)
        except websockets.exceptions.ConnectionClosed:
            print("Client disconnected")
            break
        
        await asyncio.sleep(0.05)  # ~20 FPS

async def main():
    async with websockets.serve(stream_video, "0.0.0.0", 8767):
        print("WebSocket server running on port 8767")
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        cap.release()
        cv2.destroyAllWindows()
