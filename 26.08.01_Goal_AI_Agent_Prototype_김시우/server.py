"""AI Agent 채팅 웹 인터페이스 — 로컬 서버.

agent.py의 로직(도구/시스템 프롬프트)을 그대로 재사용하고, 터미널 대신
브라우저 채팅창으로 질문/답변할 수 있게 감싸는 역할만 한다.

실행:
  저장소 루트에 .env 파일 한 줄:  ANTHROPIC_API_KEY=본인 키
  (또는 export ANTHROPIC_API_KEY="본인 키" — agent.py가 둘 다 읽는다)
  python3 server.py
그 다음 브라우저에서 http://localhost:5050 접속.

API 키는 이 서버(내 컴퓨터)에서만 쓰이고 브라우저로는 절대 안 나간다 —
브라우저는 /api/ask에 질문 텍스트만 보내고, 답변 텍스트(+그래프 요청 시 시계열 데이터)만 받는다.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import agent  # 같은 폴더의 agent.py — 도구/시스템 프롬프트/ask() 재사용
import views  # 대시보드 뷰 빌더 (선택 → 화면 데이터). API 키 없이도 동작한다.

HERE = Path(__file__).resolve().parent

app = Flask(__name__)


@app.route("/")
def index():
    return send_from_directory(HERE, "dashboard.html")


# (26.08.11) 화면을 대시보드 하나로 합쳤다. 예전 chat.html은 "질문 → 답변 + 패널"이라
# 화면 상태가 전적으로 Claude의 도구 호출에 달려 있었고, 대시보드가 그걸 대체하면서
# 챗은 그 안의 패널(선택 UI의 단축키)로 들어왔다 — views.py docstring 참고.
# 시연 촬영용으로 남겨뒀던 것인데 촬영 전에 대시보드로 확정돼서 지웠다.
# /dashboard는 문서·링크에 이미 퍼진 경로라 같은 화면으로 계속 열어둔다.
@app.route("/dashboard")
def dashboard():
    return send_from_directory(HERE, "dashboard.html")


@app.route("/api/bootstrap")
def api_bootstrap():
    """화면이 처음 뜰 때 한 번 — 장비 스트립과 변수 트리를 채운다. LLM을 안 거치므로
    API 키가 없어도, 질문을 하지 않아도 상태가 보인다."""
    try:
        return jsonify(views.bootstrap())
    except Exception as exc:  # noqa: BLE001 — 데모용 서버, 원인 그대로 노출
        return jsonify({"error": str(exc)}), 500


@app.route("/api/view", methods=["POST"])
def api_view():
    """뷰 상태 객체 하나 -> 화면 데이터. 사이드바 클릭이 여기로 온다."""
    state = request.get_json(silent=True) or {}
    try:
        result = views.build(state)
        return (jsonify(result), 404) if "error" in result else jsonify(result)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.route("/api/ask", methods=["POST"])
def api_ask():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "질문이 비어있습니다."}), 400
    if not agent.has_api_key():
        # 키가 없으면 Claude를 부르기 전에 여기서 끊는다. SDK가 던지는 영문
        # TypeError가 그대로 말풍선에 뜨던 걸, 무엇을 해야 하는지로 바꾼 것.
        return jsonify({"error": agent.MISSING_KEY_MESSAGE}), 503
    try:
        result = agent.ask(question)  # {"answer": str, "panels": list | None}
        # 자연어를 "선택 UI의 단축키"로 쓴다 — 답변 문장을 파싱하지 않고, agent가
        # 결정론적으로 만든 패널에서 뷰 상태를 뽑아 화면을 그 상태로 옮긴다.
        result["view_state"] = views.state_from_panels(result.get("panels"))
        # panels도 같이 내려간다 — 대시보드는 view_state만 읽지만, 응답 스키마를
        # 좁히면 agent.ask()를 쓰는 CLI 쪽과 어긋나므로 그대로 둔다.
        return jsonify(result)
    except Exception as exc:  # noqa: BLE001 — 데모용 서버, 원인 그대로 노출해 디버깅 쉽게
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    # 포트는 PORT 환경변수로 바꿀 수 있다(기본 5050) — 이미 5050에서 돌고 있는 서버를
    # 안 죽이고 두 번째 인스턴스를 띄울 때 필요하다.
    port = int(os.environ.get("PORT", "5050"))
    print("공정 품질 AI Agent")
    # 키 유무를 띄울 때 한 번 알려준다 — 없으면 챗만 막히고 나머지는 그대로 돈다.
    print("  API 키       " + ("연결됨(챗봇 사용 가능)" if agent.has_api_key()
                               else "없음 — 그래프·히트맵만 동작(.env에 ANTHROPIC_API_KEY)"))
    print(f"  챗봇(기존)   http://localhost:{port}/")
    print(f"  대시보드(신) http://localhost:{port}/dashboard")
    app.run(host="127.0.0.1", port=port, debug=False)
