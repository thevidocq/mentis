"""Start the ingestion worker:  python -m app.worker"""

import logging

from rq import Worker

from app.services.jobs import QUEUE, redis_connection
from app.worker import maintenance


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    maintenance.start()
    Worker([QUEUE], connection=redis_connection()).work(with_scheduler=False)


if __name__ == "__main__":
    main()
