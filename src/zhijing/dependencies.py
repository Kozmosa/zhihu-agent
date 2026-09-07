from collections.abc import Iterator
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from zhijing.container import Container


def get_container(request: Request) -> Iterator["Container"]:
    with request.app.state.runtime.lease() as container:
        yield container
