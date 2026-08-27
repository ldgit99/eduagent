나는 다양한 사용자가 교육적으로 타당한 AI 에이전트를 쉽게 설계·구현·검증할 수 있도록 지원하는 오픈소스 CLI 기반 개발 하네스를 만들고자 한다.

프로젝트의 가칭은 `edu-agent-harness`로 한다.

이 프로젝트는 단순히 프롬프트나 에이전트 코드를 자동 생성하는 도구가 아니라, 사용자의 교육적 요구와 교수설계 원리를 구조화하고 이를 기술 명세와 실제 AI 에이전트의 행동 규칙으로 변환한 뒤, 테스트와 평가를 통해 설계 의도대로 실행되는지를 검증할 수 있는 “Pedagogy-Aware Educational AI Agent Engineering Harness”를 지향한다.

# 1. 프로젝트의 핵심 목표

다음 workflow를 지원하는 CLI 도구를 개발한다.

```text
edu-agent init
      ↓
사용자와 대화형 질문
      ↓
01_educational_design.md 생성
      ↓
설계원리 관련 질문
      ↓
02_design_principles.md 생성
      ↓
기술 요구 관련 질문 및 기술 스택 추천
      ↓
03_technical_spec.md 생성
      ↓
edu-agent compile
      ↓
04_agent_spec.md 생성
      ↓
edu-agent build
      ↓
에이전트 구현
      ↓
edu-agent test
      ↓
시뮬레이션 및 평가
      ↓
edu-agent improve
      ↓
개선안 제안 및 재검증
```

MVP에서는 우선 다음 명령어가 동작하도록 한다.

```bash
edu-agent init
edu-agent review
edu-agent compile
edu-agent build
edu-agent run
edu-agent test
edu-agent improve
```

# 2. 기본 기술 스택

우선 다음 기술을 기반으로 구현한다.

- Language: Python 3.12+
- Package / Environment Manager: uv
- CLI: Typer
- Terminal UI: Rich
- Data Validation / Schema: Pydantic
- Configuration: YAML
- 사용자 작성 문서: Markdown
- Template Engine: Jinja2
- LLM Provider Abstraction: 별도 provider abstraction layer 구현
- 초기 지원 AI Provider:
  - OpenAI
  - Anthropic
  - Google Gemini
  - Ollama 또는 local model
- Storage:
  - JSONL: trace 및 실행 로그
  - SQLite: 프로젝트 및 평가 결과
- Test: pytest
- Code Quality: Ruff
- Type Checking: Pyright
- CI/CD: GitHub Actions
- Distribution: GitHub + PyPI
- API key는 반드시 환경변수 또는 `.env`를 이용하며 Git에 저장하지 않는다.

특정 LLM provider나 agent framework에 전체 프로젝트가 종속되지 않도록 architecture를 구성한다.

# 3. 가장 중요한 설계 철학

이 프로젝트의 핵심은 다음 세 계층이다.

```text
Educational Design
        ↓
Technical Architecture
        ↓
Executable Agent Specification
```

AI가 교육적 판단을 대신하는 구조가 되어서는 안 된다.

사용자가 주로 결정해야 하는 것은 다음과 같다.

- 대상 학습자
- 학습 맥락
- 학습 문제
- 학습목표
- 학습활동
- 교수학습전략
- 설계원리
- AI가 반드시 해야 하는 행동
- AI가 해서는 안 되는 행동

하네스가 주로 지원해야 하는 것은 다음과 같다.

- 요구사항 구조화
- 누락된 정보 탐지
- 기술 스택 추천
- AI 역할 추천
- agent specification 생성
- system prompt 생성
- interaction policy 생성
- tool 및 memory configuration 생성
- test scenario 생성
- 실행 충실도 평가
- 개선안 생성

# 4. 프로젝트에서 사용하는 4개 핵심 Markdown 파일

모든 프로젝트는 기본적으로 다음 4개의 MD 파일을 사용한다.

