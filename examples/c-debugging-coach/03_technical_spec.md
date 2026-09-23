---
meta:
  schema_name: technical_spec
  schema_version: 1
  harness_version: 0.2.0
  status: confirmed
  language: ko
  created_at: '2026-09-23T05:44:58.664221Z'
  updated_at: '2026-09-23T05:44:58.708914Z'
  content_hash: sha256:581f1ad194a408812da3fcf3d8db6022ec5ddeea50e0cbf01aee62eac46bfbe5
  input_hashes: {}
execution_path: harness_runtime
requirements:
  needs_external_materials: false
  needs_persistent_learner_memory: false
  uses_web_browser: true
  expected_users: 30
  needs_code_execution: true
  needs_multimodal_input: false
  needs_lms_integration: false
  must_run_offline_or_local: false
  data_sensitivity: 학생 이름·학번은 저장하지 않는다.
  selection_mode: recommend_all
ai_provider:
  provider: openai
  model: ''
  judge_model: ''
  student_model: ''
  api_config: {}
  max_tokens_per_session: 20000
architecture:
  kind: single_agent
  reason: 하나의 역할(튜터)만 필요합니다. 다중 에이전트는 복잡도만 늘리고 교육적 이득이 없습니다.
backend:
  language: python
  framework: none
interface:
  kind: web_chat
  notes: edu-agent run --web 로 로컬 웹 채팅을 엽니다. 추가 설치가 필요 없습니다.
data_rag:
  required: false
  sources: []
  retrieval: none
  vector_store: ''
memory:
  session_memory: true
  learner_progress: false
  long_term_memory: false
  retention_note: 대화가 끝나면 기억하지 않습니다.
tools:
- kind: code_execution
  description: 학습자 코드를 안전한 환경에서 실행합니다.
  sandboxed: true
  permissions:
  - network:none
  - fs:tmp-only
  - timeout:5s
  - memory:256m
  when_allowed: reasoning_shown == true
storage:
  database: sqlite
  trace_storage: jsonl
deployment:
  kind: local
  notes: ''
security:
  api_keys_via_env: true
  stores_personal_data: false
  personal_data_note: ''
  logs_conversations: true
  log_redaction: true
  roles:
  - learner
decisions:
- area: 실행 방식
  choice: 하네스 런타임 (edu-agent run)
  reason: 코드를 만들지 않고 04 문서를 그대로 실행합니다. 설계를 고치면 곧바로 반영되고, 정책 게이트가 한 곳에서만 관리됩니다.
  origin: recommended
- area: 사용 화면
  choice: 로컬 웹 채팅
  reason: 학습자가 브라우저에서 사용한다고 하셨습니다.
  origin: recommended
- area: 에이전트 구조
  choice: 단일 에이전트
  reason: 하나의 역할(튜터)만 필요합니다. 다중 에이전트는 복잡도만 늘리고 교육적 이득이 없습니다.
  origin: recommended
- area: 자료 검색
  choice: 사용하지 않음
  reason: 별도 자료 참고가 필요하지 않다고 하셨습니다.
  origin: recommended
- area: 기억
  choice: 세션 동안만
  reason: 장기 기억이 필요 없으면 저장하지 않는 것이 개인정보 측면에서 안전합니다.
  origin: recommended
- area: 도구
  choice: 샌드박스 코드 실행기
  reason: 코드를 실제로 실행해야 한다고 하셨습니다. 네트워크를 막고 임시 폴더에서만 5초 제한으로 실행합니다. 학습자가 자기 생각을 말한 뒤에만 실행합니다 (조건을 비우면 항상
    실행할 수 있습니다).
  origin: recommended
- area: 서버
  choice: 필요 없음
  reason: 하네스 런타임이 직접 실행하므로 별도 서버가 없습니다.
  origin: recommended
- area: 배포
  choice: 각자 컴퓨터에서 실행
  reason: 수업 규모에서는 별도 서버가 필요하지 않습니다.
  origin: recommended
---

# 기술 명세 (Technical Specification)

> 기술 이름을 먼저 정하지 않습니다. **무엇이 필요한지**를 정하면 하네스가 추천합니다.

## 0. 요구사항 (당신이 답한 것)

