# Goal_AI_Agent — 프로토타입 v0 (김시우)

"엔지니어를 대신해서 분석해주는 AI Agent"라는 프로젝트 본래 목표에 맞춰 만든 최소 동작
버전입니다. 팀이 이미 확정한 결과(Health Index/경보/유효인자/SOP — `26.08.01_Goal5_HealthIndex_Dashboard_김시우/`)를
Claude API가 실제로 조회해서 자연어 질문에 답하는지 검증하는 게 목적입니다.

## 어떻게 동작하는지

AI가 데이터를 지어내지 않고, 실제 저장된 값을 "조회"해서 답합니다.

1. 질문 입력 → Claude API로 전달
2. 시스템 프롬프트로 역할 고정 — "반드시 도구를 호출해서 실제 데이터를 확인한 뒤 답하라"
3. Claude가 질문 내용에 따라 필요한 도구를 스스로 선택해서 호출
   - `get_machine_health(machine_id)` — 장비별 최신 Health Index, 최근 30일 추세, 활성 경보
   - `get_defect_causes(defect_name)` — 팀이 확정한 불량별 원인 변수(유효인자)와 메커니즘
     (Particle→Vibration: daeho, Remain_Coat→CLN_Pressure: 전성재, Chipping/Micro_Crack: JHdaimma)
   - `get_sop_for_factor(factor_name)` — 원인 변수별 점검/조치 SOP 초안 (전부 `DRAFT_UNVERIFIED`)
4. 도구가 반환한 실제 값(JSON)을 근거로 Claude가 한국어 답변 생성
5. 시스템 프롬프트 규칙에 따라 "상관관계지 인과 증명 아님", "SOP는 미검증 초안" 같은 hedge 항상 포함

즉 새로운 분석을 만드는 게 아니라, 팀이 이미 통계적으로 검증한 결과 위에서 "조회 + 자연어 설명"
인터페이스만 씌운 것입니다. 관계DB(윤진혁 작업)가 완성되면 `get_defect_causes`/`get_sop_for_factor`
두 함수가 그 DB를 읽도록만 바꾸면 되고, 에이전트 구조 자체는 안 바뀝니다.

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
- 데이터 출처가 `Goal5_HealthIndex_Dashboard`의 `dashboard_data.json` 하나뿐 — 윤진혁님의
  관계DB가 완성되면 그쪽으로 교체 필요 (Particle/Remain_Coat도 관계DB에 포함되도록 확장 필요)
- Health Index 가중치/임계값은 전부 잠정치 (`Goal5_HealthIndex_Dashboard/README.md` 참고)
- 에러 처리/인증/멀티유저 지원 없음 — 데모 프로토타입 수준
