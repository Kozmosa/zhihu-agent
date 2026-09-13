"""Shared structured generation adapter for the five knowledge capabilities."""

import json
import re
from typing import Annotated

import httpx
from pydantic import Field, ValidationError

from zhijing.core.errors import DomainError
from zhijing.domain.models import Citation, Generation, NonBlank, Schema
from zhijing.domain.ports import ModelResult
from zhijing.infrastructure.ollama_transport import OllamaTransport, system_prompt


class CitedAnswer(Schema):
    answer: Annotated[NonBlank, Field(max_length=16000)]
    citations: list[Annotated[int, Field(ge=1)]] = Field(min_length=1, max_length=10)


class OllamaGenerator:
    mode = "ollama"

    def __init__(
        self,
        client: httpx.Client,
        model: str,
        *,
        output_format: str = "schema",
        max_input_chars: int = 120000,
        num_predict: int = 4096,
        num_ctx: int = 32768,
    ):
        if output_format not in {"schema", "json", "prompt"}:
            raise ValueError("Ollama output format must be schema, json, or prompt")
        self.transport = OllamaTransport(client, model, num_predict, num_ctx)
        self.output_format, self.max_input_chars = output_format, max_input_chars

    def generate(
        self,
        *,
        task: str,
        instructions: str,
        payload: dict,
        response_model: type[ModelResult],
    ) -> ModelResult:
        schema, prompt = self._prepare_request(
            task=task, instructions=instructions, payload=payload, response_model=response_model
        )
        output_format = schema if self.output_format == "schema" else self.output_format
        text = self.transport.request(
            prompt=prompt,
            instructions=instructions,
            output_format=None if output_format == "prompt" else output_format,
        )
        try:
            # A response schema may define candidate-level validation (cards).
            # Other capabilities retain strict whole-response validation.
            decoder = getattr(response_model, "parse_model_response", None)
            if decoder is not None:
                return decoder(text)
            return response_model.model_validate_json(text, strict=True)
        except ValidationError as exc:
            raise DomainError(
                "model_invalid_response",
                "模型未返回约定的JSON结构，请检查模型能力或输出长度。",
                502,
            ) from exc

    def check_budget(
        self,
        *,
        task: str,
        instructions: str,
        payload: dict,
        response_model: type[ModelResult],
    ) -> None:
        """Use the exact generation budget without contacting the model service."""
        self._prepare_request(
            task=task, instructions=instructions, payload=payload, response_model=response_model
        )

    def _prepare_request(
        self,
        *,
        task: str,
        instructions: str,
        payload: dict,
        response_model: type[ModelResult],
    ) -> tuple[dict, str]:
        schema = response_model.model_json_schema()
        prompt = json.dumps({"task": task, "input": payload, "schema": schema}, ensure_ascii=False)
        complete_input = system_prompt(instructions) + prompt
        if len(complete_input) > self.max_input_chars:
            raise DomainError(
                "model_input_too_large", "资料超过模型输入预算，请缩小资料范围或调整预算。", 413
            )
        # UTF-8 bytes are a deliberately conservative estimate, not a model tokenizer.
        if (
            len(complete_input.encode("utf-8")) + self.transport.num_predict + 512
            > self.transport.num_ctx
        ):
            raise DomainError(
                "model_input_too_large", "资料超过保守上下文预算，请减少资料或调整NUM_CTX。", 413
            )
        return schema, prompt

    def answer(self, question: str, context: list[Citation]) -> Generation:
        evidence = [
            {"citation": index, "source_id": item.source_id, "text": item.excerpt}
            for index, item in enumerate(context, 1)
        ]
        result = self.generate(
            task="author",
            instructions=(
                "根据历史资料回答问题，优先参考第一条主资料。"
                "answer中每项结论用[序号]标记依据，citations列出使用的编号且不能重复。"
                "引用必须来自input.evidence；资料不足应在answer中明确说明局限，不冒充原作者。"
            ),
            payload={"question": question, "evidence": evidence},
            response_model=CitedAnswer,
        )
        used = set(result.citations)
        markers = {int(value) for value in re.findall(r"\[(\d+)\]", result.answer)}
        if (
            len(used) != len(result.citations)
            or not used <= set(range(1, len(context) + 1))
            or markers != used
        ):
            raise DomainError(
                "model_invalid_response", "模型引用编号不存在、重复或与回答中的标记不一致。", 502
            )
        return Generation(text=result.answer, mode=self.mode)
