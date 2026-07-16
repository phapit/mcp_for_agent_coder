"""Consumer worker: xử lý document.ingest.requested/retry tuần tự.

Một consumer duy nhất trong group => các ingest run được serialize tự nhiên,
nhiều client gửi /ingest đồng thời chỉ xếp hàng thay vì cùng lúc đè lên
embedding model + Qdrant. Run lỗi được retry qua topic retry (backoff bằng
next_attempt_at trong payload), quá max attempts thì đẩy DLQ.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone

import kafka_bus
import observability
from job_contracts import JobEvent, JobStatus, JobType

logger = logging.getLogger(__name__)


def new_request_event(*, correlation_id: str, payload: dict) -> JobEvent:
    return JobEvent(
        event_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        event_type="document.ingest.requested",
        job_type=JobType.DOCUMENT_INGEST,
        status=JobStatus.QUEUED,
        correlation_id=correlation_id,
        payload=payload,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IngestWorker:
    def __init__(self, bus: kafka_bus.KafkaBus, job_store, run_ingest_fn):
        """run_ingest_fn(payload: dict) -> dict summary; ném exception khi run-level failure."""
        self.bus = bus
        self.job_store = job_store
        self.run_ingest_fn = run_ingest_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- xử lý 1 event (tách riêng để unit-test không cần Kafka) ---
    def handle_event(self, event: JobEvent) -> str:
        """Trả về nhánh kết quả: 'completed' | 'retried' | 'dead_lettered' | 'deferred'."""
        observability.set_correlation_id(event.correlation_id)

        # Backoff cho message retry: chưa tới giờ thì ngủ nốt phần còn lại (volume nhỏ,
        # một consumer nên sleep không chặn job khác ngoài đúng thứ tự hàng đợi).
        not_before = event.payload.get("next_attempt_at")
        if not_before:
            delay = (datetime.fromisoformat(not_before) - _now()).total_seconds()
            if delay > 0:
                time.sleep(min(delay, 60.0))

        self.job_store.update(event.job_id, JobStatus.RUNNING, attempt=event.attempt)
        logger.info(
            "ingest_job_started",
            extra={"job_id": str(event.job_id), "attempt": event.attempt, "trigger": event.payload.get("trigger")},
        )
        try:
            summary = self.run_ingest_fn(event.payload)
        except Exception as e:
            return self._handle_failure(event, e)

        self.job_store.update(event.job_id, JobStatus.SUCCEEDED)
        self._publish(
            kafka_bus.TOPIC_COMPLETED,
            event,
            JobStatus.SUCCEEDED,
            payload={
                **event.payload,
                "result": {
                    "status": summary.get("status"),
                    "total_files": summary.get("total_files"),
                    "failed_count": len(summary.get("failed") or []),
                },
            },
        )
        return "completed"

    def _handle_failure(self, event: JobEvent, error: Exception) -> str:
        attempt = event.attempt + 1
        logger.error(
            f"Ingest job failed (attempt {attempt}): {error}",
            exc_info=True,
            extra={"job_id": str(event.job_id), "attempt": attempt},
        )
        self._publish(kafka_bus.TOPIC_FAILED, event, JobStatus.FAILED, attempt=attempt, error=str(error))

        if attempt >= kafka_bus.RETRY_MAX_ATTEMPTS:
            self.job_store.update(event.job_id, JobStatus.DEAD_LETTERED, error=str(error), attempt=attempt)
            self._publish(kafka_bus.TOPIC_DLQ, event, JobStatus.DEAD_LETTERED, attempt=attempt, error=str(error))
            return "dead_lettered"

        backoff_s = kafka_bus.RETRY_BACKOFF_MS / 1000 * (2 ** (attempt - 1))
        retry_payload = {
            **event.payload,
            "next_attempt_at": datetime.fromtimestamp(_now().timestamp() + backoff_s, tz=timezone.utc).isoformat(),
        }
        self.job_store.update(event.job_id, JobStatus.RETRYING, error=str(error), attempt=attempt)
        self._publish(
            kafka_bus.TOPIC_RETRY, event, JobStatus.RETRYING,
            attempt=attempt, error=str(error), payload=retry_payload,
        )
        return "retried"

    def _publish(self, topic: str, source: JobEvent, status: JobStatus, *,
                 attempt: int | None = None, error: str | None = None, payload: dict | None = None) -> None:
        event = JobEvent(
            event_id=uuid.uuid4(),
            job_id=source.job_id,
            event_type=topic,
            job_type=source.job_type,
            status=status,
            correlation_id=source.correlation_id,
            attempt=source.attempt if attempt is None else attempt,
            payload=payload if payload is not None else source.payload,
            error=error,
        )
        try:
            self.bus.publish_event(topic, event)
        except kafka_bus.KafkaBusError as e:
            # Job state đã lưu Mongo; mất event downstream không được làm chết worker.
            logger.error(f"Failed to publish result event to '{topic}': {e}")

    # --- vòng đời consumer thread ---
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="kafka-ingest-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_loop(self) -> None:
        consumer = self.bus.create_consumer([kafka_bus.TOPIC_REQUESTED, kafka_bus.TOPIC_RETRY])
        logger.info(
            "kafka_consumer_started",
            extra={"topics": [kafka_bus.TOPIC_REQUESTED, kafka_bus.TOPIC_RETRY],
                   "group": kafka_bus.CONSUMER_GROUP},
        )
        try:
            while not self._stop.is_set():
                message = consumer.poll(timeout=1.0)
                if message is None:
                    continue
                if message.error():
                    logger.error(f"Kafka consumer error: {message.error()}")
                    continue
                try:
                    event = kafka_bus.parse_event(message.value())
                except Exception as e:
                    # Message hỏng: log + commit để không kẹt partition.
                    logger.error(f"Dropping malformed job event: {e}", extra={"topic": message.topic()})
                    consumer.commit(message)
                    continue
                try:
                    self.handle_event(event)
                except Exception as e:
                    logger.error(f"Unhandled error while processing job event: {e}", exc_info=True)
                consumer.commit(message)
        finally:
            consumer.close()
            logger.info("kafka_consumer_stopped")
