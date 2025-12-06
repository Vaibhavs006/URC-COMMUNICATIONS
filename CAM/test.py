import asyncio
import websockets
import cv2
import base64
import numpy as np

frame0 = None
frame1 = None

async def receive_cam0():
    global frame0
    async with websockets.connect("ws://192.168.0.5:8765") as websocket:
        print("Connected to camera 0 (port 8765)")
        while True:
            data = await websocket.recv()
            jpg_bytes = base64.b64decode(data)
            np_arr = np.frombuffer(jpg_bytes, np.uint8)
            frame0 = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

async def receive_cam1():
    global frame1
    async with websockets.connect("ws://192.168.0.5:8766") as websocket:
        print("Connected to camera 2 (port 8766)")
        while True:
            data = await websocket.recv()
            jpg_bytes = base64.b64decode(data)
            np_arr = np.frombuffer(jpg_bytes, np.uint8)
            frame1 = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

async def display():
    global frame0, frame1
    while True:
        if frame0 is not None and frame1 is not None:
            combined = np.hstack((frame0, frame1))  # side-by-side layout
            cv2.imshow("Camera 0 | Camera 2", combined)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        await asyncio.sleep(0.01)

async def main():
    await asyncio.gather(
        receive_cam0(),
        receive_cam1(),
        display()
    )

if __name__ == "__main__":
    asyncio.run(main())
    cv2.destroyAllWindows()

