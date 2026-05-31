"""
Multi-Device Compute System (MDCS) - Coordinator Entry Point
中心协调器入口，启动WebSocket服务器和HTTP API
"""
import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from websocket_server import CoordinatorWebSocketServer
from http_api import router as http_router
from device_manager import DeviceManager
from task_manager import TaskManager
from scheduler import MCDMScheduler
from security import SecurityManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/app/logs/coordinator.log')
    ]
)
logger = logging.getLogger("MDCS.Coordinator")

# Global state
class AppState:
    def __init__(self):
        self.device_manager = DeviceManager()
        self.scheduler = MCDMScheduler()
        self.task_manager = TaskManager(self.device_manager, self.scheduler)
        self.security = SecurityManager()
        self.ws_server = CoordinatorWebSocketServer(
            host="0.0.0.0",
            port=8765,
            device_manager=self.device_manager,
            task_manager=self.task_manager,
            security=self.security
        )

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager: startup and shutdown"""
    logger.info("=== MDCS Coordinator Starting ===")

    # Start WebSocket server in background
    ws_task = asyncio.create_task(state.ws_server.start())

    # Load model partition configuration
    await state.task_manager.load_model_config("/app/models/qwen-1.8b-config.json")

    logger.info("Coordinator ready. HTTP:8080, WebSocket:8765")
    yield

    # Shutdown
    logger.info("=== Coordinator Shutting Down ===")
    await state.ws_server.stop()
    ws_task.cancel()
    try:
        await ws_task
    except asyncio.CancelledError:
        pass

# FastAPI HTTP Application
app = FastAPI(
    title="MDCS Coordinator API",
    description="Multi-Device Compute System - Central Coordinator",
    version="1.0.0",
    lifespan=lifespan
)
app.include_router(http_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    """Health check endpoint for Docker and load balancers"""
    return {
        "status": "healthy",
        "devices_online": len(state.device_manager.get_online_devices()),
        "active_tasks": state.task_manager.get_active_task_count(),
        "version": "1.0.0"
    }

@app.get("/metrics")
async def metrics():
    """Prometheus-style metrics endpoint"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Counter, Gauge
    return generate_latest()

def signal_handler(sig, frame):
    logger.info("Received shutdown signal")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
        reload=False
    )
