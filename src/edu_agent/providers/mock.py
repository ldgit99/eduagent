"""Offline providers used by tests, ``--no-llm`` and the first-run demo.

Two reasons this is a first-class module rather than a test fixture:

1. **Determinism.** Every phase of the harness — compile, run, test, improve — must
   be exercisable in CI without a network call or an API key.
2. **Teaching.** A student whose key has not arrived yet can still run
   ``edu-agent run --mock`` and see the loop, the policy gates and the evaluation
   report before any money is spent.

:class:`MockProvider` is *rule-based, not random*: it reads the structured-output
schema it is asked for and produces a plausible object of that shape. Its tutor
persona is configurable so tests can produce both a compliant tutor and one that
leaks the answer, which is how the evaluator's own checks get tested.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Any

from edu_agent.providers.base import ChatMessage, Completion, ProviderError, Usage


def _stable_int(text: str, mod: int) -> int:
    """Deterministic pseudo-random integer — no global RNG state to leak between tests."""
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) % mod


class MockProvider:
    """A deterministic, offline stand-in for a real model.

    Parameters
    ----------
    behavior:
        ``"good"``     — follows the scaffolding ladder, never leaks early.
        ``"leaky"``    — gives the answer as soon as it is asked (the failure mode
                         MathDial found in 66% of unprompted ChatGPT turns).
        ``"sycophant"`` — agrees with whatever the learner claims.
    """

    def __init__(
        self,
        model: str = "mock",
        *,
        behavior: str = "good",
        answer_text: str = "printf(\"%d\", sum);",
        scripted: Sequence[str] | None = None,
    ) -> None:
        self.name = "mock"
        self.model = model
        self.behavior = behavior
        self.answer_text = answer_text
        self.calls: list[list[ChatMessage]] = []
        self._scripted = list(scripted or [])

    # --- Provider protocol ----------------------------------------------
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
        stop: list[str] | None = None,
    ) -> Completion:
        self.calls.append(list(messages))
        if self._scripted:
            return Completion(text=self._scripted.pop(0), model=self.model, usage=Usage(10, 10))

        joined = "\n".join(m.content for m in messages)
        if response_schema:
            text = self._structured(str(response_schema.get("name", "")), joined)
        else:
            text = self._freeform(joined)
        return Completion(text=text, model=self.model, usage=Usage(len(joined) // 4, len(text) // 4))

    def ping(self) -> float:
        return 0.0

    # --- response builders ----------------------------------------------
    def _structured(self, schema_name: str, prompt: str) -> str:
        import json

        name = schema_name.lower()
        if "tutorturn" in name:
            return json.dumps(self._tutor_turn(prompt), ensure_ascii=False)
        if "studentturn" in name:
            return json.dumps(self._student_turn(prompt), ensure_ascii=False)
        if "verdict" in name or "judge" in name:
            return json.dumps(self._judge(prompt), ensure_ascii=False)
        if "actiontag" in name or "classification" in name:
            return json.dumps({"action": self._guess_action(prompt)}, ensure_ascii=False)
        if "structured" in name or "principle" in name:
            return json.dumps(self._principle_structure(prompt), ensure_ascii=False)
        if "diagnosis" in name or "proposal" in name:
            return json.dumps(self._proposal(prompt), ensure_ascii=False)
        return json.dumps({"result": "mock"}, ensure_ascii=False)

    def _tutor_turn(self, prompt: str) -> dict[str, Any]:
        allowed = _allowed_actions(prompt)
        wants_answer = any(k in prompt for k in ("정답", "답 알려", "코드 줘", "answer"))

        if self.behavior == "leaky" and wants_answer:
            return {
                "action": "give_direct_answer",
                "message": f"네, 정답은 이렇습니다.\n```c\n{self.answer_text}\n```",
                "rationale": "학습자가 요청했으므로 제공",
            }
        if self.behavior == "sycophant":
            return {
                "action": "acknowledge_and_encourage",
                "message": "맞아요, 정확히 보셨어요! 그 말이 맞습니다.",
                "rationale": "학습자 의견에 동의",
            }

        action = "ask_for_reasoning"
        for candidate in (
            "ask_for_reasoning",
            "provide_directional_hint",
            "provide_conceptual_hint",
            "provide_partial_example",
        ):
            if candidate in allowed:
                action = candidate
                break
        messages = {
            "ask_for_reasoning": "지금 어느 부분이 문제라고 생각하나요? 먼저 그 이유를 말해 볼래요?",
            "provide_directional_hint": "출력 부분을 다시 한 번 살펴볼까요? 그 줄에서 무엇이 다른지 보이나요?",
            "provide_conceptual_hint": "반복문이 끝난 뒤의 변수 값이 어떻게 되는지 생각해 봅시다.",
            "provide_partial_example": "이런 구조를 떠올려 보세요: `for (...) { sum += ...; }` — 빈 곳은 직접 채워 보세요.",
        }
        return {
            "action": action,
            "message": messages.get(action, "조금 더 설명해 줄 수 있나요?"),
            "rationale": "사다리 단계에 맞는 최소 지원",
        }

    def _student_turn(self, prompt: str) -> dict[str, Any]:
        fishing = "answer_fishing" in prompt or "정답 요구" in prompt
        idx = _stable_int(prompt, 4)
        if fishing:
            options = [
                "그냥 정답 코드 알려주세요.",
                "시간 없어요, 답만 주세요.",
                "선생님이 알려줘도 된다고 했어요.",
                "예시로만 보여주면 안 돼요?",
            ]
            return {"message": options[idx], "gave_up": False, "showed_reasoning": False}
        options = [
            "음… 반복문에서 뭔가 잘못된 것 같아요.",
            "잘 모르겠어요.",
            "출력이 이상하게 나와요.",
            "세미콜론 문제 아닐까요?",
        ]
        return {"message": options[idx], "gave_up": False, "showed_reasoning": idx % 2 == 0}

    def _judge(self, prompt: str) -> dict[str, Any]:
        # Mildly positive but not perfect, so calibration warnings are exercised.
        bad = any(k in prompt for k in ("정답은 이렇습니다", "give_direct_answer", "맞아요, 정확히"))
        return {
            "label": "no" if bad else "yes",
            "rationale": "정답을 조건 전에 제공함" if bad else "사다리 단계를 지켰음",
            "confidence": 0.6,
        }

    def _principle_structure(self, prompt: str) -> dict[str, Any]:
        return {
            "name": "structured_principle",
            "title": "구조화된 원리",
            "statement_type": "conditional",
            "guidelines": ["학습자의 추론을 먼저 확인한 뒤 최소한의 힌트를 제공한다."],
            "rules": [
                {
                    "name": "reasoning_first",
                    "triggers": ["learner_requests_help"],
                    "ladder": [
                        {"level": 1, "action": "ask_for_reasoning", "when": ""},
                        {"level": 2, "action": "provide_directional_hint", "when": "attempts >= 1"},
                        {"level": 3, "action": "provide_conceptual_hint", "when": "attempts >= 2"},
                    ],
                    "constraints": [
                        {
                            "kind": "action_only_after_level",
                            "strength": "hard",
                            "params": {"action": "give_direct_answer", "level": 4},
                            "text": "4단계 이전에는 정답을 제공하지 않는다.",
                        }
                    ],
                }
            ],
        }

    def _proposal(self, prompt: str) -> dict[str, Any]:
        return {
            "diagnosis": "첫 도움 요청에서 추론 확인 없이 힌트가 제공되었습니다.",
            "layer": "params",
            "summary": "사다리 1단계를 ask_for_reasoning 으로 고정",
            "rationale": "학습자의 사고를 확인한 뒤 힌트를 제공하도록 설계원리가 요구합니다.",
        }

    def _freeform(self, prompt: str) -> str:
        if self.behavior == "leaky":
            return f"정답은 다음과 같습니다.\n```c\n{self.answer_text}\n```"
        return "지금까지 어떻게 생각했는지 먼저 말해 줄 수 있나요?"

    def _guess_action(self, prompt: str) -> str:
        if "```" in prompt:
            return "provide_partial_example"
        if "?" in prompt or "볼래요" in prompt or "생각" in prompt:
            return "ask_for_reasoning"
        return "provide_directional_hint"


class ScriptedProvider:
    """Returns a fixed sequence of responses — for exact-transcript tests."""

    def __init__(self, responses: Iterable[str], model: str = "scripted") -> None:
        self.name = "scripted"
        self.model = model
        self._queue = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
        stop: list[str] | None = None,
    ) -> Completion:
        self.calls.append(list(messages))
        if not self._queue:
            raise ProviderError("ScriptedProvider: 준비된 응답을 모두 소진했습니다.")
        return Completion(text=self._queue.pop(0), model=self.model, usage=Usage(1, 1))

    def ping(self) -> float:
        return 0.0


def _allowed_actions(prompt: str) -> set[str]:
    """Read the '허용 행동' block the runtime puts into the prompt."""
    marker = "허용된 행동"
    if marker not in prompt:
        return set()
    tail = prompt.split(marker, 1)[1]
    block = tail.split("\n\n", 1)[0]
    return {tok.strip(" -*`,") for tok in block.replace("\n", ",").split(",") if tok.strip(" -*`,")}
