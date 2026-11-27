"""Run the KASTIGO application server."""

import uvicorn

from api.main import app
from config.settings import SERVER_HOST, SERVER_PORT


if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
