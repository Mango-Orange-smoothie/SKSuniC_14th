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
export NODES_EXCLUDE='[]'   # 아래 "왜 필요한가" 참고 — 이거 없으면 Execute Command 노드가 비활성화됨
n8n start
```

브라우저에서 http://localhost:5678 접속. (이미 owner 계정 하나 만들어뒀음 —
이메일 tldn6850@gmail.com. 비밀번호는 설정 중 화면 좌표가 꼬여서 정확히 뭐가
저장됐는지 확신이 없다. 이미 로그인된 브라우저 세션에서 Settings → Personal로
들어가서 바로 원하는 비밀번호로 바꿔두는 게 안전함.)

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

## 왜 NODES_EXCLUDE='[]'가 필요한가

n8n 2.x부터 `Execute Command`/`Local File Trigger` 노드가 **기본적으로 비활성화**돼
있다(임의 쉘 실행이라 보안상 기본 차단, `disabled-nodes.rule.js` 참고). 이 프로젝트의
파이프라인 자동 실행은 정확히 그 기능이 필요해서, 로컬 전용으로만 쓴다는 전제 하에
`NODES_EXCLUDE=[]`로 기본 차단 목록을 비워서 켰다. **외부에 노출하는 서버라면 이
설정을 쓰면 안 됨** — 완전히 로컬(localhost)에서만 쓰는 용도로 만들었다.

## 다음 단계로 붙이면 좋은 것 (아직 안 함)

- **알림 연결**: 지금은 Respond to Webhook이 요약을 그대로 돌려줄 뿐, 실제 Slack/이메일
  발송은 안 함 — Slack/Gmail 노드를 `Summarize Health Index` 뒤에 추가하고
  `{{ $json.has_warning }}`으로 IF 분기하면 됨(그 서비스 자격증명은 각자 넣어야 함).
- **스케줄 트리거**: 지금 데이터는 정적(2026-01-01~03-30 고정)이라 "매일 재실행"이
  의미가 없어서 스케줄은 안 걸었음 — 실제 라이브 데이터가 들어오면 Webhook 대신/같이
  Schedule Trigger를 추가하면 됨.
