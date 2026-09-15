"""Atomic runtime configuration; in-flight requests finish on their original client."""

from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock, RLock

from zhijing.container import Container, build_container
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError
from zhijing.features.zhihu.companion import CompanionInbox


@dataclass
class Slot:
    container: Container
    users: int = 0
    retired: bool = False


class Runtime:
    def __init__(self, settings: Settings):
        self.lock = RLock()
        # Website login is independent of model and official search configuration.
        # It belongs only to this service session and is never written to Settings.
        self.zhihu_web_cookie = ""
        self.zhihu_web_lock = Lock()
        self.settings = settings
        self.revision = 0
        self.current = Slot(build_container(settings))
        self.companion_inbox = CompanionInbox(settings.data_dir)
        try:
            self.current.container.runs.recover_interrupted()
        except Exception:
            self.current.container.close()
            raise

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
            self.companion_inbox.close()
            self.zhihu_web_cookie = ""
            self.current.retired = True
            if not self.current.users:
                self.current.container.close()