```text
project/
├── 01_educational_design.md
├── 02_design_principles.md
├── 03_technical_spec.md
└── 04_agent_spec.md
```

## 4.1 `01_educational_design.md`

사용자와 대화를 통해 다음 내용을 구조화한다.

```md
# Educational Design

## 1. 학습 맥락
- 대상 학습자
- 연령 또는 학년
- 교과/영역
- 학습 주제
- 활용 상황
- 예상 사용자 수

## 2. 학습 문제
- 현재 학습자가 겪고 있는 어려움
- 해결하고자 하는 핵심 문제
- 기존 학습방법 또는 지원의 한계

## 3. 학습목표
- 학습목표 1
- 학습목표 2
- 학습목표 3

## 4. 학습활동
- 주요 학습활동
- 학습 순서
- 학생이 스스로 수행해야 하는 활동

## 5. AI 활용 맥락
- AI가 개입하는 시점
- AI 활용 전 학습자 활동
- AI 활용 중 학습자 활동
- AI 활용 후 학습자 활동

## 6. 기대하는 AI 지원
- 질문
- 힌트
- 피드백
- 설명
- 평가
- 추천
- 기타
```

`edu-agent init` 실행 시 사용자가 이 파일을 직접 작성하도록 하지 말고, CLI가 순차적으로 질문하고 응답을 구조화하여 파일을 생성한다.

한 번에 지나치게 많은 질문을 제시하지 않는다.

각 단계가 끝나면 다음과 같이 사용자에게 요약하여 확인한다.

```text
다음과 같이 이해했습니다.

대상 학습자:
중학교 2학년

학습 문제:
학생이 프로그램 오류 발생 시 스스로 원인을 분석하지 않고
AI에게 완성된 정답 코드를 바로 요구하는 경향이 있음.

이 내용이 맞습니까?

[Y] 확인
[E] 수정
[A] 내용 추가
```

사용자 확인 후 파일에 저장한다.

# 5. `02_design_principles.md`

이 파일은 이 프로젝트의 핵심 차별점이다.

다음 내용을 포함한다.

```md
# Design Principles

## 적용 이론 및 교수학습전략

## 설계원리 1
### 원리명
### 설명
### 설계지침
### AI의 필수 행동
### AI의 금지 행동
### 적용 조건

## 설계원리 2
...

## 학습자 주도성 원칙

## 스캐폴딩 원칙

## 피드백 원칙

## 성찰 및 자기조절 지원 원칙
```

사용자가 이미 연구 또는 문헌분석을 통해 도출한 설계원리를 가지고 있다면 직접 붙여넣거나 기존 Markdown을 사용할 수 있게 한다.

중요한 요구사항은 자연어 설계원리를 실제 AI 행동으로 변환하는 것이다.

예를 들어 다음 설계원리:

```text
점진적 스캐폴딩을 제공한다.
```

를 단순히 system prompt에 복사하지 않는다.

내부적으로 다음과 같은 실행 가능한 구조로 변환할 수 있도록 schema를 설계한다.

```yaml
principle:
  id: P02
  name: progressive_scaffolding

trigger:
  - learner_incorrect
  - learner_requests_help

behavior:
  level_1: ask_metacognitive_question
  level_2: provide_directional_hint
  level_3: provide_conceptual_hint
  level_4: provide_partial_example
  level_5: provide_detailed_explanation

constraints:
  direct_answer_before_level_4: false

evaluation:
  - hint_progression_correct
  - learner_reasoning_elicited
  - direct_answer_not_given_prematurely
```

다음 추적성이 반드시 유지되어야 한다.

```text
Design Principle
       ↓
Design Guideline
       ↓
Agent Behavior
       ↓
Interaction Rule
       ↓
Evaluation Criterion
       ↓
Test Scenario
```

# 6. `03_technical_spec.md`

교육적 설계 이후 기술 환경을 설정한다.

사용자에게 기술 이름부터 묻지 않는 것을 원칙으로 한다.

예를 들어 다음과 같이 묻는다.

잘못된 방식:

