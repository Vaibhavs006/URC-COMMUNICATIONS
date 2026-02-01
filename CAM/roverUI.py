# rover_ui_integrated.py
# Complete RoverUI system in a single file for Jetson Nano deployment
# Includes WebSocket camera server + HTTP server for React frontend
# Run with: python rover_ui_integrated.py

import asyncio
import json
import logging
import base64
import websockets
from websockets.server import WebSocketServerProtocol
import cv2
import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================

@dataclass
class CameraConfig:
    name: str
    source_url: str
    source_port: int
    broadcast_port: int
    camera_id: str

CAMERA_CONFIGS = [
    CameraConfig("Front View", "ws://192.168.0.5", 8765, 9001, "front_view"),
    CameraConfig("Rear View", "ws://192.168.0.5", 8766, 9002, "rear_view"),
    CameraConfig("Top View", "ws://192.168.0.5", 8767, 9003, "top_view"),
    CameraConfig("Arm Camera", "ws://192.168.0.5", 8768, 9004, "arm_camera"),
    CameraConfig("ZED RGB", "ws://192.168.0.5", 8769, 9005, "zed_rgb"),
    CameraConfig("ZED Depth", "ws://192.168.0.5", 8770, 9006, "zed_depth"),
    CameraConfig("Extra Camera", "ws://192.168.0.5", 8771, 9007, "extra_camera"),
]

HTTP_SERVER_PORT = 8080
JETSON_IP = "0.0.0.0"  # Listen on all interfaces

# ==================== FRAME BUFFER ====================

class CameraFrameBuffer:
    """Thread-safe buffer for the latest frame from each camera"""
    def __init__(self):
        self.frames: Dict[str, Optional[bytes]] = {cfg.camera_id: None for cfg in CAMERA_CONFIGS}
        self.timestamps: Dict[str, Optional[datetime]] = {cfg.camera_id: None for cfg in CAMERA_CONFIGS}
        self.frame_counts: Dict[str, int] = {cfg.camera_id: 0 for cfg in CAMERA_CONFIGS}
        self.connection_status: Dict[str, bool] = {cfg.camera_id: False for cfg in CAMERA_CONFIGS}

    async def set_frame(self, camera_id: str, frame_base64: str, timestamp: datetime = None):
        """Store the latest frame for a camera"""
        self.frames[camera_id] = frame_base64.encode() if isinstance(frame_base64, str) else frame_base64
        self.timestamps[camera_id] = timestamp or datetime.now()
        self.frame_counts[camera_id] += 1

    def get_frame(self, camera_id: str) -> Optional[bytes]:
        """Retrieve the latest frame for a camera"""
        return self.frames.get(camera_id)

    def set_connection_status(self, camera_id: str, connected: bool):
        """Update connection status for a camera"""
        self.connection_status[camera_id] = connected

    def get_status(self) -> Dict:
        """Get status of all cameras"""
        return {
            "timestamp": datetime.now().isoformat(),
            "cameras": {
                camera_id: {
                    "connected": self.connection_status.get(camera_id, False),
                    "frames_received": self.frame_counts.get(camera_id, 0),
                    "last_frame": self.timestamps[camera_id].isoformat() if self.timestamps[camera_id] else None
                }
                for camera_id in self.frames.keys()
            }
        }

frame_buffer = CameraFrameBuffer()

# ==================== WEBSOCKET HANDLERS ====================

