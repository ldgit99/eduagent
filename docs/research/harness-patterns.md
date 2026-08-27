# 참고한 하네스들의 설계 패턴

조사: 2026-08-28. 각 항목은 "무엇을 빌려왔는가"와 "어디에 구현했는가"를 함께 적는다.

---

## A. 평가·에이전트 하네스

### Inspect AI (UK AISI) — https://inspect.aisi.org.uk/
- `Task = dataset + solver + scorer`. 에이전트가 바뀌어도 eval 명세는 그대로.
- CLI(`inspect eval`)와 Python API가 **동일한 의미**를 갖는 이중 진입점.
- 모든 실행이 구조화된 로그 파일을 남기고, 뷰어는 그 로그를 보는 렌즈일 뿐 — **로그가 정본**.
- 샌드박스는 task의 교체 가능한 필드이지 루프에 박힌 것이 아님.
- 주의: 의존성이 무겁고, solver/store 추상화가 실제 보낸 메시지를 가린다.

> **차용**: `Scenario(persona + task + criteria)` = dataset, `runtime` = solver, `evaluator` = scorer.
> JSONL trace가 정본이고 `edu-agent view`는 렌즈. → `schemas/trace.py`, `evaluator/`

### promptfoo — https://www.promptfoo.dev/docs/getting-started/
- 선언적 YAML(`prompts`/`providers`/`tests`+`assert`) — eval을 diff 가능한 설정으로.
- assertion 분류가 한 리스트 안에 공존: 결정적(`contains`), 모델 채점(`llm-rubric`), 운영(`cost`, `latency`).
- `eval` → `view` 워크플로 + 응답 캐싱. red-team 모드가 같은 설정 형식을 씀.
- 주의: 환경 상태를 갖는 다중 턴 과제에는 YAML-first가 버겁다.

> **차용**: 평가 기준을 `rubrics/*.yaml`로 두고 결정적/judge/운영 검사를 한 목록에 섞는다. → `evaluator/rubrics/`

### τ-bench / τ²-bench (Sierra) — https://arxiv.org/abs/2406.12045 · https://github.com/sierra-research/tau2-bench
- **pass^k**: k회 시행이 *모두* 성공할 확률. 운이 아니라 신뢰도를 잰다.
- 채점은 최종 **상태**(DB) 비교 + 필수 행동 확인 — transcript가 아니라 결과.
- τ²는 사용자 시뮬레이터에게도 도구를 줘 제약(dual control): 시뮬레이터 오류율 40–47% → 16%.
- `evaluate-trajs --fresh-tasks`: 저장된 궤적을 **다시 실행하지 않고 재채점**.
- 주의: 시뮬레이터 잡음이 지표를 오염시킨다. 태스크 명세 디버깅 비용을 예산에 넣을 것.

> **차용 3가지**:
> 1. `seeds` × 시나리오 → pass^k 스타일 반복 (`TestScenario.seeds`)
> 2. `edu-agent test --regrade <run_id>` — 모델 재호출 없이 저장된 trace 재채점
> 3. 시뮬레이터 제약(`SimulatorConstraints`)과 그 위반을 1급 지표로 기록

### openevals (LangChain) — https://github.com/langchain-ai/openevals
- `run_multiturn_simulation(app, user, max_turns, stopping_condition)` — 앱과 시뮬레이션 사용자가 **둘 다 그냥 callable**.
- 궤적 평가자에 strict/unordered/subset/superset 매치 모드.
- 주의: 영속화·리포팅이 LangSmith에 기운다.

> **차용**: `simulator/loop.py::run_simulation(tutor, student, max_turns, stop)` 시그니처.

### DeepEval ConversationSimulator — https://deepeval.com/docs/conversation-simulator
- `ConversationalGolden = persona + scenario + expected_outcome` (+ 초기 turns 시드).
- 시뮬레이션과 채점이 **분리된 단계**: `simulate()` → test case → `evaluate(metrics=[...])`.

> **차용**: 시뮬레이션(`simulator/`)과 채점(`evaluator/`)을 완전히 분리. trace 파일이 둘 사이의 유일한 계약.

### Anthropic, "Demystifying evals for AI agents" — https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- transcript 채점보다 **결과/상태 검사**를 선호. transcript는 *왜*를 설명하는 데 쓴다.
- eval을 CI처럼 다루고, LLM judge는 사람 라벨로 보정한다.
- 주의: 순수 결과 검사는 도중의 정책 위반을 놓친다 — 궤적 검토도 필요.

> **차용**: 이 하네스의 "상태"는 학습자 상태 변수와 게이트 판정. 점수 옆에 항상 근거 대화를 붙인다(`Evidence`).

### OpenAI Agents SDK — https://openai.github.io/openai-agents-python/guardrails/
- 가드레일이 타입 있는 함수(`@input_guardrail`, `@output_guardrail`)이고 `tripwire_triggered=True`가 **전용 예외**를 던진다 — 문자열 파싱이 아니라 제어 흐름.
- 입력 가드레일은 기본적으로 에이전트와 **병렬** 실행(지연 최소화), 필요하면 blocking.
- 주의: 병렬이면 tripwire 전에 토큰/도구 호출이 나갈 수 있다. 파괴적 도구는 blocking으로.

