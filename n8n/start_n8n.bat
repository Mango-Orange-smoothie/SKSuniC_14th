@echo off
REM n8n 서버 자동 시작 (Windows 작업 스케줄러가 로그인 시 호출).
REM
REM 왜 필요한가 — 일일 리포트는 워크플로우 안의 Schedule Trigger가 발화시키는데,
REM 그건 n8n 프로세스가 떠 있어야만 돈다. 터미널에서 손으로 띄우는 구조로는
REM 재부팅 한 번에 리포트가 조용히 끊긴다.
REM
REM 주의: Schedule Trigger는 **서버가 뜰 때 등록**된다. 워크플로우에서 스케줄을
REM 추가·수정했으면 반드시 n8n을 재시작해야 반영된다(발행만으로는 안 울린다).
REM
REM NODES_EXCLUDE=[] 는 필수다. n8n 2.x부터 Execute Command 노드가 기본 비활성화라
REM (임의 쉘 실행이라 보안상 차단) 이걸 비워주지 않으면 Run Pipeline 노드가
REM "Unrecognized node type"으로 죽는다. 로컬 전용이라는 전제로 켠다.
REM
REM 등록:
REM   schtasks /create /tn "n8n Server" /tr "<이 파일의 절대경로>" /sc onlogon /f
REM 해제:
REM   schtasks /delete /tn "n8n Server" /f
REM 로그:
REM   type "%TEMP%\n8n_server.log"

set "LOG=%TEMP%\n8n_server.log"

REM 이미 떠 있으면 중복 실행하지 않는다(포트 5678 충돌 방지).
curl -s -o NUL -m 3 http://localhost:5678
if %ERRORLEVEL% EQU 0 (
  echo [%DATE% %TIME%] n8n already running - skip >> "%LOG%"
  exit /b 0
)

echo. >> "%LOG%"
echo ===== [%DATE% %TIME%] n8n 시작 ===== >> "%LOG%"

set "NODES_EXCLUDE=[]"
set "N8N_SECURE_COOKIE=false"

call "%APPDATA%\npm\n8n.cmd" start >> "%LOG%" 2>&1

echo ===== [%DATE% %TIME%] n8n 종료 (exit=%ERRORLEVEL%) ===== >> "%LOG%"