| 질문 | 답 |
|---|---|
| AI가 별도의 교과서나 학습자료를 참고해야 합니까? | 아니오 |
| 학생별 학습기록을 다음 접속에서도 기억해야 합니까? | 아니오 |
| 학생은 웹 브라우저에서 사용합니까? | 예 |
| 약 몇 명이 사용할 예정입니까? | 30 |
| AI가 코드를 실제로 실행해야 합니까? | 예 |
| 이미지나 파일을 입력받아야 합니까? | 아니오 |
| LMS와 연동해야 합니까? | 아니오 |
| 인터넷 없이 로컬에서 돌아야 합니까? | 아니오 |

- 개인정보 관련 메모: 학생 이름·학번은 저장하지 않는다.

## 1. 실행 방식

- **하네스 런타임 (edu-agent run) — 코드를 만들지 않고 04 문서를 그대로 실행**

## 2. AI Provider

| 항목 | 값 |
|---|---|
| Provider | openai |
| 튜터 모델 | .env 의 EDU_AGENT_MODEL 사용 |
| 평가자 모델 | 튜터와 동일 (다른 모델 권장) |
| 시뮬레이션 학생 모델 | 템플릿 사용 (모델 호출 없음) |
| 세션당 토큰 상한 | 20000 |

> API 키는 이 문서에 적지 않습니다. `.env` 파일의 `EDU_AGENT_API_KEY` 에서 읽습니다.

## 3. 에이전트 구조

- **단일 에이전트**
- 이유: 하나의 역할(튜터)만 필요합니다. 다중 에이전트는 복잡도만 늘리고 교육적 이득이 없습니다.

## 4. 사용 화면

- web_chat — edu-agent run --web 로 로컬 웹 채팅을 엽니다. 추가 설치가 필요 없습니다.
## 5. 자료 검색 (RAG)

- **필요 여부**: 아니오

## 6. 기억

| 범위 | 사용 |
|---|---|
| 대화 중 기억 | 예 |
| 학습자 진도 | 아니오 |
| 장기 기억 | 아니오 |

- 대화가 끝나면 기억하지 않습니다.

## 7. 도구

### code_execution
- 학습자 코드를 안전한 환경에서 실행합니다.
- 샌드박스: 예
- 쓸 수 있는 조건: reasoning_shown == true
- 권한: `network:none`, `fs:tmp-only`, `timeout:5s`, `memory:256m`

## 8. 저장

- 데이터베이스: sqlite
- 실행 기록(trace): jsonl — `.edu-agent/` 폴더에만 저장되며 Git에 올라가지 않습니다.

## 9. 배포

- local
## 10. 보안·개인정보

| 항목 | 값 |
|---|---|
| API 키를 환경변수로 관리 | 예 |
| 개인정보 저장 | 아니오 |
| 대화 기록 저장 | 예 |
| 기록에서 개인정보 가림 | 예 |
| 역할 | learner |


## 11. 기술 결정과 이유

| 영역 | 선택 | 이유 | 결정 주체 |
|---|---|---|---|
| 실행 방식 | 하네스 런타임 (edu-agent run) | 코드를 만들지 않고 04 문서를 그대로 실행합니다. 설계를 고치면 곧바로 반영되고, 정책 게이트가 한 곳에서만 관리됩니다. | 하네스 추천 |
| 사용 화면 | 로컬 웹 채팅 | 학습자가 브라우저에서 사용한다고 하셨습니다. | 하네스 추천 |
| 에이전트 구조 | 단일 에이전트 | 하나의 역할(튜터)만 필요합니다. 다중 에이전트는 복잡도만 늘리고 교육적 이득이 없습니다. | 하네스 추천 |
| 자료 검색 | 사용하지 않음 | 별도 자료 참고가 필요하지 않다고 하셨습니다. | 하네스 추천 |
| 기억 | 세션 동안만 | 장기 기억이 필요 없으면 저장하지 않는 것이 개인정보 측면에서 안전합니다. | 하네스 추천 |
| 도구 | 샌드박스 코드 실행기 | 코드를 실제로 실행해야 한다고 하셨습니다. 네트워크를 막고 임시 폴더에서만 5초 제한으로 실행합니다. 학습자가 자기 생각을 말한 뒤에만 실행합니다 (조건을 비우면 항상 실행할 수 있습니다). | 하네스 추천 |
| 서버 | 필요 없음 | 하네스 런타임이 직접 실행하므로 별도 서버가 없습니다. | 하네스 추천 |
| 배포 | 각자 컴퓨터에서 실행 | 수업 규모에서는 별도 서버가 필요하지 않습니다. | 하네스 추천 |