async def receive_camera_feed(config: CameraConfig, max_retries: int = 5):
    """
    Receive camera feed from rover hardware via WebSocket.
    Converts incoming JPEG frames to color (BGR) and stores in buffer.
    Implements exponential backoff for reconnection.
    """
    retry_count = 0
    
    while True:
        try:
            source_url = f"{config.source_url}:{config.source_port}"
            logger.info(f"[{config.name}] Connecting to {source_url}")
            
            async with websockets.connect(source_url, ping_interval=20, ping_timeout=10) as websocket:
                frame_buffer.set_connection_status(config.camera_id, True)
                logger.info(f"[{config.name}] Connected successfully")
                retry_count = 0
                
                while True:
                    try:
                        data = await asyncio.wait_for(websocket.recv(), timeout=30)
                        
                        try:
                            message = json.loads(data)
                            jpg_bytes = base64.b64decode(message['image'])
                        except (json.JSONDecodeError, KeyError):
                            logger.warning(f"[{config.name}] Invalid message format")
                            continue
                        
                        try:
                            np_arr = np.frombuffer(jpg_bytes, np.uint8)
                            # Changed from IMREAD_GRAYSCALE to IMREAD_COLOR for color display
                            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                            
                            if frame is None:
                                logger.warning(f"[{config.name}] Failed to decode frame")
                                continue
                            
                            # Re-encode as JPEG (supports color)
                            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                            if ret:
                                frame_base64 = base64.b64encode(buffer).decode('utf-8')
                                await frame_buffer.set_frame(config.camera_id, frame_base64)
                                
                                if frame_buffer.frame_counts[config.camera_id] % 30 == 0:
                                    logger.debug(f"[{config.name}] Frames received: {frame_buffer.frame_counts[config.camera_id]}")
                        except Exception as e:
                            logger.error(f"[{config.name}] Error processing frame: {e}")
                            continue
                    
                    except asyncio.TimeoutError:
                        logger.warning(f"[{config.name}] No frame received for 30 seconds")
                        break
                    except Exception as e:
                        logger.error(f"[{config.name}] Error receiving frame: {e}")
                        break
        
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError) as e:
            frame_buffer.set_connection_status(config.camera_id, False)
            retry_count += 1
            
            if retry_count > max_retries:
                logger.error(f"[{config.name}] Max retries exceeded. Giving up.")
                break
            
            wait_time = min(2 ** retry_count, 30)
            logger.warning(f"[{config.name}] Connection closed: {e}. Retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
            await asyncio.sleep(wait_time)
        
        except Exception as e:
            frame_buffer.set_connection_status(config.camera_id, False)
            logger.error(f"[{config.name}] Unexpected error: {e}")
            await asyncio.sleep(5)

async def broadcast_camera_feed(config: CameraConfig, websocket: WebSocketServerProtocol, path: str):
    """
    WebSocket handler that broadcasts the latest color frame to connected clients.
    """
    client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    logger.info(f"[{config.name}] Client connected: {client_id}")
    
    try:
        while True:
            frame = frame_buffer.get_frame(config.camera_id)
            status = frame_buffer.connection_status.get(config.camera_id, False)
            
            if frame:
                response = {
                    "camera_id": config.camera_id,
                    "camera_name": config.name,
                    "timestamp": datetime.now().isoformat(),
                    "image": frame.decode('utf-8') if isinstance(frame, bytes) else frame,
                    "is_grayscale": False,  # Changed to False for color display
                    "source_connected": status,
                }
                try:
                    await websocket.send(json.dumps(response))
                except websockets.exceptions.ConnectionClosed:
                    break
            else:
                response = {
                    "camera_id": config.camera_id,
                    "camera_name": config.name,
                    "timestamp": datetime.now().isoformat(),
                    "image": None,
                    "is_grayscale": False,  # Changed to False for color display
                    "source_connected": status,
                    "message": "Waiting for first frame...",
                }
                try:
                    await websocket.send(json.dumps(response))
                except websockets.exceptions.ConnectionClosed:
                    break
            
            await asyncio.sleep(0.033)
    
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"[{config.name}] Client disconnected: {client_id}")
    except Exception as e:
        logger.error(f"[{config.name}] Error in broadcast handler: {e}")

async def health_check_handler(websocket: WebSocketServerProtocol, path: str):
    """Health check endpoint for monitoring camera status"""
    logger.info(f"Health check request from {websocket.remote_address}")
    
    try:
        while True:
            status = frame_buffer.get_status()
            await websocket.send(json.dumps(status))
            await asyncio.sleep(1)
    except websockets.exceptions.ConnectionClosed:
        pass

async def start_websocket_servers():
    """Start WebSocket servers for all cameras"""
    servers = []
    
    for config in CAMERA_CONFIGS:
        handler = lambda ws, path, cfg=config: broadcast_camera_feed(cfg, ws, path)
        server = await websockets.serve(
            handler,
            JETSON_IP,
            config.broadcast_port,
            ping_interval=20,
            ping_timeout=10,
        )
        servers.append(server)
        logger.info(f"Started broadcast server for {config.name} on ws://{JETSON_IP}:{config.broadcast_port}")
    
    # Health check server
    health_server = await websockets.serve(
        health_check_handler,
        JETSON_IP,
        9000,
        ping_interval=20,
        ping_timeout=10,
    )
    servers.append(health_server)
    logger.info(f"Started health check server on ws://{JETSON_IP}:9000")
    
    return servers

# ==================== HTTP SERVER FOR REACT UI ====================

class RoverUIHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves the embedded React UI"""
    
    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/' or self.path == '':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(REACT_UI_HTML.encode('utf-8'))
        else:
            super().do_GET()
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        logger.info(f"[HTTP] {format % args}")

def start_http_server():
    """Start HTTP server in a separate thread"""
    server = HTTPServer((JETSON_IP, HTTP_SERVER_PORT), RoverUIHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Started HTTP server on http://{JETSON_IP}:{HTTP_SERVER_PORT}")
    return server

# ==================== EMBEDDED REACT UI ====================

REACT_UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RoverUI - Security Camera Control</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        // Dynamic host detection - uses current server IP
        const HOST = window.location.hostname;
    </script>
    <style>
        .camera-feed {
            width: 100%;
            height: 100%;
        }
        .status-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin: 0 4px;
        }
        .status-online { background-color: #10b981; }
        .status-offline { background-color: #ef4444; }
        .status-connecting { background-color: #f97316; }
    </style>
</head>
<body class="bg-black text-white">
    <div id="app"></div>
    <script>
        // Camera configurations
        const CAMERA_CONFIGS = [
            { id: 'front_cam', name: 'Front Cam', port: 9001 },
            { id: 'rear_cam', name: 'Rear Cam', port: 9002 },
            { id: 'speed', name: 'Speed', port: 9003 },
            { id: 'zed_depth', name: 'Zed Depth', port: 9004 },
            { id: 'arm', name: 'Arm', port: 9005 },
            { id: 'pit', name: 'Pit', port: 9006 },
            { id: 'side', name: 'Side', port: 9007 },
        ];

        // CameraFeed Component
        class CameraFeed {
            constructor(config) {
                this.config = config;
                this.image = null;
                this.connected = false;
                this.sourceConnected = false;
                this.lastUpdate = null;
                this.fps = 0;
                this.frameCount = 0;
                this.lastTime = Date.now();
                this.ws = null;
                this.element = this.createElement();
            }

            createElement() {
                const div = document.createElement('div');
                div.className = 'relative bg-black rounded-lg overflow-hidden border border-zinc-700 hover:border-zinc-500 transition-colors h-full';
                div.innerHTML = `
                    <div class="relative w-full h-full camera-feed bg-zinc-950 flex items-center justify-center">
                        <img id="img-${this.config.id}" style="display:none; width:100%; height:100%; object-fit:cover;" />
                        <div id="loading-${this.config.id}" class="flex flex-col items-center justify-center text-gray-500">
                            <div class="text-6px mb-2">📷</div>
                            <span class="text-sm">Connecting...</span>
                        </div>
                        <div class="absolute inset-0 pointer-events-none flex flex-col justify-between p-1">
                            <div class="flex items-start justify-between">
                                <div class="bg-black/70 px-1.5 py-0.5 rounded text-xs font-semibold text-white">
                                    ${this.config.name}
                                </div>
                                <div class="flex gap-1">
                                    <div id="status-client-${this.config.id}" class="status-dot status-offline" title="Client connection"></div>
                                    <div id="status-source-${this.config.id}" class="status-dot status-offline" title="Source connection"></div>
                                </div>
                            </div>
                            <div class="text-right">
                                <div class="bg-black/70 px-1.5 py-0.5 rounded text-xs text-gray-300 font-mono">
                                    <div id="fps-${this.config.id}">0 FPS</div>
                                    <div id="time-${this.config.id}" class="text-gray-500 text-xs"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
                return div;
            }

            connect() {
                const wsUrl = `ws://${HOST}:${this.config.port}`;
                this.ws = new WebSocket(wsUrl);

                this.ws.onopen = () => {
                    console.log(`[${this.config.name}] Connected`);
                    this.connected = true;
                    this.updateStatusIndicators();
                };

                this.ws.onmessage = (event) => {
                    try {
                        const message = JSON.parse(event.data);
                        if (message.image) {
                            const img = this.element.querySelector(`#img-${this.config.id}`);
                            const loading = this.element.querySelector(`#loading-${this.config.id}`);
                            img.src = `data:image/jpeg;base64,${message.image}`;
                            img.style.display = 'block';
                            loading.style.display = 'none';
                        }
                        this.sourceConnected = message.source_connected || false;
                        this.lastUpdate = new Date(message.timestamp);
                        this.updateFPS();
                        this.updateStatusIndicators();
                    } catch (e) {
                        console.error(`[${this.config.name}] Parse error:`, e);
                    }
                };

                this.ws.onerror = (error) => {
                    console.error(`[${this.config.name}] Error:`, error);
                    this.connected = false;
                    this.updateStatusIndicators();
                };

                this.ws.onclose = () => {
                    console.warn(`[${this.config.name}] Closed. Reconnecting...`);
                    this.connected = false;
                    this.updateStatusIndicators();
                    setTimeout(() => this.connect(), 3000);
                };
            }

            updateFPS() {
                this.frameCount++;
                const now = Date.now();
                const elapsed = (now - this.lastTime) / 1000;
                if (elapsed >= 1) {
                    this.fps = Math.round(this.frameCount / elapsed);
                    const fpsEl = this.element.querySelector(`#fps-${this.config.id}`);
                    if (fpsEl) fpsEl.textContent = `${this.fps} FPS`;
                    this.frameCount = 0;
                    this.lastTime = now;
                }
                if (this.lastUpdate) {
                    const timeEl = this.element.querySelector(`#time-${this.config.id}`);
                    if (timeEl) timeEl.textContent = this.lastUpdate.toLocaleTimeString();
                }
            }

            updateStatusIndicators() {
                const clientStatus = this.element.querySelector(`#status-client-${this.config.id}`);
                const sourceStatus = this.element.querySelector(`#status-source-${this.config.id}`);

                if (clientStatus) {
                    clientStatus.className = `status-dot ${this.connected ? 'status-online' : 'status-offline'}`;
                }
                if (sourceStatus) {
                    sourceStatus.className = `status-dot ${this.sourceConnected ? 'status-online' : 'status-offline'}`;
                }
            }

            destroy() {
                if (this.ws) this.ws.close();
            }
        }

        // Main App
        class RoverUI {
            constructor() {
                this.cameras = [];
                this.telemetry = {
                    connected: false,
                    speed: 0,
                    battery: 0,
                    temperature: 0
                };
                this.init();
            }

            init() {
                this.renderHTML();
                this.setupCameras();
                this.connectTelemetry();
            }

            renderHTML() {
                const app = document.getElementById('app');
                app.innerHTML = `
                    <div class="flex flex-col h-screen bg-black">
                        <!-- Telemetry Bar -->
                        <div class="bg-zinc-900 border-b border-zinc-700 px-6 py-3">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-4">
                                    <span class="text-sm font-semibold text-blue-400">🛸 TaraUI</span>
                                </div>
                                <div class="flex items-center gap-6">
                                    <div>
                                        <span class="text-xs text-gray-400">Speed</span>
                                        <div class="text-sm font-mono text-white" id="telemetry-speed">0 km/h</div>
                                    </div>
                                    <div class="w-px h-6 bg-zinc-700"></div>
                                    <div>
                                        <span class="text-xs text-gray-400">Battery</span>
                                        <div class="text-sm font-mono text-white" id="telemetry-battery">0%</div>
                                    </div>
                                    <div class="w-px h-6 bg-zinc-700"></div>
                                    <div>
                                        <span class="text-xs text-gray-400">Temp</span>
                                        <div class="text-sm font-mono text-white" id="telemetry-temp">0°C</div>
                                    </div>
                                    <div class="w-px h-6 bg-zinc-700"></div>
                                    <div class="flex items-center gap-2" id="telemetry-status">
                                        <span class="status-dot status-offline"></span>
                                        <span class="text-xs font-semibold text-red-500">OFFLINE</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <!-- Header Section Above Cameras -->
                        <div class="px-1 pt-1 bg-black">
                            <div class="grid grid-cols-12 gap-1 mb-1">
                                <div class="col-span-1 bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-center">
                                    <span class="text-xs font-semibold text-gray-400">Temp</span>
                                    <div class="text-xs font-mono text-white">0°C</div>
                                </div>
                                <div class="col-span-1 bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-center">
                                    <span class="text-xs font-semibold text-white">-</span>
                                </div>
                                <div class="col-span-1 bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-center">
                                    <span class="text-xs font-semibold text-white">-</span>
                                </div>
                                <div class="col-span-2 bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-center">
                                    <span class="text-xs font-semibold text-gray-400">Speed</span>
                                    <div class="text-xs font-mono text-white">0 km/h</div>
                                </div>
                                <div class="col-span-2 bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-center">
                                    <span class="text-xs font-semibold text-white">-</span>
                                </div>
                                <div class="col-span-2 bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-center">
                                    <span class="text-xs font-semibold text-white">-</span>
                                </div>
                                <div class="col-span-2 bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-center">
                                    <span class="text-xs font-semibold text-white">-</span>
                                </div>
                                <div class="col-span-1 bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-center">
                                    <span class="text-xs font-semibold text-white">-</span>
                                </div>
                            </div>
                        </div>
                        <!-- Camera Grid -->
                        <div class="flex-1 p-1 bg-black">
                            <div class="grid grid-cols-6 grid-rows-4 gap-1 h-full" id="camera-grid">
                            </div>
                        </div>
                    </div>
                `;
            }

            setupCameras() {
                const grid = document.getElementById('camera-grid');
                CAMERA_CONFIGS.forEach((config, index) => {
                    const camera = new CameraFeed(config);
                    this.cameras.push(camera);

                    const wrapper = document.createElement('div');

                    // Layout based on hand-drawn diagram:
                    // Row 1-2: Front Cam (left, 4 cols x 2 rows) | Rear Cam (top right, 2 cols x 1 row)
                    // Row 2: Speed (right, 2 cols x 1 row)
                    // Row 3: Zed Depth | Arm | Pit | Side (each 1.5 cols)
                    // Row 4: Back (left section) | Battery (right)
                    
                    if (config.id === 'front_cam') {
                        // Front Cam - Big camera top left (4 columns, 2 rows)
                        wrapper.className = 'col-span-4 row-span-2';
                    } else if (config.id === 'rear_cam') {
                        // Rear Cam - Top right
                        wrapper.className = 'col-span-2 row-span-1';
                    } else if (config.id === 'speed') {
                        // Speed - Second row right
                        wrapper.className = 'col-span-2 row-span-1';
                    } else if (config.id === 'zed_depth') {
                        // Zed Depth - Third row, first position
                        wrapper.className = 'col-span-1 row-span-1';
                    } else if (config.id === 'arm') {
                        // Arm - Third row, second position
                        wrapper.className = 'col-span-2 row-span-1';
                    } else if (config.id === 'pit') {
                        // Pit - Third row, third position
                        wrapper.className = 'col-span-2 row-span-1';
                    } else if (config.id === 'side') {
                        // Side - Third row, fourth position
                        wrapper.className = 'col-span-1 row-span-1';
                    }

                    wrapper.appendChild(camera.element);
                    grid.appendChild(wrapper);
                    camera.connect();
                });
            }

            connectTelemetry() {
                const wsUrl = `ws://${HOST}:9000`;
                const ws = new WebSocket(wsUrl);

                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        const allConnected = Object.values(data.cameras).every(cam => cam.connected);
                        this.telemetry.connected = allConnected;
                        this.updateTelemetry();
                    } catch (e) {
                        console.error('Telemetry parse error:', e);
                    }
                };

                ws.onerror = () => {
                    this.telemetry.connected = false;
                    this.updateTelemetry();
                };

                ws.onclose = () => {
                    setTimeout(() => this.connectTelemetry(), 3000);
                };
            }

            updateTelemetry() {
                const statusEl = document.getElementById('telemetry-status');
                if (statusEl) {
                    statusEl.innerHTML = this.telemetry.connected
                        ? '<span class="status-dot status-online"></span><span class="text-xs font-semibold text-green-500">ONLINE</span>'
                        : '<span class="status-dot status-offline"></span><span class="text-xs font-semibold text-red-500">OFFLINE</span>';
                }
            }
        }

        // Initialize app when DOM is ready
        document.addEventListener('DOMContentLoaded', () => {
            new RoverUI();
        });
    </script>
</body>
</html>
"""

# ==================== MAIN ====================

async def main():
    """Main entry point"""
    logger.info("=" * 70)
    logger.info("RoverUI Integrated System - Starting on Jetson Nano (COLOR MODE)")
    logger.info("=" * 70)
    
    # Start HTTP server in background thread
    http_server = start_http_server()
    
    # Create receiver tasks
    receiver_tasks = [
        receive_camera_feed(config)
        for config in CAMERA_CONFIGS
    ]
    
    # Start WebSocket servers
    ws_servers = await start_websocket_servers()
    
    logger.info("=" * 70)
    logger.info(f"🎥 WebSocket servers started (cameras on ports 9001-9007)")
    logger.info(f"🌐 HTTP UI available at: http://<jetson-ip>:{HTTP_SERVER_PORT}")
    logger.info(f"📊 Health check endpoint: ws://<jetson-ip>:9000")
    logger.info(f"🎨 COLOR MODE: All cameras will display in color")
    logger.info("=" * 70)
    logger.info("Waiting for camera connections...")
    
    try:
        await asyncio.gather(*receiver_tasks)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        http_server.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
