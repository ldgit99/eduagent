"""Questionnaire for ``03_technical_spec.md``.

The rule from plan v2 §8: never ask for a technology by name. Ask what the agent
must be able to do, then recommend — and show the reasoning, so the student learns
why a single agent and session-only memory is usually the right answer for a class
project.
"""

from __future__ import annotations

from edu_agent import ui
from edu_agent.compiler.recommend import recommend_stack, summarize_recommendation
from edu_agent.schemas.technical import SelectionMode, TechnicalSpec
from edu_agent.ui import Choice


def run_technical(doc: TechnicalSpec, *, expected_users: int | None = None) -> TechnicalSpec:
    ui.header("기술 명세", "기술 이름 대신 '무엇이 필요한지'를 묻습니다.", step=(3, 4))

    mode = ui.ask_choice(
        "기술적인 부분을 직접 선택하시겠습니까?",
        [
            Choice("1", "직접 선택", SelectionMode.MANUAL),
            Choice("2", "일부만 직접 선택하고 나머지는 추천", SelectionMode.MIXED),
            Choice("3", "모두 추천해 주세요 (권장)", SelectionMode.RECOMMEND_ALL),
        ],
        hint="프로그래밍 경험이 없다면 3번을 고르세요. 추천 이유도 함께 보여드립니다.",
        default="3",
    )
    doc.requirements.selection_mode = mode

    _ask_requirements(doc, expected_users)
    recommend_stack(doc)

    ui.say()
    ui.panel(summarize_recommendation(doc), title="추천 구성", style="green")
    _show_reasons(doc)

    if mode is not SelectionMode.RECOMMEND_ALL:
        _offer_overrides(doc)
    return doc


def _ask_requirements(doc: TechnicalSpec, expected_users: int | None) -> None:
    req = doc.requirements
    ui.say()
    ui.info("[bold]필요한 것을 확인합니다[/bold]")

    req.needs_external_materials = ui.ask_yes_no(
        "AI가 별도의 교과서나 학습자료를 참고해야 합니까?",
        default=req.needs_external_materials,
        hint="'참고해야 한다'면 자료를 찾아오는 기능이 필요합니다. 일반 지식으로 충분하면 아니오.",
        allow_unknown=True,
    )
    req.needs_persistent_learner_memory = ui.ask_yes_no(
        "학생별 학습기록을 다음 접속에서도 기억해야 합니까?",
        default=req.needs_persistent_learner_memory,
        hint="기억하면 개인화가 되지만 학생 데이터를 저장하게 됩니다. 수업 한 차시용이면 보통 아니오.",
        allow_unknown=True,
    )
    req.uses_web_browser = ui.ask_yes_no(
        "학생은 웹 브라우저에서 이 에이전트를 사용합니까?",
        default=req.uses_web_browser,
        hint="아니오면 터미널에서 대화합니다. 학생에게 나눠줄 거라면 예를 고르세요.",
        allow_unknown=True,
    )
    req.expected_users = ui.ask_int(
        "약 몇 명이 사용할 예정입니까?",
        default=req.expected_users or expected_users,
        hint="규모에 따라 비용 관리와 배포 방식이 달라집니다.",
    )
    req.needs_code_execution = ui.ask_yes_no(
        "AI가 학생이 쓴 코드를 실제로 실행해 봐야 합니까?",
        default=req.needs_code_execution,
        hint="실행하면 정확한 피드백이 가능하지만, 반드시 안전한 격리 환경이 필요합니다.",
        allow_unknown=True,
    )
    req.needs_multimodal_input = ui.ask_yes_no(
        "학생이 사진이나 파일을 올려야 합니까?",
        default=req.needs_multimodal_input,
        allow_unknown=True,
    )
    req.must_run_offline_or_local = ui.ask_yes_no(
        "인터넷 없이 각자 컴퓨터에서만 돌아야 합니까?",
        default=req.must_run_offline_or_local,
        hint="예를 고르면 로컬 모델(Ollama)을 전제로 추천합니다.",
        allow_unknown=True,
    )


def _show_reasons(doc: TechnicalSpec) -> None:
    if not doc.decisions:
        return
    ui.say()
    ui.info("추천 이유")
    for decision in doc.decisions:
        ui.say(f"  [bold]{decision.area}[/bold] → {decision.choice}")
        ui.note(decision.reason)


def _offer_overrides(doc: TechnicalSpec) -> None:
    ui.say()
    change = ui.ask_yes_no("바꾸고 싶은 것이 있나요?", default=False)
    if not change:
        return
    ui.note(
        "03_technical_spec.md 파일을 직접 열어 수정한 뒤 'edu-agent review 03' 을 다시 실행하세요. "
        "무엇을 왜 바꿨는지도 파일에 적어 두면 나중에 도움이 됩니다."
    )


def summarize(doc: TechnicalSpec) -> str:
    return summarize_recommendation(doc)
