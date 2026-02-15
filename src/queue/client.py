"""RabbitMQ client for submitting extracted matches to missing-table."""

from __future__ import annotations

import structlog
from pydantic_settings import BaseSettings

from models.match_data import MatchData

logger = structlog.get_logger()


class QueueConfig(BaseSettings):
    """RabbitMQ connection settings."""

    model_config = {"env_prefix": "RABBITMQ_"}

    url: str = "amqp://guest:guest@localhost:5672/"
    exchange: str = ""
    routing_key: str = "match_processing"


class MatchQueueClient:
    """Submits extracted match data to the match_processing queue."""

    def __init__(self, config: QueueConfig | None = None) -> None:
        self._config = config or QueueConfig()
        self._connection = None
        self._channel = None

    def connect(self) -> None:
        """Establish connection to RabbitMQ."""
        import pika

        self._connection = pika.BlockingConnection(pika.URLParameters(self._config.url))
        self._channel = self._connection.channel()
        self._channel.queue_declare(queue=self._config.routing_key, durable=True)
        logger.info("queue.connected", routing_key=self._config.routing_key)

    def submit(self, matches: list[MatchData]) -> int:
        """Submit a batch of matches to the queue.

        Returns:
            Number of matches submitted.
        """
        if not self._channel:
            self.connect()

        count = 0
        for match in matches:
            body = match.model_dump_json()
            self._channel.basic_publish(
                exchange=self._config.exchange,
                routing_key=self._config.routing_key,
                body=body.encode(),
            )
            count += 1

        logger.info("queue.submitted", count=count)
        return count

    def close(self) -> None:
        """Close the RabbitMQ connection."""
        if self._connection and not self._connection.is_closed:
            self._connection.close()
            logger.info("queue.disconnected")
