"""
DeepSkyAgent — Entry point
Run:  python main.py
Open: http://localhost:8000
"""
import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    uvicorn.run(
        "backend.api.app:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", 8000)),
        reload=True,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
