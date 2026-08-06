# n8n — Health Index 파이프라인 자동화

Step0 전처리 → trend_analysis.py → build_health_index.py를 매번 손으로 실행하던 걸
n8n으로 자동 트리거 + 결과 요약까지 받을 수 있게 워크플로우로 감쌌다. Langflow는
검토했지만 안 씀 — agent.py에 이미 도구 호출/spec_source 신뢰도 구분/차트 렌더링까지
검증된 커스텀 에이전트가 있어서, 굳이 다시 만들 이유가 없었음(자세한 이유는
대화 기록 참고).

## 워크플로우 구조

`health_index_pipeline_workflow.json` (n8n에서 export한 파일, import 가능):

```
Webhook(POST) → Execute Command(파이프라인 3단계 실행 + JSON cat)
             → Code(장비별 Health Index 요약, 임계값 30 미만이면 warnings에 담음)
             → Respond to Webhook(요약 JSON 반환)
```

## 실행 방법

n8n은 Node.js 앱이라 Docker나 Node가 있어야 한다. 이 환경엔 Node 최신(26)이 이미 있었는데
n8n의 네이티브 의존성(isolated-vm)이 Node 26과 안 맞아서 컴파일이 깨졌다 — **Node 22
LTS**로 따로 설치해서 n8n을 그 위에 올렸다(`brew install node@22`, 전역 `node`는
안 건드림, n8n 실행 시에만 PATH 앞에 붙여서 씀).

```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
export NODES_EXCLUDE='[]'        # 아래 "왜 필요한가" 참고 — 이거 없으면 Execute Command 노드가 비활성화됨
export N8N_SECURE_COOKIE=false   # Safari로 http://localhost 접속 시 "secure cookie" 에러 방지(로컬 전용이라 안전)
n8n start
```

브라우저에서 http://localhost:5678 접속 — **꼭 `localhost`로 접속할 것, `127.0.0.1`
아님** (Safari가 `127.0.0.1` + secure cookie 조합을 막을 수 있음). 계정: 이메일
`tldn6850@gmail.com` / 비밀번호는 **팀 채널(카톡/노션) 참고 — git에는 올리지 않음**.

### 워크플로우 최초 등록

```bash
n8n import:workflow --input=n8n/health_index_pipeline_workflow.json
n8n publish:workflow --id=sugentHealthIdxPipe1
```