```text
Vector DB를 무엇으로 사용하시겠습니까?
Redis를 사용하시겠습니까?
```

권장 방식:

```text
AI가 별도의 교과서나 학습자료를 참고해야 합니까?

학생별 학습기록을 다음 접속에서도 기억해야 합니까?

학생은 웹 브라우저에서 이 에이전트를 사용합니까?

약 몇 명의 사용자가 사용할 예정입니까?

AI가 코드를 실제로 실행해야 합니까?
```

이 요구를 바탕으로 하네스가 기술 스택을 추천한다.

먼저 다음 선택지를 제공한다.

```text
기술적인 부분을 직접 선택하시겠습니까?

[1] 직접 선택
[2] 일부 선택 + 나머지는 추천
[3] 모두 추천
```

기술 명세에는 최소한 다음 항목을 포함한다.

```md
# Technical Specification

## AI Provider
- Provider
- Model
- API configuration

## Agent Architecture
- Single Agent / Multi-agent
- 선택 이유

## Backend
- Language
- Framework

## Frontend / Interface
- CLI
- Web Chat
- Streamlit
- Gradio
- React / Next.js
- LMS
- Existing application

## Data / RAG
- 필요 여부
- 데이터 소스
- Retrieval 방식
- Vector Store

## Memory
- Session memory
- Learner progress
- Long-term memory

## Tools
- Web search
- Calculator
- Code execution
- File retrieval
- Database
- External API
- LMS

## Storage
- Database
- Trace storage

## Deployment
- Local
- Docker
- Cloud
- Vercel
- Other

## Security
- API key
- 개인정보
- 로그
- 권한

## Technical Decisions
- 선택한 기술
- 선택 이유
```

예를 들어 다음과 같은 사용자 요구가 입력될 수 있다.

```text
중학생 30명이 웹에서 사용하는 C언어 디버깅 코치이다.
학생별 장기기억은 필요하지 않다.
학생이 입력한 C코드를 실제로 실행해 볼 필요가 있다.
별도의 교과서 검색은 필요 없다.
```

그러면 하네스는 다음과 같은 추천안을 만들 수 있어야 한다.

```text
AI       → OpenAI API
Backend  → FastAPI
Frontend → Next.js
Agent    → Single Agent
Storage  → SQLite
Memory   → Session only
RAG      → Not required
Tools    → Sandboxed Code Runner
Deploy   → Docker
```

추천 이유도 간단히 설명한다.

Multi-agent가 불필요한 경우에는 오히려 단일 agent를 추천한다.

# 7. `04_agent_spec.md`

앞의 세 문서를 종합하여 생성한다.

```text
01_educational_design.md
          +
02_design_principles.md
          +
03_technical_spec.md
          ↓
       Compiler
          ↓
04_agent_spec.md
```

이 파일은 사람이 읽을 수 있는 문서이면서 실제 구현에 사용되는 executable specification 역할을 해야 한다.

다음 항목을 포함한다.

```md
# Agent Specification

## 1. Agent Purpose

## 2. Target Learner

## 3. Learning Goals

## 4. Agent Role

## 5. Core Behaviors

## 6. Interaction Flow

## 7. Scaffolding Policy

## 8. Feedback Policy

## 9. Learner Agency Policy

## 10. Tool Policy

## 11. Memory Policy

## 12. Safety and Ethical Policy

## 13. System Prompt

## 14. Evaluation Criteria

## 15. Test Scenarios

## 16. Traceability
```

Traceability 섹션에서는 최소한 다음 관계를 확인할 수 있어야 한다.

```text
P01 설계원리
→ B03 Agent Behavior
→ E02 Evaluation Criterion
→ T04 Test Scenario
```

# 8. Agent Compiler

`edu-agent compile`을 구현한다.

Compiler는 세 개의 입력 문서를 읽는다.

```text
01_educational_design.md
02_design_principles.md
03_technical_spec.md
```

그리고 다음 작업을 수행한다.

