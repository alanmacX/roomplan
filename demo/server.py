"""Smart Home Course Design Server Entrypoint.

Delegates to the strict 5-layer architecture under backend/{api,strategy,control,device,data}/.
"""
from pathlib import Path
from backend.api.http_server import main

if __name__ == "__main__":
    main(Path(__file__).resolve().parent)