`publish:workflow`는 n8n을 재시작해야 반영된다("Note: Changes will not take effect
if n8n is running" 안내가 뜸) — 재시작하면 로그에 `Activated workflow "SUGENT Health
Index 파이프라인"`이 뜨는지 확인.

### 테스트

```bash
curl -X POST http://localhost:5678/webhook/run-health-pipeline
```

파이프라인 3단계(약 15~20초)를 실제로 실행하고, 이런 형태로 응답한다:

```json
{
  "generated_at": "...",
  "alert_threshold": 30,
  "summary": "⚠️ 위험 장비 2대: DP02(5.2), DP03(15.9)",
  "has_warning": true,
  "warnings": [{"machine_id": "DP02", "health_index": 5.2, "worst_defect": "Chipping"}, ...],
  "machines": [...]
}
```

### 임계값(ALERT_THRESHOLD=30)이 뜻하는 것

Health Index는 0~100이고 낮을수록 급하다. **10점 미만은 "이미 스펙아웃"** 전용 구간이라
(0에 가까울수록 스펙을 몇 배로 벗어난 것), 기본 임계값 30은 "스펙 여유를 78% 넘게 쓴
상태"에 해당한다 — 즉 스펙아웃 직전부터 메일이 나간다. 더 일찍 받고 싶으면 이 값을
올리면 되고(50이면 여유 절반 소진 시점), 스펙아웃만 받고 싶으면 10으로 내리면 된다.
Code 노드 안의 `ALERT_THRESHOLD` 상수 하나만 고치면 되고, 요약/표/상세가 모두 그 값을
따라간다.

## 위험 장비 있으면 메일로 리포트 발송

`위험 장비 있음?`(IF) 노드가 `has_warning`을 보고 분기 — 위험 장비가 있으면
`위험 메일 발송`(SMTP) 노드가 HTML 리포트를 보낸다. 리포트에는 장비 전체 개요 표
(Health Index 색상 표시) + 위험 장비별 defect/원인변수 상세(현재값/기준값/정상범위/
스펙출처/추세)까지 담긴다 — `causes` 딕셔너리를 그대로 표로 풀어낸 것.

메일 발송은 Gmail SMTP(`smtp.gmail.com:465`, SSL)를 쓴다. n8n Credentials에
"SMTP account"라는 이름으로 이미 등록돼 있고(Host/Port/User/앱 비밀번호), 워크플로우
JSON의 이메일 노드가 그 credential id를 직접 참조한다 — **이 credential은 로컬 n8n
DB에만 있고 git에는 안 올라간다**(워크플로우 JSON은 credential id만 참조, 실제
비밀번호는 안 들어있음). 다른 컴퓨터에서 이 워크플로우를 다시 쓰려면 Credentials에서
동일한 이름으로 새로 만들고 이메일 노드에서 다시 연결해야 함.

**주의**: 워크플로우를 n8n 화면에서 수정(노드 추가/credential 연결 등)하면 "Publish"를
눌러야 반영되고, `n8n start`로 띄운 서버는 재시작해야 그 발행분을 읽는다 — 편집 후
바로 웹훅을 호출하면 예전 버전으로 실행된다.

## 왜 NODES_EXCLUDE='[]'가 필요한가

n8n 2.x부터 `Execute Command`/`Local File Trigger` 노드가 **기본적으로 비활성화**돼
있다(임의 쉘 실행이라 보안상 기본 차단, `disabled-nodes.rule.js` 참고). 이 프로젝트의
파이프라인 자동 실행은 정확히 그 기능이 필요해서, 로컬 전용으로만 쓴다는 전제 하에
`NODES_EXCLUDE=[]`로 기본 차단 목록을 비워서 켰다. **외부에 노출하는 서버라면 이
설정을 쓰면 안 됨** — 완전히 로컬(localhost)에서만 쓰는 용도로 만들었다.

## 팀원과 같이 수정하기

지금은 각자 로컬에서 n8n을 띄워 쓰는 구조라 실시간 동시편집은 안 되고, git으로
비동기 협업한다.

1. `git pull`로 최신 `health_index_pipeline_workflow.json`을 받는다.
2. 로컬 n8n에 import: `n8n import:workflow --input=n8n/health_index_pipeline_workflow.json`
   (이미 등록돼 있으면 n8n 화면에서 기존 워크플로우를 지우고 다시 import하거나,
   화면에서 직접 노드를 고쳐도 됨)
3. n8n 화면(캔버스)에서 노드 추가/수정 후 저장.
4. 워크플로우를 다시 JSON으로 export해서 git 파일을 덮어쓴다:
   `n8n export:workflow --id=sugentHealthIdxPipe1 --output=n8n/health_index_pipeline_workflow.json`
5. `git diff`로 실제 바뀐 내용만 커밋됐는지 확인 후 커밋 → PR.
   (credential id 등 민감정보는 워크플로우 JSON에 값으로는 안 들어가니 안전 —
   단, 위 비밀번호 사고처럼 README나 커밋 메시지에 실제 비밀번호/키를 직접 적지 말 것)

같은 워크플로우를 동시에 여러 명이 화면에서 고치면 나중에 저장한 사람 걸로
덮어써지니, 수정 전엔 팀 채널에 "지금 n8n 워크플로우 건드릴게요" 정도만 얘기하고
하면 충돌 없이 갈 수 있다.

## 다음 단계로 붙이면 좋은 것 (아직 안 함)

- **알림 연결**: 지금은 Respond to Webhook이 요약을 그대로 돌려줄 뿐, 실제 Slack/이메일
  발송은 안 함 — Slack/Gmail 노드를 `Summarize Health Index` 뒤에 추가하고
  `{{ $json.has_warning }}`으로 IF 분기하면 됨(그 서비스 자격증명은 각자 넣어야 함).
- **(26.08.06 추가) 메일 발송 트리거는 "매일 재확인"이 아니라 "새 이상 시작"/"악화" 기준으로
  나가야 함** — early_warning은 상태형이라 하나의 이상이 며칠~몇십일 지속되면 파이프라인을
  돌릴 때마다(=n8n이 재실행될 때마다) 같은 이상을 계속 "위험"으로 반환한다. 그대로 스케줄
  트리거를 걸면 엔지니어가 같은 문제로 매일 메일을 받게 됨(알림 피로). `health_index_data.json`의
  `causes`/`anomalies` 항목에 이제 `alert_since`(이 이상이 시작된 날짜)와
  `alert_active_days`(며칠째 지속 중인지)가 들어있으니, n8n Code 노드에서
  - 직전 실행에서 보낸 `alert_since` 값을 저장해뒀다가(예: n8n 워크플로우 static data,
    또는 별도 상태 파일) 이번 실행의 `alert_since`와 같으면 "이미 보낸 사건"으로 보고 스킵
  - 다르면(새 사건 시작) 또는 `alert_active_days`가 특정 기준(예: 7일 단위)을 넘어서면
    "장기 미해결" 재알림으로 다시 발송
  하는 분기를 추가하는 걸 추천. 리포트 메일 본문에도 "이 이상은 {alert_since}부터
  {alert_active_days}일째 지속 중"을 넣으면 엔지니어가 처음 보는 문제인지 계속 보던
  문제인지 바로 구분할 수 있다.
- **스케줄 트리거**: 지금 데이터는 정적(2026-01-01~03-30 고정)이라 "매일 재실행"이
  의미가 없어서 스케줄은 안 걸었음 — 실제 라이브 데이터가 들어오면 Webhook 대신/같이
  Schedule Trigger를 추가하면 됨.
