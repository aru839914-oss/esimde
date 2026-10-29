import logging
import os

from waitress import serve

from app import create_app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("waitress.queue").setLevel(logging.ERROR)
    application = create_app()
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    logging.info("Esimde is starting on %s:%s", host, port)
    serve(application, host=host, port=port, threads=8)
