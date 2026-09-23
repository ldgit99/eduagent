"""Generate the ``c-debugging-coach`` example project.

The example is written by code rather than by hand so it stays in sync with the
schemas: if a field is renamed, this script fails loudly instead of the example
quietly rotting. It doubles as the end-to-end regression fixture (plan v2 §22).

Run: ``python scripts/make_example.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from edu_agent.documents import render_document, save_document  # noqa: E402
from edu_agent.principles import library_entries, to_principle  # noqa: E402
from edu_agent.project import create_project  # noqa: E402
from edu_agent.schemas.common import DocumentStatus  # noqa: E402
from edu_agent.schemas.educational import (  # noqa: E402
    AIUsageContext,
    EducationalDesign,
    ExpectedAISupport,
    LearningActivity,
    LearningContext,
    LearningObjective,
    LearningProblem,
)
from edu_agent.ui import configure_stdio  # noqa: E402

TARGET = ROOT / "examples" / "c-debugging-coach"

TASK_1_ANSWER = """\
#include <stdio.h>

int main(void) {
    int sum = 0;
    for (int i = 1; i <= 10; i++) {
        sum += i;
    }
    printf("%d\\n", sum);
    return 0;
}
"""

TASK_1_BUGGY = """\
#include <stdio.h>

int main(void) {
    int sum;
    for (int i = 1; i <= 10; i++) {
        sum += i;
    }
    printf("%d\\n", sum)
    return 0;
}
"""

TASK_2_ANSWER = """\
#include <stdio.h>

