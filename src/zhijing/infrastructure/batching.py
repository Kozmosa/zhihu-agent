"""Plan complete, ordered batches using a provider's network-free budget check."""

from collections.abc import Callable

from pydantic import BaseModel

from zhijing.core.errors import DomainError
from zhijing.domain.ports import StructuredGenerator


def budget_batches[Item, ModelResult: BaseModel](
    generator: StructuredGenerator,
    items: list[Item],
    *,
    task: str,
    instructions: str,
    payload_for: Callable[[list[Item]], dict],
    response_model: type[ModelResult],
    max_batches: int = 64,
) -> list[list[Item]]:
    """Preflight every batch before generating; never split on upstream failures.

    Providers predating ``check_budget`` keep their original one-call contract.
    A batch is divided only at supplied item boundaries, so indices and original
    text remain intact. Unfit schema/instructions or one unfit item fail with the
    original 413 instead of an unbounded retry or silent text truncation.
    """
    if max_batches < 1:
        raise ValueError("max_batches must be positive")
    check_budget = getattr(generator, "check_budget", None)
    if not callable(check_budget):
        return [items]

    def check(batch: list[Item]) -> None:
        check_budget(
            task=task,
            instructions=instructions,
            payload=payload_for(batch),
            response_model=response_model,
        )

    try:
        check(items)
        return [items]
    except DomainError as error:
        if error.code != "model_input_too_large" or len(items) <= 1:
            raise

    # Fail early when fixed instructions/schema/metadata alone cannot fit.
    check([])
    planned: list[list[Item]] = []

    def divide(batch: list[Item]) -> None:
        try:
            check(batch)
        except DomainError as error:
            if error.code != "model_input_too_large" or len(batch) <= 1:
                raise
            middle = len(batch) // 2
            divide(batch[:middle])
            divide(batch[middle:])
        else:
            planned.append(batch)
            if len(planned) > max_batches:
                raise DomainError(
                    "model_batch_limit",
                    f"资料需要超过 {max_batches} 批模型请求，请缩小资料范围或增加单批输入预算。",
                    413,
                )

    middle = len(items) // 2
    divide(items[:middle])
    divide(items[middle:])
    return planned
