"""Atomic runtime configuration; in-flight requests finish on their original client."""

from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock

from zhijing.container import Container, build_container
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError


@dataclass
class Slot:
    container: Container
    users: int = 0
    retired: bool = False


class Runtime:
    def __init__(self, settings: Settings):
        self.lock = RLock()
        self.settings = settings
        self.revision = 0
        self.current = Slot(build_container(settings))

    @contextmanager
    def lease(self):
        with self.lock:
            slot = self.current
            slot.users += 1
        try:
            yield slot.container
        finally:
            with self.lock:
                slot.users -= 1
                if slot.retired and not slot.users:
                    slot.container.close()

    def activate(
        self, settings: Settings, container: Container, expected_revision: int | None = None
    ):
        with self.lock:
            if expected_revision is not None and expected_revision != self.revision:
                raise DomainError(
                    "configuration_changed", "另一操作已更新配置，请刷新页面后重试。", 409
                )
            old = self.current
            self.current = Slot(container)
            self.settings = settings
            self.revision += 1
            old.retired = True
            if not old.users:
                old.container.close()

    def close(self):
        with self.lock:
            self.current.retired = True
            if not self.current.users:
                self.current.container.close()
