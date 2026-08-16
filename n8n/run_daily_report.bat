@echo off
REM SUGENT Health Index 데일리 리포트 수동 트리거.
REM
REM ⚠️ 정기 실행에는 쓰지 않는다. 일일 자동 실행은 n8n 워크플로우 안의
REM    Schedule Trigger 노드가 맡는다(2026-08-16 검증 완료, 실행 20번).
REM    이 파일을 작업 스케줄러에 등록하면 스케줄이 이중으로 걸려 하루 두 번 돌고,
REM    같은 산출물 파일을 동시에 덮어쓸 위험이 있다. 실제로 그 상태였던 적이 있어
REM    "SUGENT Health Report" 작업을 해제했다.
REM
REM 지금 용도: 스케줄을 기다리지 않고 즉시 한 번 돌려보고 싶을 때(로그가 남아서
REM 결과 확인이 편하다). 웹훅을 부르는 것뿐이라 워크플로우는 손대지 않는다.
REM
REM 파이프라인이 9~14분 걸려서 curl이 그동안 대기한다. 응답과 시각을 로그로 남겨
REM "어젯밤에 돌았는지"를 나중에 확인할 수 있게 한다.
REM
REM 실행: 이 파일을 더블클릭하거나 터미널에서 직접 호출
REM 로그: type "%TEMP%\sugent_daily_report.log"
REM
REM 주의: PC가 켜져 있고 n8n(localhost:5678)이 떠 있어야만 동작한다. 절전 모드면 안 돈다.

set "LOG=%TEMP%\sugent_daily_report.log"

echo. >> "%LOG%"
echo ===== %DATE% %TIME% 실행 시작 ===== >> "%LOG%"

curl -s -S -X POST http://localhost:5678/webhook/run-health-pipeline --max-time 1800 >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%

echo. >> "%LOG%"
echo ===== %DATE% %TIME% 종료 (curl exit=%RC%) ===== >> "%LOG%"

exit /b %RC%
