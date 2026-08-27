# 연구 근거 (Research Basis)

이 폴더는 `edu-agent-harness`의 설계 결정이 어디에서 왔는지를 기록한다.
조사 시점: **2026-08-27 ~ 28**. 모든 항목은 URL로 확인한 것만 싣는다.

- [harness-patterns.md](harness-patterns.md) — 참고한 하네스들의 설계 패턴, 자기개선 루프
- [pedagogy-evaluation.md](pedagogy-evaluation.md) — LLM 튜터의 교육학적 품질 평가 문헌
- [student-simulation.md](student-simulation.md) — LLM 학생 시뮬레이터의 타당성 문헌

## 이 프로젝트가 문헌에서 가져온 6가지 핵심 결정

| 결정 | 근거 | 구현 위치 |
|---|---|---|
| "정답 절대 금지"를 기본값으로 쓰지 않는다 | Arena 루브릭은 "정답을 너무 빨리 줌"과 "정보를 비생산적으로 보류함"을 **둘 다** 감점 | `schemas/principles.py::AnswerPolicy` 기본값 `CONDITIONAL` |
| hard 제약은 런타임에서 결정적으로 막는다 | Kadir 2026: 정책 게이트로 정답 누출 181건 → 0건 | `runtime/gates.py` |
| 단일 턴이 아니라 다중 턴으로 평가한다 | SafeTutors: 실패율 17.7% → 77.8% (긴 대화); Shao 2026: 9턴 이후 32% 붕괴 | `evaluator/deterministic.py::collapse_onset` |
| judge 점수는 사람 보정 전까지 참고용이다 | Maurya 2025: 범용 judge는 인간과 음의 상관; Khanmigo는 인간 일치 85% 확보 후 judge 사용 | `evaluator/calibration.py`, 보고서 경고 |
| 학생 시뮬레이터는 인식 상태를 LLM 밖에 둔다 | Do 2026: 강한 모델일수록 **무관한 피드백에도** 오개념을 버림 | `simulator/state.py::BeliefUpdate` |
| 튜터만 채점하지 않는다 | Neagu 2026: 챗봇 스캐폴딩과 학생 uptake는 별개 | `schemas/evaluation.py::LearnerSideMetrics` |
