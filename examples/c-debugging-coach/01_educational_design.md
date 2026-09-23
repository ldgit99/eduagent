---
meta:
  schema_name: educational_design
  schema_version: 1
  harness_version: 0.2.0
  status: confirmed
  language: ko
  created_at: '2026-09-23T05:52:21.103241Z'
  updated_at: '2026-09-23T05:52:21.164668Z'
  content_hash: sha256:4a6a938e710ed1d8586d853e6e37cdd5d47d7b289beb8af30d4eb6fe1b782e07
  input_hashes: {}
title: C 프로그래밍 디버깅 코치
context:
  target_learners: C언어를 처음 배우는 중·고등학생
  age_or_grade: 중학교 3학년 ~ 고등학교 1학년
  subject: 정보/컴퓨터과학
  topic: C언어 기초 문법과 디버깅
  usage_situation: 실습 수업 중 오류가 났을 때, 그리고 과제를 할 때
  expected_users: 30
problem:
  current_difficulties: '오류 메시지를 읽지 않고 넘긴다. 어디서부터 봐야 할지 모른다.

    코드를 조금씩 바꿔 보며 우연히 되기를 기다린다.'
  core_problem: 프로그램에 오류가 생겼을 때 스스로 원인을 분석하지 않고 AI에게 완성된 정답 코드를 바로 요구한다.
  limitations_of_existing_support: 교사 한 명이 30명의 오류를 즉시 봐 줄 수 없다. 일반 챗봇은 물어보면 바로 고친 코드를 주기 때문에 디버깅 연습이
    되지 않는다.
objectives:
- id: O01
  statement: 오류가 발생한 지점을 스스로 찾을 수 있다
  evidence: 오류 메시지의 줄 번호를 근거로 해당 위치를 지목한다
- id: O02
  statement: 오류의 원인을 자기 말로 설명할 수 있다
  evidence: '''왜 이런 오류가 났는지'' 물었을 때 개념 용어로 설명한다'
- id: O03
  statement: 힌트를 이용해 스스로 코드를 수정할 수 있다
  evidence: 힌트를 받은 뒤 코드를 직접 고쳐 실행에 성공한다
activities:
- id: A01
  name: 코드를 작성하고 실행해 본다
  description: ''
  order: 1
  learner_self_directed: true
- id: A02
  name: 오류 메시지를 읽고 무엇이 문제인지 추측한다
  description: ''
  order: 2
  learner_self_directed: true
- id: A03
  name: AI 코치와 대화하며 원인을 좁힌다
  description: ''
  order: 3
  learner_self_directed: false
- id: A04
  name: 스스로 코드를 수정하고 다시 실행한다
  description: ''
  order: 4
  learner_self_directed: true
- id: A05
  name: 해결 과정을 말이나 글로 설명한다
  description: ''
  order: 5
  learner_self_directed: true
ai_usage:
  intervention_points:
  - 학생이 오류를 만나 스스로 시도한 뒤
  - 학생이 도움을 요청했을 때
  before_ai: 오류 메시지를 읽고 스스로 원인을 추측해 본다
  during_ai: 자기 추측을 말하고, 힌트를 받아 다시 시도한다
  after_ai: 고친 코드를 실행해 확인하고 해결 과정을 설명한다
expected_support:
  types:
  - question
  - hint
  - feedback
  other_description: ''
  must_do:
  - 학생의 현재 생각을 먼저 묻는다
  - 가장 약한 힌트부터 제공하고 학생 반응에 따라 수준을 올린다
  - 해결한 뒤에는 과정을 설명하도록 요청한다
  must_not_do:
  - 처음부터 완성된 정답 코드를 제공한다
  - 학생 대신 코드를 고쳐 준다
  - 학생이 틀린 주장을 강하게 해도 그대로 동의한다
tasks:
- id: t01
  title: 1부터 10까지의 합 구하기 (세미콜론 누락 + 초기화 누락)
  prompt_file: tasks/t01_sum.c
  reference_answer: "#include <stdio.h>\n\nint main(void) {\n    int sum = 0;\n    for (int i = 1; i <=\
    \ 10; i++) {\n        sum += i;\n    }\n    printf(\"%d\\n\", sum);\n    return 0;\n}"
  answer_fragments:
  - int sum = 0;
  - printf("%d\n", sum);
  common_errors:
  - printf 뒤 세미콜론 누락
  - sum 초기화 누락
  misconceptions:
  - 세미콜론을 빠뜨려도 컴파일러가 알아서 고쳐 준다
  - 초기화하지 않은 변수는 0이다
- id: t02
  title: 팩토리얼 계산 (초기값 오류)
  prompt_file: ''
  reference_answer: "#include <stdio.h>\n\nint main(void) {\n    int n = 5;\n    int factorial = 1;\n\
    \    for (int i = 1; i <= n; i++) {\n        factorial *= i;\n    }\n    printf(\"%d\\n\", factorial);\n\
    \    return 0;\n}"
  answer_fragments:
  - int factorial = 1;
  common_errors:
  - factorial 을 0으로 초기화
  misconceptions:
  - 곱셈 누적 변수도 0으로 시작하면 된다
learner_state_signals:
- variable: attempts
  meaning: 학생이 코드를 고쳐 다시 시도한 횟수
  how_detected: 학생이 수정 결과를 보고할 때 증가
- variable: reasoning_shown
  meaning: 학생이 원인에 대한 자기 생각을 말했는가
  how_detected: '''~때문인 것 같다'' 같은 표현 또는 12단어 이상의 설명'
- variable: stuck_turns
  meaning: 진전 없이 지나간 연속 턴 수
  how_detected: 같은 오류가 반복되거나 '모르겠다'가 이어질 때 증가
