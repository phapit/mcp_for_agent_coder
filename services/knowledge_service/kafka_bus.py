"""Kafka producer/consumer cho pipeline ingest event-driven.

Cấu hình đọc từ env (xem .env.example mục 8). Bus được thiết kế degrade mềm:
Kafka lỗi thì publish ném KafkaBusError để caller quyết định (fallback/503),
không bao giờ làm crash service lúc import.
"""

from __future__ import annotations

import json
import logging
import os

from confluent_kafka import Consumer, KafkaError, Producer

from job_contracts import JobEvent

logger = logging.getLogger(__name__)

KAFKA_ENABLED = os.getenv("KAFKA_ENABLED", "0") == "1"
BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
CLIENT_ID = os.getenv("KAFKA_CLIENT_ID", "knowledge_service")
SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "SASL_PLAINTEXT")
SASL_MECHANISM = os.getenv("KAFKA_SASL_MECHANISM", "PLAIN")
SASL_USERNAME = os.getenv("KAFKA_SASL_USERNAME", "")
SASL_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD", "")
# Broker dùng chung chạy SASL_SSL với CA tự ký; cert advertised theo IP nên tắt
# hostname verification giống /etc/kafka/client.properties phía broker.
SSL_CA_LOCATION = os.getenv("KAFKA_SSL_CA_LOCATION", "")
SSL_ENDPOINT_IDENTIFICATION = os.getenv("KAFKA_SSL_ENDPOINT_IDENTIFICATION", "none")

TOPIC_REQUESTED = os.getenv("KAFKA_TOPIC_DOCUMENT_INGEST_REQUESTED", "document.ingest.requested")
TOPIC_COMPLETED = os.getenv("KAFKA_TOPIC_DOCUMENT_INGEST_COMPLETED", "document.ingest.completed")
TOPIC_FAILED = os.getenv("KAFKA_TOPIC_DOCUMENT_INGEST_FAILED", "document.ingest.failed")
TOPIC_RETRY = os.getenv("KAFKA_TOPIC_DOCUMENT_INGEST_RETRY", "document.ingest.retry")
TOPIC_DLQ = os.getenv("KAFKA_TOPIC_DOCUMENT_INGEST_DLQ", "document.ingest.dlq")

CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP_DOCUMENT_INGEST", "knowledge-ingest")
AUTO_OFFSET_RESET = os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest")
MAX_POLL_INTERVAL_MS = int(os.getenv("KAFKA_MAX_POLL_INTERVAL_MS", 300000))
SESSION_TIMEOUT_MS = int(os.getenv("KAFKA_SESSION_TIMEOUT_MS", 45000))
REQUEST_TIMEOUT_MS = int(os.getenv("KAFKA_REQUEST_TIMEOUT_MS", 30000))
RETRY_BACKOFF_MS = int(os.getenv("KAFKA_RETRY_BACKOFF_MS", 1000))
RETRY_MAX_ATTEMPTS = int(os.getenv("KAFKA_RETRY_MAX_ATTEMPTS", 3))
PRODUCE_TIMEOUT_S = float(os.getenv("KAFKA_PRODUCE_TIMEOUT_S", 10.0))


class KafkaBusError(Exception):
    pass


def _base_config() -> dict:
    config = {
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "client.id": CLIENT_ID,
        "security.protocol": SECURITY_PROTOCOL,
    }
    if SECURITY_PROTOCOL.startswith("SASL"):
        config.update(
            {
                "sasl.mechanism": SASL_MECHANISM,
                "sasl.username": SASL_USERNAME,
                "sasl.password": SASL_PASSWORD,
            }
        )
    if SECURITY_PROTOCOL.endswith("SSL"):
        config["ssl.endpoint.identification.algorithm"] = SSL_ENDPOINT_IDENTIFICATION
        if SSL_CA_LOCATION:
            config["ssl.ca.location"] = SSL_CA_LOCATION
    return config


class KafkaBus:
    """Producer lazy-init + helper tạo consumer, dùng chung config SASL."""

    def __init__(self):
        self._producer: Producer | None = None

    def _get_producer(self) -> Producer:
        if self._producer is None:
            self._producer = Producer(
                {**_base_config(), "request.timeout.ms": REQUEST_TIMEOUT_MS, "acks": "all"}
            )
        return self._producer

    def publish_event(self, topic: str, event: JobEvent) -> None:
        """Publish 1 JobEvent (key = job_id để giữ thứ tự per-job). Ném KafkaBusError khi thất bại."""
        errors: list[str] = []

        def _on_delivery(err, _msg):
            if err is not None:
                errors.append(str(err))

        try:
            producer = self._get_producer()
            producer.produce(
                topic,
                key=str(event.job_id),
                value=event.model_dump_json().encode("utf-8"),
                on_delivery=_on_delivery,
            )
            remaining = producer.flush(PRODUCE_TIMEOUT_S)
        except (BufferError, KafkaError, Exception) as e:
            raise KafkaBusError(f"Kafka publish to '{topic}' failed: {e}") from e
        if errors or remaining:
            raise KafkaBusError(
                f"Kafka publish to '{topic}' failed: {errors or f'{remaining} message(s) not delivered'}"
            )
        logger.info(
            "kafka_event_published",
            extra={"topic": topic, "job_id": str(event.job_id), "event_type": event.event_type,
                   "attempt": event.attempt},
        )

    def create_consumer(self, topics: list[str]) -> Consumer:
        consumer = Consumer(
            {
                **_base_config(),
                "group.id": CONSUMER_GROUP,
                "auto.offset.reset": AUTO_OFFSET_RESET,
                "enable.auto.commit": False,
                "max.poll.interval.ms": MAX_POLL_INTERVAL_MS,
                "session.timeout.ms": SESSION_TIMEOUT_MS,
            }
        )
        consumer.subscribe(topics)
        return consumer

    def close(self) -> None:
        if self._producer is not None:
            self._producer.flush(PRODUCE_TIMEOUT_S)
            self._producer = None

    def ping(self) -> bool:
        """Health probe: lấy metadata cluster trong thời gian ngắn."""
        try:
            self._get_producer().list_topics(timeout=5.0)
            return True
        except Exception as e:
            logger.warning(f"Kafka ping failed: {e}")
            return False


def parse_event(raw: bytes) -> JobEvent:
    return JobEvent.model_validate(json.loads(raw.decode("utf-8")))