> **차용**: `GateResult(passed, reason)` + 차단 시 재생성. 파괴적 도구(코드 실행)는 blocking 검사.

### Pydantic AI — https://pydantic.dev/docs/ai/overview/
- 함수 시그니처+docstring이 곧 도구 스키마. 검증 실패가 모델에게 **자동 피드백**되어 재시도.
- 주의: 검증 재시도가 조용히 토큰을 태운다 — 상한을 두고 로그를 남길 것.

> **차용**: 게이트 차단 시 모델에게 수정 지시를 되돌려주되 `max_regenerations`로 상한. 재생성 횟수는 기술 안정성 지표.

### mini-swe-agent — https://github.com/SWE-agent/mini-swe-agent
- ~100줄 에이전트, 도구는 bash 하나, 모든 행동이 무상태 `subprocess.run`. 선형 append-only 히스토리 = 궤적이 곧 프롬프트. 그럼에도 SWE-bench Verified >74%.
- 주의: 무상태 셸은 env/cwd를 잃는다.

> **차용**: 런타임 턴 루프를 최대한 단순하게. 상태는 명시적 `LearnerState` 하나에만 둔다.

### SWE-agent ACI 논문 — https://arxiv.org/abs/2405.15793
- 에이전트-컴퓨터 인터페이스를 의도적으로 설계: 적고 간결하며 문서화된 명령. 인터페이스만 바꿔 3.8% → 12.5%.

> **차용**: 모델에게 주는 "허용 행동 목록"을 짧고 명확한 어휘로 고정(`AgentAction`).

### Claude Code hooks / Agent Skills — https://code.claude.com/docs/en/hooks
- 라이프사이클 훅이 선언적 설정에 있고, `allow|deny|ask` JSON을 반환하는 **모델 밖 정책 계층**.
- 이름 붙은 권한 모드가 자율성 다이얼 역할.
- Skills: `SKILL.md`의 점진적 공개 — 이름+설명만 먼저, 필요할 때 본문.
- 주의: 설정이 여러 파일에 흩어지면 실효 정책 감사가 어렵다 — "병합된 설정 보기" 명령을 제공할 것.

> **차용 3가지**:
> 1. 정책 게이트 = 모델 밖 계층, `allow|block` + 이유 (`runtime/gates.py`)
> 2. **자율성 다이얼**: `improve --auto` 레벨 (§B 참조)
> 3. `edu-agent status --explain`이 실효 게이트 목록을 보여준다

### Vercel Eve — https://vercel.com/docs/eve
- 파일시스템 우선: 에이전트가 관례적 파일들의 디렉터리 — 검사·diff·grep 가능.

> **차용**: 프로젝트가 4개 MD + tasks/ + evals/ 디렉터리. 모든 산출물이 git에서 diff된다.

### 12-Factor Agents — https://github.com/humanlayer/12-factor-agents
- #2 프롬프트를 소유하라, #3 컨텍스트 윈도를 소유하라, #4 도구는 그냥 구조화 출력, #7 **사람 접촉을 도구 호출로**, #9 에러를 압축해 컨텍스트에, #12 무상태 리듀서(agent = fn(state, event) → state).
- 주의: 검증된 프레임워크가 아니라 의견 에세이.

> **차용**: 시스템 프롬프트를 템플릿으로 소유(`templates/system_prompt.j2`), 턴 루프를 `fn(state, event) → state`로.

---

## B. 자기개선 루프와 안전장치

### DSPy GEPA — https://dspy.ai/api/optimizers/GEPA/overview/ · https://arxiv.org/abs/2507.19457
- **편집 단위**: 모듈별 지시문 텍스트.
- **신호**: 점수 + **자연어 피드백**(에러 로그, 제약 위반). 반성 LM이 실행 궤적을 읽고 표적 수정을 제안.
- **과적합 방지**: 별도 valset, 인스턴스별 점수의 **Pareto frontier**로 후보 유지(탐욕적 교체 아님), 명시적 예산(`max_metric_calls`), 후보 계보 기록.
- **사람 지점**: 사람이 frontier를 보고 선택·배포.

> **가장 크게 차용한 항목.** `improve`의 신호는 스칼라 점수가 아니라 **실패 근거 텍스트**다.

### DSPy MIPROv2 — https://dspy.ai/api/optimizers/MIPROv2/
- 지시문과 few-shot 데모를 **함께** 최적화. 미니배치 + 주기적 전체 평가.
- 주의: 최적화된 프롬프트는 기계 냄새가 난다 — 채택 전 사람이 읽는 diff 단계를 둘 것.

> **차용**: 모든 패치는 `--dry-run`으로 diff를 먼저 보여준다.

