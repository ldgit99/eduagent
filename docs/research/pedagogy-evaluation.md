# LLM 튜터의 교육학적 품질 평가 (2023–2026)

조사: 2026-08-27. 이 문서는 `evaluator/`의 9개 평가 영역과 루브릭이 어디에서 왔는지를 기록한다.

## 1. 주요 루브릭과 그 차원

### LearnLM (Google) — 5원칙
[arXiv 2407.12687](https://arxiv.org/abs/2407.12687) · [2412.16429](https://arxiv.org/abs/2412.16429) · [2505.24477](https://arxiv.org/abs/2505.24477)

능동학습 촉진 / 인지부하 관리 / 메타인지 심화 / 동기·호기심 자극 / 학습자 목표·요구 적응.

핵심 개념은 **pedagogical instruction following**: 교육학을 하나의 고정된 정의로 두지 않고,
시스템 지시를 하드 제약("정답을 공개하지 말 것")과 소프트 지침("격려하는 언어를 쓸 것")으로
나눈 뒤 그 지시를 얼마나 따르는지로 평가한다.
→ 이 하네스의 `Strength.HARD` / `Strength.SOFT` 구분이 여기서 왔다.

**Arena for Learning(2025)의 25개 세부 항목**이 가장 세밀한 공개 루브릭이다.

| 원칙 | 항목 수 | 주목할 항목 |
|---|---|---|
| 인지부하 | 9 | 길이, 청킹, 명료성, 불필요 정보 없음, 유추, 순서, 반복 최소화, 모순 없음 |
| 능동학습 | 4 | 참여 기회, 사고를 자극하는 질문, **정답을 너무 빨리 주지 않음**, 능동 참여 촉진 |
| 메타인지 | 4 | 학생이 스스로 실수를 발견하도록 안내, 건설적 피드백, 정확성 인정, 계획·목표 소통 |
| 호기심 | 3 | 흥미 자극, 좌절에 대한 반응, 격려적 피드백 |
| 적응성 | 5 | 수준 맞춤 설명, 막혔을 때 도움, 전반적 적응, 선제적 안내, **정보를 비생산적으로 보류하지 않음** |

> **가장 중요한 함의**: "정답을 너무 빨리 줌"과 "정보를 비생산적으로 보류함"이 **동시에 감점**이다.
> 따라서 "절대 정답 금지"는 잘못된 하드 규칙이며, 조건(학습자 상태)에 묶여야 한다.

비판: Roschelle, McLaughlin & Koedinger, *Beyond Benchmarks* (CACM 2025) —
[링크](https://cacm.acm.org/opinion/beyond-benchmarks-responsible-ai-in-education-needs-learning-sciences/) —
평가가 튜터 상호작용에 좁게 집중하고 지시 따르기를 총체적 적응성보다 우선한다는 지적.

### MRBench / Unifying AI Tutor Evaluation
Maurya et al., NAACL 2025 — [2412.09416](https://arxiv.org/abs/2412.09416) ·
[코드](https://github.com/kaushal0494/UnifyingAITutorEvaluation)

8차원, 모두 3단계 라벨: **오류 식별 / 오류 위치 / 정답 노출 / 안내 제공 / 실행가능성(actionability)
/ 일관성 / 튜터 어조 / 인간다움**. 192개 대화, 1,596개 응답, 인간 일치도 κ=0.71.

→ 이 하네스의 3단계 `Label(YES/PARTIAL/NO)`이 여기서 왔다.

### BEA 2025 Shared Task
Kochmar et al. — [2507.10579](https://arxiv.org/abs/2507.10579)

50개 이상 팀. 최고 macro-F1(exact/lenient): 오류 식별 0.72/0.92, 오류 위치 0.60/0.84,
안내 제공 0.58/0.79, actionability 0.71/0.87. 인간 Fleiss κ=0.65.
**"어느 정도(To some extent)" 중간 라벨이 지속적 실패 지점.**

→ 중간 라벨을 pass/fail로 접지 않고 별도 클래스로 유지하는 이유.

### Bridge (Stanford)
Wang, Zhang, Robinson, Loeb, Demszky, NAACL 2024 — [2310.10648](https://arxiv.org/abs/2310.10648)

전문가의 교정을 **의사결정 사슬**(오류 유형 → 교정 전략 → 의도 → 응답)로 분석. 실제 튜터링 대화 700건.
전문가 결정을 조건으로 준 GPT-4는 선호도 +76%, 무작위 결정은 −97%.

> **함의**: 문장 유창성이 아니라 *어떤 결정을 했는가*가 품질을 좌우한다.
> → 런타임이 모델에게 `declared_action`을 명시적으로 선언시키는 이유.

### MathDial (ETH)
Macina et al., EMNLP 2023 — [2305.14536](https://arxiv.org/abs/2305.14536)

교사 행동 분류: **Focus**(전략 탐색, 초점 안내, 정보 상기) / **Probing**(설명 요구, 자기교정 유도,
문제 변형) / **Telling**(전략 공개, 정답 공개) / Generic.
지시 없는 ChatGPT는 **66%에서 정답을 공개**하고 59%에서 잘못된 피드백을 준다.
지표: Success@k vs Telling@k 트레이드오프.

→ `AgentAction` 어휘와 `ACTION_DIRECTIVENESS` 순위가 여기에 기반한다.

### 기타 벤치마크
- **MathTutorBench** (EMNLP 2025) — [2502.18940](https://arxiv.org/abs/2502.18940):
  문제해결력과 교수능력이 **역상관**(튜터링 특화 모델 제외). 대화가 길어질수록 성능 저하.
- **TutorBench** (2025) — [2510.02663](https://arxiv.org/abs/2510.02663):
  1,490개 전문가 문항, 항목별 루브릭. 어떤 프런티어 모델도 56%를 넘지 못함.
- **TutorEval** (2024) — [2402.11111](https://arxiv.org/abs/2402.11111): GPT-4 채점자 Pearson 0.60.
- **CIMA** (BEA 2020) — [링크](https://aclanthology.org/2020.bea-1.5/):
  같은 학생 발화에 대한 튜터의 다음 행동 일치도가 **18.1%**.
  → 참조 응답과의 유사도(BLEU/임베딩)는 교육학적 신호로 부적합하다는 결정적 근거.

### Khan Academy / Khanmigo
[블로그](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/)

교육학 박사가 루브릭 작성 → 인간 평가자 일치도 **85% 확보 후에야** LLM judge 훈련 →
인간 정확도 도달 후 야간 배치 운영. 운영 지표: 인지적 참여(수동/능동/구성적),
다음 문항 정답률, 바람직하지 않은 행동(정답 제공), 수학 오류, 지연.
학습 기록 맥락 제공 시 다음 문항 정답률 +6.1%.

> **함의**: judge는 사람 기준 없이 쓰면 안 된다. → `edu-agent calibrate`

## 2. 다중 턴에서의 붕괴

| 연구 | 발견 |
|---|---|
| SafeTutors [2603.17373](https://arxiv.org/abs/2603.17373) | "교육학적 안전" = 정답 과잉 공개, 오개념 강화, 스캐폴딩 포기. 긴 대화에서 실패율 17.7% → **77.8%**. 모델 규모로 해결되지 않음 |
| Shao et al. 2026 [2607.19371](https://arxiv.org/abs/2607.19371) | **scaffolding collapse** 정의: Collapse Rate, 붕괴 시작 턴, 과잉 거부. 9턴 이후 32% 붕괴 |
| Zhao, Knežević & Käser 2026 [2604.18660](https://arxiv.org/abs/2604.18660) | 설득 전략 6종을 적대적 학생 에이전트로 구현해 정답 추출 시도 |
| Kadir 2026 [2608.00515](https://arxiv.org/abs/2608.00515) | 정답 누출을 "권한 부여 시점 위반"으로 보고 **결정적 정책 게이트**로 강제: 599건 중 181건 → **0건** |
| Kasneci & Kasneci 2026 [2605.14604](https://arxiv.org/abs/2605.14604) | EduFrameTrap: 권위 주장·체면 압박에 튜터가 굴복(아첨). "corrective friction" 벤치마크 제안 |
| Neagu et al. 2026 [2606.15766](https://arxiv.org/abs/2606.15766) | 9,490건 실제 대화. 챗봇 스캐폴딩과 **학생 uptake**를 분리하니 uptake가 낮음 |
| Kobler et al. 2026 [2604.23486](https://arxiv.org/abs/2604.23486) | 12,650개 메시지: 학생은 대부분 정답을 추출하려 함. 턴 수준 지표를 권고 |

## 3. LLM judge의 신뢰성

| 출처 | 발견 |
|---|---|
| Maurya et al. 2025 | Prometheus2는 8개 차원 거의 전부에서 인간과 **음의 상관**. 최고가 인간다움 0.11 |
| BEA 2025 | 지도학습 judge조차 3분류 F1 0.58–0.72 (인간 κ 0.65인데도) |
| Norman et al. 2026 [2606.19544](https://arxiv.org/abs/2606.19544) | judge 21개, 약 54만 판정: 재검사 신뢰도는 높으나 위치 편향 >0.10, 벤치마크 간 순위 최대 14위 변동 — **"reliability without validity"** |
| Kadir 2026 ES-LLMs [2603.23990](https://arxiv.org/abs/2603.23990) | 같은 7차원 루브릭에서 인간 전문가 선호 91.7% vs 6모델 judge 패널 79.2% |
| Abdulsalam & Aroyehun 2025 [2512.20780](https://arxiv.org/abs/2512.20780) | 정확성 압박·revoicing은 품질을 예측하나 **공손함·agentic 언어는 낮은 평가를 예측**. LLM은 후자를 과다 생성 |
| EducationQ [2504.14928](https://arxiv.org/abs/2504.14928) | 평가자 에이전트와 전문가 일치 78%. 교수 품질은 모델 크기에 단조 증가하지 않음 |
| Petukhova & Kochmar 2026 [2603.24375](https://arxiv.org/abs/2603.24375) | 0.5B Bradley-Terry 보상 모델로 인간 쌍대 일치 0.74 — 작은 특화 모델이 범용 judge보다 낫다 |

## 4. 하네스 설계에 반영한 것

**결정적으로 검사 가능한 것** → `evaluator/deterministic.py`
- 정답 누출 (tasks/의 정답·조각 매칭, 학습자 상태 조건과 함께)
- 행동 선언 검증, 사다리 진행, 추론 유도 선행
- 압박 굴복률, 붕괴 시작 턴, PII 처리
- 구조 지표(질문 포함 여부, 길이·청크 수 = 인지부하 대리)

**judge가 필요한 것** → `evaluator/judge.py`
- 오류 식별·위치, 안내 품질, actionability, 일관성, 어조, 적응, 비생산적 보류, 피드백 유형
- 절대 점수보다 쌍대 비교, 순서 교환 재판정(위치 편향), 3단계 라벨

**함정 7가지**
1. 범용 judge는 미세 교육학 차원에서 무효 → 사람 라벨로 먼저 검증
2. 위치·장황함 편향 → 순서 교환, 길이 정규화
3. 단일 턴 착시 → 다중 턴 + 붕괴 시작 턴
4. "절대 금지"는 잘못된 하드 규칙 → 학습자 상태 조건화
5. 타당한 튜터 행동이 여러 개(CIMA 18%) → 참조 유사도 금지
6. 튜터 편측 채점 → 학생 측 지표
7. 아첨 → 압박 하에서 옳은 입장을 유지하는지 별도 검사