1. 필수 항목 누락 검사
2. 교육목표와 AI 역할 간 정렬 확인
3. 설계원리와 AI 행동 간 정렬
4. 서로 충돌하는 설계원리 검사
5. 기술적 구현 가능성 검사
6. 안전·윤리 관련 기본 규칙 추가
7. system prompt 생성
8. interaction policy 생성
9. evaluation criteria 생성
10. test scenario 생성
11. `04_agent_spec.md` 생성

# 9. Agent Builder

`edu-agent build`을 구현한다.

`04_agent_spec.md`와 내부 structured schema를 이용하여 실제 실행 가능한 agent project를 생성한다.

가능하면 다음 형태로 생성한다.

```text
generated-agent/
├── app/
│   ├── agent.py
│   ├── prompts/
│   ├── policies/
│   ├── tools/
│   └── safety/
│
├── evals/
│   ├── scenarios/
│   ├── personas/
│   └── rubric.yaml
│
├── tests/
├── .env.example
├── pyproject.toml
└── README.md
```

MVP에서는 모든 종류의 frontend나 backend를 완벽하게 생성하려고 하지 않는다.

우선 다음 두 가지 구현 경로를 안정적으로 지원한다.

1. Python CLI Agent
2. Python FastAPI Agent

추후 Next.js frontend 등을 추가할 수 있도록 adapter 또는 template architecture를 구성한다.

# 10. Student Simulator

교육용 AI 에이전트가 실제 다양한 학생에게 어떻게 반응하는지 평가하기 위해 synthetic learner simulator를 구현한다.

기본 persona 예시는 다음과 같다.

```text
Persona A
성취수준 높음
학습동기 높음
AI 도움을 거의 요구하지 않음

Persona B
성취수준 중간
일부 오개념 존재
부분적 힌트 필요

Persona C
성취수준 낮음
도움을 자주 요청함

Persona D
AI 의존성이 높음
계속 완성된 정답을 요구함

Persona E
수업과 관련 없는 질문을 반복함

Persona F
잘못된 가설이나 오개념을 강하게 주장함
```

향후 사용자가 persona를 추가할 수 있도록 확장 가능한 구조로 만든다.

# 11. Educational Evaluator

`edu-agent test`는 단순 unit test뿐 아니라 교육적 실행 충실도 평가를 수행한다.

최소 평가 영역은 다음과 같이 구성한다.

1. 학습목표 정렬성
2. 교수전략 실행 충실도
3. 설계원리 실행 충실도
4. 적응적 지원
5. 학습자 주도성 지원
6. 상호작용 적절성
7. 피드백 적절성
8. 안전·윤리적 실행
9. 기술적 안정성

평가 결과는 예를 들어 다음처럼 표시한다.

```text
Educational Agent Evaluation

Goal Alignment                  4.6 / 5
Pedagogical Fidelity            4.2 / 5
Design Principle Fidelity       4.4 / 5
Adaptive Support                4.0 / 5
Learner Agency                  4.7 / 5
Interaction Quality             4.3 / 5
Safety & Ethics                 5.0 / 5

Overall                         4.46 / 5
```

점수만 제시하지 말고 근거를 trace와 함께 표시한다.

예:

```text
FAIL: P02-03

Design Principle:
학습자의 사고를 확인한 후 힌트를 제공한다.

Observed Behavior:
학생의 첫 질문 직후 예제 코드를 제공함.

Expected Behavior:
학생의 현재 추론을 먼저 질문해야 함.

Recommendation:
learner_reasoning elicitation 단계를 interaction policy에 추가할 것.
```

# 12. 평가 방식

Evaluator는 다음 세 가지 방식의 결합을 고려한다.

- deterministic checks
- LLM-based evaluation
- human review

MVP에서는 다음을 구현한다.

```text
Deterministic Evaluator
+
LLM Evaluator
```

추후 human evaluator 결과를 입력할 수 있도록 schema를 준비한다.

# 13. Improve Loop

`edu-agent improve`는 자동으로 코드와 설계원리를 무제한 수정하는 self-evolving agent로 만들지 않는다.

