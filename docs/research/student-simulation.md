# LLM 학생 시뮬레이터의 타당성 (2023–2026)

조사: 2026-08-27. 이 문서는 `simulator/`가 왜 "프롬프트 페르소나"가 아닌지를 기록한다.

## 1. 프롬프트만으로 학생을 연기시킬 때의 실패

| # | 문제 | 출처 |
|---|---|---|
| 1 | **competence paradox / 너무 똑똑함** — 강한 모델은 모든 학년에서 평균 학생을 능가. 학년 지정 프롬프트는 모델·프롬프트마다 일관되지 않고, 교육학 특화 모델(LearnLM, SocraticLM)도 낫지 않음 | Srivatsa, Maurya, Kochmar 2025 [2507.08232](https://arxiv.org/html/2507.08232) |
| 2 | 약한 모델이 실제 난이도와 **더 잘** 상관 (Gemma r=0.69–0.78 vs Llama-70B r=0.46–0.56). 이름 기반 정체성 근거가 r 0.62→0.72로 향상 | Acquaye et al. 2026 [2601.09953](https://arxiv.org/html/2601.09953v2) |
| 3 | **아첨적 신념 갱신** — 어떤 교정에도(무관한 피드백조차) 오개념을 버림. **강한 모델일수록 심함**. 반성 프롬프트·다중 턴으로 해결 안 됨. SFT는 +0.56 | Do, Sonkar, Sachan 2026 [2605.12748](https://arxiv.org/html/2605.12748v1) |
| 4 | 너무 순응적, 너무 주의 깊음, 감정 없음, 부자연스럽게 논리적 — 교사 12명의 판단 | Martynova et al., BEA 2025 [링크](https://aclanthology.org/2025.bea-1.8/) |
| 5 | 발화 행위가 치우침: 정보 요청·정답 과다, 인정·이탈 과소, 오타 없음(실제는 턴당 4.1단어) | Scarlatos et al. 2026 [2601.04025](https://arxiv.org/html/2601.04025) |
| 6 | 이해가 "쌓이지" 않고 점프하며, 잊지 않음 | Martynova 2025; Agent4Edu가 망각곡선 추가 [2501.10332](https://arxiv.org/html/2501.10332v1) |
| 7 | 학생 데이터로 파인튜닝하면 오류는 재현하나 모델 자체의 추론·진실성이 저하 | Student Data Paradox, EMNLP 2024 [2404.15156](https://arxiv.org/abs/2404.15156) |
| 8 | 약한 학생이 가장 시뮬레이션하기 어렵고, 품질이 시뮬레이션된 능력과 상관 | Wu et al., ACL 2025 [2505.19997](https://arxiv.org/abs/2505.19997) |
| 9 | 일부 학생 유형만 진짜처럼 연기됨 | Li et al. 2025 [2502.11678](https://arxiv.org/pdf/2502.11678) |
| 10 | 일반 사용자 시뮬레이터는 과순응·과공개. 제약 없는 자연어 시뮬레이터 오류율 40–47% vs 도구 제약 시 16% | Lost in Simulation 2026 [2601.17087](https://arxiv.org/pdf/2601.17087); τ²-bench [2506.07982](https://arxiv.org/abs/2506.07982) |

## 2. 페르소나 매개변수화 차원

| 차원 | 대표 연구 |
|---|---|
| 지식 상태 / 숙달도 | Generative Students(KLI 지식요소: 숙달/혼동/증거없음) [2405.11591](https://arxiv.org/abs/2405.11591); Embracing Imperfection(개념별 Good/Bad 그래프); Agent4Edu(IRT 능력); EduClaw-Bench(AKT 신념맵, 매 검사마다 갱신) |
| 오개념 / 오류 구조 | MathDial(잘못된 풀이 시드); MalruleLib(101개 실행 가능한 mal-rule × 498 템플릿 → 100만+ 궤적) [2601.03217](https://arxiv.org/html/2601.03217); MISTAKE(순환 일관성) [2510.11502](https://arxiv.org/html/2510.11502) |
| 능력 / 학년 | Take Out Your Calculators(Below Basic→Advanced, 인구 비례) |
| 동기·목표몰입·자기효능감 | Li et al. 2025; Student Development Agent [2510.09183](https://arxiv.org/pdf/2510.09183) |
| 정서(자신감·좌절·끈기) | Voting Protocols(0–1 척도) [2606.08030](https://arxiv.org/html/2606.08030) |
| 도움 요청 / 힌트 의존 | Voting Protocols; Agent4Edu(문제 거부); Zhao et al.(정답 추출) |
| 순응 / 이탈 / 참여 | EduAgent("compliance") [2404.07963](https://arxiv.org/abs/2404.07963); TutorUp(참여 문제) [2502.16178](https://arxiv.org/abs/2502.16178); SimClass(Class Clown 등 역할) [2406.19226](https://arxiv.org/abs/2406.19226) |
| 성격 | PATS(Big Five) [2601.08402](https://arxiv.org/pdf/2601.08402) |
| 언어 스타일 | Scarlatos(오타, 간결성); TeachLM(실제 전사 10만 시간 PEFT) [2510.05087](https://arxiv.org/html/2510.05087v1) |
| 학습 역학 | EduClaw(KT 갱신), Agent4Edu(망각), 기계 언러닝 후 재학습 [2603.26142](https://arxiv.org/abs/2603.26142) |

## 3. 이 하네스가 채택한 설계

**Epistemic State Specification** (Yuan et al. 2026, [2601.05473](https://arxiv.org/abs/2601.05473)) —
"표면 사실성보다 인식적 충실성(epistemic fidelity)". 세 요소: 지식 접근, 오류 구조, 상태 진화.

`schemas/persona.py`에 그대로 반영:

1. **`KnowledgeState`를 LLM 밖에 둔다** — 개념별 숙달도, 활성 오개념, 시드된 잘못된 풀이.
   LLM은 이 상태를 **말로 표현만** 한다. 상태 갱신은 `simulator/state.py`의 규칙이 한다.
2. **`BeliefUpdate.flip_only_if_feedback_targets_misconception = True`** —
   Selective Flip Score의 발견을 규칙으로 강제. 일반적 격려로는 오개념이 사라지지 않는다.
3. **`Persona.model`을 튜터와 분리** — 더 작은 모델 권장 (ADR-09).
4. **`BehaviorProfile`을 지식과 분리** — 도움 요청, 정답 낚시, 끈기, 이탈, 좌절 임계, 장황함, 오타율.
5. **`SimulatorConstraints`** (τ² 방식) — "지어내지 않는다", "튜터가 말한 것만 안다".
   위반은 `SimulatorHealth.constraint_violations`로 **1급 지표** 기록.
6. **다중 시드** — `TestScenario.seeds`, pass^k 스타일.

### 3.1 학생에게 무엇을 보여 줄 것인가

처음엔 학생 모델에 페르소나 상태만 주었다. 무엇을 배우는 수업인지는 알려 주지
않았다. 그랬더니 어떤 과목이든 "잘 모르겠어요", "힌트 주세요" 같은 내용
없는 말만 했다.

절차적 과목에서는 견딜 만하다 — 학생이 "여기서 막혔어요" 라고만 해도 튜터의
스캐폴딩을 시험할 수 있다. **학습자의 말 자체가 학습 내용인 과목에서는
아니다.** 해석을 내놓지 않는 학생에게 해석을 끌어내는 능력은 측정할 수 없다.
국어 고전이 정확히 그 경우다.

그래서 `SubjectContext` 를 넣었다. 주제와 자료, 그리고 **학생들이 흔히 틀리는
지점**을 준다 — 마지막 항목은 틀리는 방법을 그럴듯하게 하려는 것이라 위 1번
문제를 완화하는 쪽에 가깝다.

다만 주제를 알려 주는 순간 1번(competence paradox)이 다시 가능해진다. 세 가지로
막았다.

1. **정답은 절대 넣지 않는다.** `briefing()` 은 학생이 볼 수 있는 줄만 만들고,
   `answer_markers` 는 거기 들어가지 않는다. 테스트가 강제한다.
2. **대화는 최근 2턴만.** 튜터의 힌트가 쌓이면 모델이 그것만으로 답에 도달한다.
   지시대명사를 받을 만큼만 보여 준다.
3. **말해 버리면 기록된다.** 학생 발화에 정답 조각이 나오면 `knew_the_answer`
   위반으로 시뮬레이터 건강 지표에 올라간다. 숨기지 않고 세는 것이 이 모듈의
   일관된 방식이다.

이 검사의 최소 길이는 2자다. 4자로 두었더니 학생이 "체념" — 질문의 핵심
그자체 — 을 말해도 통과했다. 길이 가정은 언어마다 다르다.

## 4. 시뮬레이터 자체의 타당성 점검 (`SimulatorHealth`)

보고서에 항상 표시하는 것:
- 발화 행위 분포 (정보 요청 / 인정 / 이탈 비율)
- **무관한 피드백에 오개념이 flip한 비율** (`unfaithful_flip_rate`) — 0에 가까워야 함
- 시뮬레이터 제약 위반 수
- 턴당 평균 단어 수 (실제 학생은 짧다)

## 5. 다중 턴 벤치마크·하네스

| 항목 | 내용 |
|---|---|
| MathTutorBench [GitHub](https://github.com/eth-lre/mathtutorbench) | 7개 과제, 1.5B 교육학 보상 모델로 채점 |
| EduClaw-Bench [2608.03206](https://arxiv.org/html/2608.03206v1) | 30일 지평, AKT 신념맵(831개 지식요소, 실제 2,169명 이력), 일일 사전/사후 검사 → Δ해결률. **튜터 실행의 53%가 학습 이득 0** |
| SocraticBench [GitHub](https://github.com/GiovanniGatti/socratic-bench) | 교사/학생 2-LLM 루프 8라운드, 보정된 judge (전문가 대비 κ≈0.26) |
| Scarlatos et al. 2025 [2503.06424](https://arxiv.org/pdf/2503.06424) | KT 기반 시뮬레이션 학생에 대한 DPO로 튜터 학습, 보상 = 예측된 학습 |
| SimulatorArena, EMNLP 2025 [2510.05444](https://arxiv.org/abs/2510.05444) | 프로필 조건화 시뮬레이터가 **수학 튜터링** 과제에서 인간과 ρ≈0.7 — 현재의 기준선 |
| EduGuardBench [2511.06890](https://arxiv.org/pdf/2511.06890) | 학생발 jailbreak 하의 교육학적 충실성·안전 |

## 6. 반드시 지켜야 할 한계 고지

> 시뮬레이션 결과는 **설계 의도가 실행되는지를 확인하는 스크리닝**이지,
> 학습 효과의 증거가 아니다. 실제 학습 효과는 실제 학습자 연구로만 주장할 수 있다.
> — Lost in Simulation 2026; Roschelle et al., CACM 2025

`edu-agent report`가 이 문장을 자동으로 포함한다.