### TextGrad — https://arxiv.org/abs/2406.07496
- 텍스트 변수에 대한 "텍스트 기울기"(LLM 비평)를 역전파. 주의: 자체 held-out/롤백 규율이 없다.

### Reflexion — https://arxiv.org/abs/2303.11366
- 프롬프트를 영구 변경하지 않고 **에피소드 메모리의 자기반성 텍스트**를 다음 시도에 전달. 외부 검증(테스트)이 보상.
- 주의: 반성이 자신 있게 오진할 수 있다 — 재시도 상한 + 외부 검증 필수.

> **차용**: 게이트 차단 후 재생성 시 "왜 막혔는지"를 압축해 다음 프롬프트에 넣는다(런타임 내 Reflexion).

### Self-Refine — https://arxiv.org/abs/2303.17651
- generate → critique → refine. 주의: 같은 모델의 자기비평은 정체·퇴화한다 — 더 강하거나 루브릭에 고정된 비평자를 쓸 것.

> **차용**: 진단(critique)에 judge와 **다른** 모델을 권장하고, 루브릭에 고정한다.

### Anthropic evaluator-optimizer 패턴 — https://www.anthropic.com/engineering/building-effective-agents
- 생성 LLM + 평가 LLM 루프. **명확한 평가 기준이 있고 반복이 실제로 도움이 될 때만** 사용. 에이전트가 아니라 예측 가능한 *워크플로*로 규정.

> **차용**: `improve`는 자율 에이전트가 아니라 결정적 워크플로. 각 단계가 코드로 고정되어 있다.

### OPRO — https://arxiv.org/abs/2309.03409
- 메타프롬프트에 과거 (프롬프트, 점수) 궤적을 담아 더 나은 것을 외삽. 주의: 작은 eval 셋의 잡음이 궤적을 오도한다.

> **차용**: 개선 이력(`improve/history.jsonl`)을 다음 라운드 프롬프트에 넣되, 최소 시나리오 수 미만이면 경고.

### Promptbreeder — https://arxiv.org/abs/2309.16797
- 진화적 프롬프트 집단 + 자기참조적 변이 프롬프트. 주의: 수천 회 eval 아래에서는 과잉.

> **미채택** (수업 규모에 과함).

### Agent Lightning (Microsoft) — https://github.com/microsoft/agent-lightning
- 차용할 아이디어는 RL이 아니라 **프록시/게이트웨이가 수정되지 않은 에이전트의 궤적을 투명하게 포착**하는 구조.

> **차용**: provider 계층이 모든 호출을 trace에 기록. 에이전트 코드는 그것을 모른다.

### Self-Taught Evaluators (Meta) — https://arxiv.org/abs/2408.02666
- judge 자체를 개선. 주의: judge 드리프트 — 매 반복마다 소수의 사람 라벨 앵커 셋으로 재보정.

> **차용**: `calibrate`의 사람 라벨을 앵커로 보관하고, judge 프롬프트를 바꾸면 재보정을 요구한다.

### Eval-gated deployment / "prompt CI" (2025–26 실무 관행)
- 프롬프트 편집 = 커밋 → CI가 eval 실행 → 회귀면 **실패 예시를 붙여 PR을 막음** → 사람이 머지 → 롤백 = 태그 포인터 되돌리기.
- 잡음 흡수를 위한 최소 개선 임계(약 2–5%p).
- 주의: 실무 블로그이며 수치는 검증되지 않음.

> **차용**: 개선안 적용은 스냅샷 + 포인터. 롤백은 포인터 되돌리기(`improve --rollback`).

---

## 채택한 10가지 패턴과 구현 위치

| # | 패턴 | 출처 | 구현 |
|---|---|---|---|
| 1 | Task = dataset + solver + scorer | Inspect | `TestScenario` / `runtime` / `evaluator` |
| 2 | 선언적 YAML + 타입 있는 assertion 목록 + `view` | promptfoo, Inspect | `evaluator/rubrics/*.yaml`, `edu-agent view` |
| 3 | transcript보다 상태를 채점, transcript는 진단용 | τ-bench, Anthropic | 게이트 판정 + 학습자 상태 vs `Evidence` |
| 4 | pass^k, 저장된 궤적 재채점 | τ²-bench | `seeds`, `test --regrade` |
| 5 | 사용자 시뮬레이터를 1급 callable로 | openevals, DeepEval | `simulator/loop.py` |
| 6 | 단순한 무상태 루프, 선형 히스토리 | mini-swe-agent | `runtime/loop.py` |
| 7 | 훅/트립와이어 + 자율성 다이얼 | Claude Code, OpenAI SDK | `runtime/gates.py`, `improve --auto` |
| 8 | 파일시스템 우선 + 점진적 공개 | Eve, Agent Skills | 4개 MD + frontmatter |
| 9 | 최적화 계약 = 점수 + **텍스트 피드백**, held-out, Pareto, 예산, 계보 | GEPA | `optimizer/` |
| 10 | eval 게이트 승격 + 롤백 | prompt CI, 12-factor #7 | `optimizer/gate.py`, `improve --rollback` |