다음 방식으로 구현한다.

```text
Build
 ↓
Simulate
 ↓
Evaluate
 ↓
Diagnose
 ↓
Improvement Proposal
 ↓
User Review
 ↓
Apply
 ↓
Re-test
```

즉, `eval-guided iterative improvement`를 사용한다.

중요한 수정은 사용자가 승인해야 한다.

다음과 같은 UX를 제공한다.

```text
3개의 개선안을 발견했습니다.

[1] Scaffolding threshold 조정
이유:
초기 단계에서 지나치게 많은 정보를 제공합니다.

[2] Learner reasoning 질문 추가
이유:
학생의 사고과정을 확인하기 전에 힌트가 제공됩니다.

[3] Reflection prompt 추가
이유:
문제 해결 후 학습자의 설명 활동이 누락되었습니다.

어떤 변경을 적용하시겠습니까?

[1,2,3]
[A] 모두 적용
[N] 적용하지 않음
```

# 14. CLI UX 원칙

사용자는 개발자가 아닐 수도 있다.

따라서 다음 원칙을 따른다.

- 전문 기술 용어를 먼저 사용하지 않는다.
- 요구를 먼저 질문한다.
- 기술은 요구에 따라 추천한다.
- 모든 기술 선택에는 `잘 모르겠음 / 추천` 옵션을 제공한다.
- 한 번에 지나치게 많은 질문을 하지 않는다.
- 질문 → 응답 → AI 구조화 → 사용자 확인 → 저장의 workflow를 사용한다.
- Rich를 활용하여 단계, 상태, 경고, 성공 여부를 읽기 쉽게 표현한다.

예:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 / 4
교육적 설계원리
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AI가 학생에게 정답을 바로 제공해도 됩니까?

[1] 제공하지 않음
[2] 일정 조건에서만 제공
[3] 제공 가능
[4] 직접 입력
```

# 15. 보안 원칙

다음을 기본적으로 적용한다.

- API Key를 코드 또는 MD에 저장하지 않는다.
- `.env`는 `.gitignore`에 포함한다.
- `.env.example`만 repository에 포함한다.
- 사용자 입력과 시스템 프롬프트를 분리한다.
- 외부 tool 실행에 permission boundary를 둔다.
- 코드 실행 기능이 있을 경우 sandbox architecture를 사용한다.
- 학생 개인정보 저장 여부를 명확히 표시한다.
- 민감정보가 trace에 불필요하게 저장되지 않도록 한다.
- prompt injection 및 tool misuse를 고려할 수 있는 구조로 만든다.
- 자동 생성 코드의 shell command, file access, network access를 제한할 수 있도록 설계한다.

# 16. 프로젝트 내부 구조

초기 repository를 다음과 유사하게 구성하라.

```text
edu-agent-harness/
├── src/
│   └── edu_agent/
│       ├── cli.py
│       │
│       ├── questionnaire/
│       │   ├── educational.py
│       │   ├── principles.py
│       │   └── technical.py
│       │
│       ├── schemas/
│       │   ├── educational.py
│       │   ├── principles.py
│       │   ├── technical.py
│       │   └── agent.py
│       │
│       ├── compiler/
│       ├── builder/
│       ├── providers/
│       ├── simulator/
│       ├── evaluator/
│       ├── optimizer/
│       ├── storage/
│       ├── security/
│       └── utils/
│
├── templates/
│   ├── educational_design.md.j2
│   ├── design_principles.md.j2
│   ├── technical_spec.md.j2
│   └── agent_spec.md.j2
│
├── examples/
│   └── c-debugging-coach/
│
├── tests/
├── docs/
├── .github/
│   └── workflows/
├── .env.example
├── .gitignore
├── pyproject.toml
├── LICENSE
└── README.md
```

필요하면 더 나은 구조를 제안해도 되지만, 지나치게 복잡한 architecture는 피한다.

# 17. MVP에서 하지 않을 것

첫 번째 버전에서는 다음을 억지로 구현하지 않는다.

- 복잡한 multi-agent orchestration
- 모든 LLM provider 완전 지원
- 복잡한 RAG framework
- Kubernetes
- 대규모 cloud infrastructure
- SaaS user authentication
- 결제 시스템
- production scale multi-tenancy
- 자동 배포
- 무제한 self-modifying agent

MVP의 핵심은 다음이다.

```text
Educational Requirement
        ↓
