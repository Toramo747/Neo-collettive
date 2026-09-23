"""Alternative pilot entrypoint; the production Dockerfile stays unchanged."""
import os

from cloud_mcp import app as legacy_app
from relay_app import build_app

app = build_app(legacy_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")),
                proxy_headers=True, forwarded_allow_ips="*")
