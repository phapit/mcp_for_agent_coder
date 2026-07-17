"""Distributed lock/throttle cho lệnh gọi NotebookLM CLI, dùng Redis.

Bảo vệ tài khoản NotebookLM cá nhân (dùng chung giữa công việc hàng ngày và
AI coder agent, có thể chạy ở process/container khác nhau) khỏi bị Google
flag do gọi quá nhanh:

- Tối đa 1 request đang xử lý cho mỗi notebook_id tại một thời điểm (lock
  độc quyền theo notebook_id qua Redis; khác notebook_id thì chạy song song).
- Giữa 2 lần gọi liên tiếp tới cùng 1 notebook_id có khoảng nghỉ ngẫu nhiên
  (mặc định 2-4s).
"""

from __future__ import annotations

import logging
import random
import time
from contextlib import contextmanager

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class NotebookLMLockError(RuntimeError):
    """Raised when the NotebookLM distributed lock cannot be reached (Redis lỗi)."""


class NotebookLMLockTimeoutError(NotebookLMLockError):
    """Raised when a request waited too long to acquire the per-notebook lock."""


class NotebookLMLockManager:
    def __init__(
        self,
        redis_client: Redis,
        *,
        lease_seconds: float = 600.0,
        wait_timeout_seconds: float = 600.0,
        min_delay_seconds: float = 2.0,
        max_delay_seconds: float = 4.0,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._redis = redis_client
        self._lease_seconds = lease_seconds
        self._wait_timeout_seconds = wait_timeout_seconds
        self._min_delay_seconds = min_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._poll_interval_seconds = poll_interval_seconds

    @staticmethod
    def _last_call_key(notebook_id: str) -> str:
        return f"notebooklm:last_call:{notebook_id}"

    @contextmanager
    def throttle(self, notebook_id: str):
        """Giữ 1 lock độc quyền cho notebook_id, đợi đủ khoảng nghỉ tối thiểu
        kể từ lần gọi trước đó, rồi mới cho phép thân `with` chạy."""
        lock = self._redis.lock(
            f"notebooklm:lock:{notebook_id}",
            timeout=self._lease_seconds,
            blocking_timeout=self._wait_timeout_seconds,
            sleep=self._poll_interval_seconds,
            thread_local=True,
        )
        try:
            acquired = lock.acquire(blocking=True)
        except RedisError as exc:
            raise NotebookLMLockError(
                f"Không thể kết nối Redis để lấy lock cho notebook '{notebook_id}': {exc}"
            ) from exc
        if not acquired:
            raise NotebookLMLockTimeoutError(
                f"Notebook '{notebook_id}' đang được xử lý bởi request khác quá lâu "
                f"(vượt quá {self._wait_timeout_seconds:.0f}s chờ). Thử lại sau."
            )
        try:
            self._wait_for_gap(notebook_id)
            yield
        finally:
            try:
                self._redis.set(self._last_call_key(notebook_id), time.time())
            except RedisError as exc:
                logger.warning("Không thể ghi last_call cho notebook '%s': %s", notebook_id, exc)
            try:
                lock.release()
            except RedisError as exc:
                logger.warning(
                    "Không thể release lock cho notebook '%s' (sẽ tự hết hạn sau %.0fs): %s",
                    notebook_id, self._lease_seconds, exc,
                )

    def _wait_for_gap(self, notebook_id: str) -> None:
        try:
            raw = self._redis.get(self._last_call_key(notebook_id))
        except RedisError as exc:
            logger.warning("Không thể đọc last_call cho notebook '%s': %s", notebook_id, exc)
            return
        if raw is None:
            return
        last_call_at = float(raw)
        gap = random.uniform(self._min_delay_seconds, self._max_delay_seconds)
        wait = gap - (time.time() - last_call_at)
        if wait > 0:
            time.sleep(wait)