Design Principles
        ↓
Technical Specification
        ↓
Agent Specification
        ↓
Build
        ↓
Simulation
        ↓
Educational Evaluation
```

# 18. Example Project

기능 검증을 위해 `C Programming Debugging Coach` 예제를 함께 만든다.

예제 조건:

- 대상: 중학교 또는 고등학교 초급 C언어 학습자
- 문제: 오류 발생 시 스스로 디버깅하지 않고 AI에게 정답 코드를 요구함
- 목표:
  - 오류 발생 지점을 탐색할 수 있음
  - 오류 원인을 설명할 수 있음
  - AI의 힌트를 이용하여 스스로 코드를 수정할 수 있음
- 주요 설계원리:
  - 학습자 주도적 문제해결
  - 점진적 스캐폴딩
  - 질문 기반 사고 촉진
  - 피드백
  - 성찰
- AI 역할:
  - Debugging Coach
- 핵심 행동:
  - 정답을 즉시 제공하지 않음
  - 학생의 현재 생각을 먼저 질문
  - 최소한의 힌트부터 제공
  - 학생 반응에 따라 도움 수준을 증가
  - 해결 후 문제해결 과정을 설명하도록 요청
- 금지 행동:
  - 처음부터 완성된 정답 코드 제공
  - 학생 대신 과제를 수행
- 테스트 사례:
  - 학생이 바로 정답을 요구
  - 동일한 오류를 반복
  - 잘못된 원인을 주장
  - 도움을 여러 번 요청
  - 수업과 무관한 질문
  - 개인정보 입력

이 예제를 통해 전체 workflow가 실제로 동작하는지 검증한다.

# 19. 개발 방식

바로 모든 기능을 한꺼번에 구현하지 말고 단계적으로 진행한다.

우선 repository를 분석하고 다음 순서로 작업하라.

## Phase 1
- 프로젝트 skeleton
- uv / pyproject 설정
- Typer CLI
- `edu-agent --help`
- `edu-agent init`

## Phase 2
- Pydantic schemas
- questionnaire
- 4개 Markdown 생성
- 사용자 확인 및 수정 workflow

## Phase 3
- LLM provider abstraction
- compiler
- `04_agent_spec.md` 자동 생성

## Phase 4
- build / run

## Phase 5
- learner simulator
- evaluator
- test

## Phase 6
- improve loop
- traceability
- report

각 phase마다 pytest 테스트를 작성하고 기존 테스트가 통과하는지 확인하라.

# 20. 지금 수행할 작업

먼저 다음 작업부터 수행하라.

1. 위 요구사항을 분석한다.
2. 과도하게 복잡하거나 서로 충돌하는 부분이 있는지 검토한다.
3. MVP architecture를 제안한다.
4. repository directory structure를 확정한다.
5. Pydantic 기반 핵심 domain model을 설계한다.
6. CLI command structure를 설계한다.
7. Phase 1을 실제로 구현한다.
8. 테스트를 실행한다.
9. README에 현재 구현된 기능과 다음 개발 단계를 기록한다.

중요한 architectural decision에는 간단한 이유를 남겨라.

불필요한 framework를 추가하지 말고 Python 표준 라이브러리와 가벼운 dependency를 우선 사용하라.

코드를 작성하기 전에 전체 계획만 길게 설명하고 멈추지 말고, 합리적인 가정을 세운 뒤 실제 파일을 생성하고 구현을 진행하라.

기존 파일이 있다면 먼저 repository 구조와 내용을 확인한 뒤 기존 코드를 최대한 보존하면서 수정하라.