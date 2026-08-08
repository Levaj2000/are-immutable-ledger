"""Production server for the ledger gateway. Uvicorn + WSGI wrapper."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from asgiref.wsgi import WsgiToAsgi
from api.gateway import app

asgi_app = WsgiToAsgi(app)

if __name__ == "__main__":
    port = int(os.environ.get("GATEWAY_PORT", "28099"))
    workers = int(os.environ.get("GATEWAY_WORKERS", "2"))
    uvicorn.run(
        "api.serve:asgi_app",
        host="0.0.0.0",
        port=port,
        workers=workers,
    )
