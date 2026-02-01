import asyncio
import cv2
import websockets
import base64
import json
from threading import Thread
import numpy as np

class CameraStreamer:
    def __init__(self, cam_idx, port, width=320, height=240, quality=50):
        self.cam_idx = cam_idx
        self.port = port
        self.width = width
        self.height = height
        self.quality = quality
        self.clients = set()
        self.cap = None
        self.running = False

    def init_camera(self):
         """Initialize camera capture"""
        self.cap = cv2.VideoCapture(self.cam_idx)
        if not self.cap.isOpened():
            print(f"Error: Cannot open camera {self.cam_idx}")
            return False
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        return True
    
    def process_frame(self, frame):
        """Resize, convert to grayscale, and encode frame"""
        # Resize frame
        frame = cv2.resize(frame, (self.width, self.height))

        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Encode as JPEG with quality reduction
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
        _, buffer = cv2.imencode('.jpg', gray, encode_param) 
        # Convert to base64
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        return jpg_as_text
    
    async def handler(self, websocket):
        """Handle WebSocket connections"""
        self.clients.add(websocket)
        print(f"Camera {self.cam_idx}: Client connected on port {self.port}")
        try:
            await websocket.wait_closed()
        finally:
            self.clients.remove(websocket)
            print(f"Camera {self.cam_idx}: Client disconnected from port {self.>
    
    async def broadcast_frames(self):
        """Capture and broadcast frames to all connected clients"""
        while self.running:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    # Process frame
                    encoded_frame = self.process_frame(frame)
                    # Broadcast to all clients
                    if self.clients:
                        message = json.dumps({
                            'camera': self.cam_idx,
                            'image': encoded_frame
                        })

                        # Send to all connected clients
                        websockets_to_remove = set()
                        for ws in self.clients:
                            try:
                                await ws.send(message)
                            except websockets.exceptions.ConnectionClosed:
                                websockets_to_remove.add(ws)

                        # Remove closed connections
                        self.clients -= websockets_to_remove
                    # Small delay to control frame rate (~30 FPS)
                await asyncio.sleep(0.033)
            else:
                await asyncio.sleep(0.1)
    
    async def start_server(self):
        """Start WebSocket server"""
        self.running = True

        if not self.init_camera():
            return

        async with websockets.serve(self.handler, "0.0.0.0", self.port):
            print(f"Camera {self.cam_idx} streaming on ws://localhost:{self.por>

            # Start broadcasting frames
            await self.broadcast_frames()
    
    def cleanup(self):
        """Release camera resources"""

  async def main():
    """Run both camera streamers concurrently"""
    # Create streamers for camera 0 and 2
    streamer0 = CameraStreamer(cam_idx=0, port=8765, width=320, height=240, qua>
    streamer2 = CameraStreamer(cam_idx=2, port=8766, width=320, height=240, qua>
    
    try:
        # Run both servers concurrently
        await asyncio.gather(
            streamer0.start_server(),
            streamer2.start_server()
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        streamer0.cleanup()
        streamer2.cleanup()
        cv2.destroyAllWindows()

if __name__ == "__main__":
