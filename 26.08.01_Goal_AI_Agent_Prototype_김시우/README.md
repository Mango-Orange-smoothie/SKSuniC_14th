# Goal_AI_Agent — 프로토타입 v2 (김시우)

"엔지니어를 대신해서 분석해주는 AI Agent"라는 프로젝트 본래 목표에 맞춰 만든 버전입니다.
팀이 이미 확정한 결과(defect별 원인변수 레벨/추세/실제발생여부/SOP —
`26.08.01_Goal5_HealthIndex_Dashboard_김시우/`)를 Claude API가 실제로 조회해서 자연어
질문에 답하는지 검증하는 게 목적입니다. **v1의 "Health Index 단일 점수 + 정적 대시보드"
구조는 폐기했습니다** — 근거 없는 가중치 문제도 있었지만, 무엇보다 "과거를 요약한 리포트"에
가까워서 이 프로젝트가 원래 만들려는 "AI Agent"와 목적이 안 맞았습니다.

## 어떻게 동작하는지

AI가 데이터를 지어내지 않고, 실제 저장된 값을 "조회"해서 답합니다.

1. 질문 입력 → Claude API로 전달
2. 시스템 프롬프트로 역할 고정 — "반드시 도구를 호출해서 실제 데이터를 확인한 뒤 답하라"
3. Claude가 질문 내용에 따라 필요한 도구를 스스로 선택해서 호출
   - `get_machine_health(machine_id)` — 장비별 defect마다 원인변수의 레벨(지금 얼마나
     벗어났나)/추세(최근 14일 방향·속도), 실제 불량 발생 여부(최근 7일), 확정 원인이
     아닌 변수의 미확인 이상(안전망)까지 전부 반환
   - `get_defect_causes(defect_name)` — 팀이 확정한 불량별 원인 변수(유효인자)와 메커니즘
     (Particle→Vibration: daeho, Remain_Coat→CLN_Pressure: 전성재,
     Chipping→8개 변수/Micro_Crack→2개: JHdaimma/Jun)
   - `get_sop_for_factor(factor_name)` — 원인 변수별 점검/조치 SOP 초안 (전부 `DRAFT_UNVERIFIED`)
4. 도구가 반환한 실제 값(JSON)을 근거로 Claude가 한국어 답변 생성 — **레벨/추세를 종합해서
   "얼마나 급한지" 판단하는 것 자체가 에이전트(LLM)의 역할**입니다. 가중치로 미리 하나의
   점수를 만들어서 주지 않습니다.
5. 시스템 프롬프트 규칙에 따라 "상관관계지 인과 증명 아님", "SOP는 미검증 초안", "실제
   발생과 조짐 단계는 다른 어조로" 같은 hedge/구분을 항상 포함

즉 새로운 분석을 만드는 게 아니라, 팀이 이미 통계적으로 검증한 결과 위에서 "조회 + 종합
판단 + 자연어 설명" 인터페이스를 씌운 것입니다. 관계DB(윤진혁 작업)가 완성되면
`get_defect_causes`/`get_sop_for_factor` 두 함수가 그 DB를 읽도록만 바꾸면 되고, 에이전트
구조 자체는 안 바뀝니다.

## 실행 방법 (팀원 각자 본인 컴퓨터에서)

### 1. 필요한 패키지 설치
```bash
pip install anthropic flask
```

### 2. 본인 Anthropic API 키 발급
[console.anthropic.com](https://console.anthropic.com)에서 가입 → 결제 정보 등록(최소 크레딧 구매,
$5~10 정도면 데모용으로 충분) → API Keys 메뉴에서 키 생성.

**주의: 키는 절대 코드에 직접 쓰거나 캡처/공유하지 마세요.** 터미널 환경변수로만 설정합니다.

### 3. 터미널에서 키 설정 + 서버 실행
```bash
export ANTHROPIC_API_KEY="본인 키 값"
```
```bash
cd 26.08.01_Goal_AI_Agent_Prototype_김시우
python3 server.py
```
터미널에 `http://localhost:5050 에서 열어보세요`가 뜨면 브라우저에서 그 주소를 엽니다.

CLI로만 테스트하고 싶으면:
```bash
python3 agent.py "DP03 상태 어때?"
```

## 알려진 한계 (다음 라운드에서 보완할 것)

- 지금은 각자 본인 컴퓨터에서만 실행 가능 (localhost는 외부 공유 안 됨) — 팀 전체가 공용
  링크 하나로 접속하려면 별도 배포(서버 호스팅)가 필요, 아직 미착수
- 데이터 출처가 `Goal5_HealthIndex_Dashboard`의 `health_index_data.json` 하나뿐 — 윤진혁님의
  관계DB가 완성되면 그쪽으로 교체 필요 (Particle/Remain_Coat도 관계DB에 포함되도록 확장 필요)
- 레벨/추세 계산의 안전망 임계값(|z|≥2.0)과 추세 윈도우(14일)는 전부 잠정치
  (`Goal5_HealthIndex_Dashboard/README.md` 참고)
- 에러 처리/인증/멀티유저 지원 없음 — 데모 프로토타입 수준