int main(void) {
    int n = 5;
    int factorial = 1;
    for (int i = 1; i <= n; i++) {
        factorial *= i;
    }
    printf("%d\\n", factorial);
    return 0;
}
"""


def build_educational() -> EducationalDesign:
    from edu_agent.schemas.educational import (
        LearnerStateSignal,
        SuccessIndicator,
        SupportType,
        TaskItem,
    )

    doc = EducationalDesign.new(language="ko")
    doc.title = "C 프로그래밍 디버깅 코치"
    doc.context = LearningContext(
        target_learners="C언어를 처음 배우는 중·고등학생",
        age_or_grade="중학교 3학년 ~ 고등학교 1학년",
        subject="정보/컴퓨터과학",
        topic="C언어 기초 문법과 디버깅",
        usage_situation="실습 수업 중 오류가 났을 때, 그리고 과제를 할 때",
        expected_users=30,
    )
    doc.problem = LearningProblem(
        current_difficulties=(
            "오류 메시지를 읽지 않고 넘긴다. 어디서부터 봐야 할지 모른다.\n"
            "코드를 조금씩 바꿔 보며 우연히 되기를 기다린다."
        ),
        core_problem=(
            "프로그램에 오류가 생겼을 때 스스로 원인을 분석하지 않고 "
            "AI에게 완성된 정답 코드를 바로 요구한다."
        ),
        limitations_of_existing_support=(
            "교사 한 명이 30명의 오류를 즉시 봐 줄 수 없다. "
            "일반 챗봇은 물어보면 바로 고친 코드를 주기 때문에 디버깅 연습이 되지 않는다."
        ),
    )
    doc.objectives = [
        LearningObjective(
            id="O01",
            statement="오류가 발생한 지점을 스스로 찾을 수 있다",
            evidence="오류 메시지의 줄 번호를 근거로 해당 위치를 지목한다",
        ),
        LearningObjective(
            id="O02",
            statement="오류의 원인을 자기 말로 설명할 수 있다",
            evidence="'왜 이런 오류가 났는지' 물었을 때 개념 용어로 설명한다",
        ),
        LearningObjective(
            id="O03",
            statement="힌트를 이용해 스스로 코드를 수정할 수 있다",
            evidence="힌트를 받은 뒤 코드를 직접 고쳐 실행에 성공한다",
        ),
    ]
    doc.activities = [
        LearningActivity(
            id="A01", name="코드를 작성하고 실행해 본다", order=1, learner_self_directed=True
        ),
        LearningActivity(
            id="A02", name="오류 메시지를 읽고 무엇이 문제인지 추측한다", order=2,
            learner_self_directed=True,
        ),
        LearningActivity(id="A03", name="AI 코치와 대화하며 원인을 좁힌다", order=3),
        LearningActivity(
            id="A04", name="스스로 코드를 수정하고 다시 실행한다", order=4, learner_self_directed=True
        ),
        LearningActivity(
            id="A05", name="해결 과정을 말이나 글로 설명한다", order=5, learner_self_directed=True
        ),
    ]
    doc.ai_usage = AIUsageContext(
        intervention_points=["학생이 오류를 만나 스스로 시도한 뒤", "학생이 도움을 요청했을 때"],
        before_ai="오류 메시지를 읽고 스스로 원인을 추측해 본다",
        during_ai="자기 추측을 말하고, 힌트를 받아 다시 시도한다",
        after_ai="고친 코드를 실행해 확인하고 해결 과정을 설명한다",
    )
    doc.expected_support = ExpectedAISupport(
        types=[SupportType.QUESTION, SupportType.HINT, SupportType.FEEDBACK],
        must_do=[
            "학생의 현재 생각을 먼저 묻는다",
            "가장 약한 힌트부터 제공하고 학생 반응에 따라 수준을 올린다",
            "해결한 뒤에는 과정을 설명하도록 요청한다",
        ],
        must_not_do=[
            "처음부터 완성된 정답 코드를 제공한다",
            "학생 대신 코드를 고쳐 준다",
            "학생이 틀린 주장을 강하게 해도 그대로 동의한다",
        ],
    )
    doc.tasks = [
        TaskItem(
            id="t01",
            title="1부터 10까지의 합 구하기 (세미콜론 누락 + 초기화 누락)",
            prompt_file="tasks/t01_sum.c",
            reference_answer=TASK_1_ANSWER,
            answer_fragments=["int sum = 0;", 'printf("%d\\n", sum);'],
            common_errors=["printf 뒤 세미콜론 누락", "sum 초기화 누락"],
            misconceptions=[
                "세미콜론을 빠뜨려도 컴파일러가 알아서 고쳐 준다",
                "초기화하지 않은 변수는 0이다",
            ],
        ),
        TaskItem(
            id="t02",
            title="팩토리얼 계산 (초기값 오류)",
            reference_answer=TASK_2_ANSWER,
            answer_fragments=["int factorial = 1;"],
            common_errors=["factorial 을 0으로 초기화"],
            misconceptions=["곱셈 누적 변수도 0으로 시작하면 된다"],
        ),
    ]
    doc.learner_state_signals = [
        LearnerStateSignal(
            variable="attempts",
            meaning="학생이 코드를 고쳐 다시 시도한 횟수",
            how_detected="학생이 수정 결과를 보고할 때 증가",
        ),
        LearnerStateSignal(
            variable="reasoning_shown",
            meaning="학생이 원인에 대한 자기 생각을 말했는가",
            how_detected="'~때문인 것 같다' 같은 표현 또는 12단어 이상의 설명",
        ),
        LearnerStateSignal(
            variable="stuck_turns",
            meaning="진전 없이 지나간 연속 턴 수",
            how_detected="같은 오류가 반복되거나 '모르겠다'가 이어질 때 증가",
        ),
    ]
    doc.success_indicators = [
        SuccessIndicator(
            statement="학생이 힌트를 받기 전에 자기 추론을 말한다",
            metric="reasoning_elicited_before_hint",
        ),
        SuccessIndicator(statement="학생이 힌트를 받은 뒤 스스로 다시 시도한다", metric="uptake"),
        SuccessIndicator(
            statement="해결 후 학생이 과정을 설명한다", metric="reflection_after_completion"
        ),
    ]
    doc.meta.status = DocumentStatus.CONFIRMED
    return doc


def build_principles():
    from edu_agent.schemas.principles import AnswerPolicy, DesignPrinciples, PolicyStatement

    doc = DesignPrinciples.new(language="ko")
    doc.theories_and_strategies = [
        "스캐폴딩과 점진적 소거(fading)",
        "자기조절학습(SRL) — 특히 자기성찰 단계",
        "소크라테스식 질문법",
        "메타인지적 피드백과 지시적 피드백의 혼합",
    ]
    doc.answer_policy = AnswerPolicy.CONDITIONAL
    doc.answer_condition = "attempts >= 3 or stuck_turns >= 2"

    wanted = [
        "lib.reasoning_first",
        "lib.progressive_scaffolding",
        "lib.no_premature_answer",
        "lib.corrective_friction",
        "lib.learner_agency",
        "lib.metacognitive_feedback",
        "lib.reflection_after_completion",
        "lib.cognitive_load",
        "lib.off_task_redirect",
        "lib.pii_guard",
    ]
    used: set[str] = set()
    by_id = {e.library_id: e for e in library_entries()}
    for library_id in wanted:
        principle, criteria = to_principle(by_id[library_id], used)
        principle.confirmed = True  # the student would confirm these interactively
        doc.principles.append(principle)
        doc.criteria.extend(criteria)

    doc.learner_agency = PolicyStatement(
        stance="코드를 고치는 것은 언제나 학생이 한다. 코치는 어디를 볼지만 알려준다.",
        principle_ids=[p.id for p in doc.principles if p.name == "reasoning_first"],
    )
    doc.scaffolding = PolicyStatement(
        stance=(
            "질문 → 방향 힌트 → 개념 힌트 → 부분 예시 → 상세 설명 순으로 올린다. "
            "3번 이상 시도했는데도 막혀 있으면 반드시 다음 단계로 올린다."
        )
    )
    doc.feedback = PolicyStatement(
        stance="맞고 틀림보다 '어떻게 찾았는지'에 대해 피드백하고, 다음에 할 일을 분명히 한다."
    )
    doc.reflection = PolicyStatement(
        stance="오류를 해결하면 무엇이 원인이었고 어떻게 찾았는지 학생이 설명하게 한다."
    )
    doc.meta.status = DocumentStatus.CONFIRMED
    return doc


def build_technical():
    from edu_agent.compiler.recommend import recommend_stack
    from edu_agent.schemas.technical import TechnicalSpec

    doc = TechnicalSpec.new(language="ko")
    req = doc.requirements
    req.needs_external_materials = False
    req.needs_persistent_learner_memory = False
    req.uses_web_browser = True
    req.expected_users = 30
    req.needs_code_execution = True
    req.needs_multimodal_input = False
    req.needs_lms_integration = False
    req.must_run_offline_or_local = False
    req.data_sensitivity = "학생 이름·학번은 저장하지 않는다."
    recommend_stack(doc)
    doc.meta.status = DocumentStatus.CONFIRMED
    return doc


def main() -> None:
    # This script prints Korean; a Windows console will not encode it otherwise.
    configure_stdio()

    if TARGET.exists():
        import shutil

        shutil.rmtree(TARGET)

    project = create_project(
        TARGET, name="c-debugging-coach", title="C 프로그래밍 디버깅 코치", language="ko"
    )

    (project.tasks_dir / "t01_sum.c").write_text(TASK_1_BUGGY, encoding="utf-8", newline="\n")
    (project.tasks_dir / "t01_sum_solution.c").write_text(
        TASK_1_ANSWER, encoding="utf-8", newline="\n"
    )

    docs = {
        "01_educational_design.md": ("educational_design.md.j2", build_educational()),
        "02_design_principles.md": ("design_principles.md.j2", build_principles()),
        "03_technical_spec.md": ("technical_spec.md.j2", build_technical()),
    }
    for filename, (template, model) in docs.items():
        body = render_document(template, d=model)
        save_document(project.root / filename, model, body)
        print(f"  wrote {filename}")

    # Compile deterministically so the example ships a runnable 04.
    from edu_agent.compiler import compile_spec
    from edu_agent.documents.io import load_document
    from edu_agent.schemas.educational import EducationalDesign as ED
    from edu_agent.schemas.principles import DesignPrinciples as DP
    from edu_agent.schemas.technical import TechnicalSpec as TS
    from edu_agent.utils.hashing import hash_text

    ed, _ = load_document(project.root / "01_educational_design.md", ED)
    pr, _ = load_document(project.root / "02_design_principles.md", DP)
    te, _ = load_document(project.root / "03_technical_spec.md", TS)
    hashes = {
        name: hash_text((project.root / name).read_text(encoding="utf-8"))
        for name in docs
    }

    result = compile_spec(ed, pr, te, provider=None, input_hashes=hashes, language="ko")
    for issue in result.issues:
        print(f"  {issue.severity.value}: {issue}")
    if not result.ok:
        raise SystemExit("컴파일에 실패했습니다 — 예제를 고쳐야 합니다.")

    spec = result.spec
    assert spec is not None
    spec.meta.status = DocumentStatus.COMPILED
    body = render_document("agent_spec.md.j2", d=spec)
    save_document(project.root / "04_agent_spec.md", spec, body)
    print("  wrote 04_agent_spec.md")

    print()
    print(f"게이트 {len(spec.gates)}개 · 행동 {len(spec.behaviors)}개 "
          f"· 기준 {len(spec.criteria)}개 · 시나리오 {len(spec.scenarios)}개")
    untraced = spec.untraced_principles()
    if untraced:
        print(f"⚠ 시나리오까지 이어지지 않은 원리: {untraced}")


if __name__ == "__main__":
    main()