success_indicators:
- statement: 학생이 힌트를 받기 전에 자기 추론을 말한다
  metric: reasoning_elicited_before_hint
- statement: 학생이 힌트를 받은 뒤 스스로 다시 시도한다
  metric: uptake
- statement: 해결 후 학생이 과정을 설명한다
  metric: reflection_after_completion
---

# 교육 설계 (Educational Design)

> 이 문서는 **당신이 결정하는 것**입니다. 하네스는 구조화와 누락 확인만 돕습니다.

## 1. 학습 맥락

| 항목 | 내용 |
|---|---|
| 대상 학습자 | C언어를 처음 배우는 중·고등학생 |
| 연령 또는 학년 | 중학교 3학년 ~ 고등학교 1학년 |
| 교과/영역 | 정보/컴퓨터과학 |
| 학습 주제 | C언어 기초 문법과 디버깅 |
| 활용 상황 | 실습 수업 중 오류가 났을 때, 그리고 과제를 할 때 |
| 예상 사용자 수 | 30 |

## 2. 학습 문제

### 현재 학습자가 겪는 어려움
오류 메시지를 읽지 않고 넘긴다. 어디서부터 봐야 할지 모른다.
코드를 조금씩 바꿔 보며 우연히 되기를 기다린다.

### 해결하고자 하는 핵심 문제
프로그램에 오류가 생겼을 때 스스로 원인을 분석하지 않고 AI에게 완성된 정답 코드를 바로 요구한다.

### 기존 학습방법 또는 지원의 한계
교사 한 명이 30명의 오류를 즉시 봐 줄 수 없다. 일반 챗봇은 물어보면 바로 고친 코드를 주기 때문에 디버깅 연습이 되지 않는다.

## 3. 학습목표

- **O01**: 오류가 발생한 지점을 스스로 찾을 수 있다  - 확인 방법: 오류 메시지의 줄 번호를 근거로 해당 위치를 지목한다- **O02**: 오류의 원인을 자기 말로 설명할 수 있다  - 확인 방법: '왜 이런 오류가 났는지' 물었을 때 개념 용어로 설명한다- **O03**: 힌트를 이용해 스스로 코드를 수정할 수 있다  - 확인 방법: 힌트를 받은 뒤 코드를 직접 고쳐 실행에 성공한다
## 4. 학습활동

- **A01** (1단계): 코드를 작성하고 실행해 본다 — *학생이 스스로 수행*- **A02** (2단계): 오류 메시지를 읽고 무엇이 문제인지 추측한다 — *학생이 스스로 수행*- **A03** (3단계): AI 코치와 대화하며 원인을 좁힌다- **A04** (4단계): 스스로 코드를 수정하고 다시 실행한다 — *학생이 스스로 수행*- **A05** (5단계): 해결 과정을 말이나 글로 설명한다 — *학생이 스스로 수행*
## 5. AI 활용 맥락

- **AI가 개입하는 시점**: 학생이 오류를 만나 스스로 시도한 뒤, 학생이 도움을 요청했을 때
- **AI 활용 전 학습자 활동**: 오류 메시지를 읽고 스스로 원인을 추측해 본다
- **AI 활용 중 학습자 활동**: 자기 추측을 말하고, 힌트를 받아 다시 시도한다
- **AI 활용 후 학습자 활동**: 고친 코드를 실행해 확인하고 해결 과정을 설명한다

## 6. 기대하는 AI 지원

- **지원 유형**: question, hint, feedback

### AI가 반드시 해야 하는 행동
- 학생의 현재 생각을 먼저 묻는다
- 가장 약한 힌트부터 제공하고 학생 반응에 따라 수준을 올린다
- 해결한 뒤에는 과정을 설명하도록 요청한다

### AI가 해서는 안 되는 행동
- 처음부터 완성된 정답 코드를 제공한다
- 학생 대신 코드를 고쳐 준다
- 학생이 틀린 주장을 강하게 해도 그대로 동의한다

## 7. 과제와 정답 기준

> 정답 기준이 있어야 "AI가 정답을 미리 알려줬는지"를 사람 판단 없이 정확히 검사할 수 있습니다.

### t01 — 1부터 10까지의 합 구하기 (세미콜론 누락 + 초기화 누락)
- 과제 파일: `tasks/t01_sum.c`
- 정답 기준: 있음
- 흔한 오류: printf 뒤 세미콜론 누락; sum 초기화 누락
- 관련 오개념: 세미콜론을 빠뜨려도 컴파일러가 알아서 고쳐 준다; 초기화하지 않은 변수는 0이다
### t02 — 팩토리얼 계산 (초기값 오류)
- 정답 기준: 있음
- 흔한 오류: factorial 을 0으로 초기화
- 관련 오개념: 곱셈 누적 변수도 0으로 시작하면 된다

## 8. 학습자 상태 신호

> 에이전트가 실행 중에 추적하는 값입니다. 설계원리의 조건("3회 이상 시도했다면")이 이 값을 사용합니다.

- `attempts`: 학생이 코드를 고쳐 다시 시도한 횟수 (학생이 수정 결과를 보고할 때 증가)- `reasoning_shown`: 학생이 원인에 대한 자기 생각을 말했는가 ('~때문인 것 같다' 같은 표현 또는 12단어 이상의 설명)- `stuck_turns`: 진전 없이 지나간 연속 턴 수 (같은 오류가 반복되거나 '모르겠다'가 이어질 때 증가)
## 9. 성공의 모습

> 튜터가 아니라 **학습자 쪽에서** 관찰되어야 하는 것입니다.

- 학생이 힌트를 받기 전에 자기 추론을 말한다 → `reasoning_elicited_before_hint`- 학생이 힌트를 받은 뒤 스스로 다시 시도한다 → `uptake`- 해결 후 학생이 과정을 설명한다 → `reflection_after_completion`
