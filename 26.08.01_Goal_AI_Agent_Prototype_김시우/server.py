"""AI Agent 채팅 웹 인터페이스 — 로컬 서버.

agent.py의 로직(도구/시스템 프롬프트)을 그대로 재사용하고, 터미널 대신
브라우저 채팅창으로 질문/답변할 수 있게 감싸는 역할만 한다.

실행:
  export ANTHROPIC_API_KEY="본인 키"   (아직 안 했다면)
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
    return send_from_directory(HERE, "chat.html")


# 기존 chat.html은 촬영 대기 중이라 그대로 두고, 새 대시보드는 별도 경로로 붙인다.
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
    try:
        result = agent.ask(question)  # {"answer": str, "panels": list | None}
        # 자연어를 "선택 UI의 단축키"로 쓴다 — 답변 문장을 파싱하지 않고, agent가
        # 결정론적으로 만든 패널에서 뷰 상태를 뽑아 화면을 그 상태로 옮긴다.
        # chat.html은 이 키를 안 읽으므로 기존 화면 동작은 그대로다.
        result["view_state"] = views.state_from_panels(result.get("panels"))
        return jsonify(result)
    except Exception as exc:  # noqa: BLE001 — 데모용 서버, 원인 그대로 노출해 디버깅 쉽게
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    # 포트는 PORT 환경변수로 바꿀 수 있다(기본 5050) — 이미 5050에서 돌고 있는 서버를
    # 안 죽이고 두 번째 인스턴스를 띄울 때 필요하다.
    port = int(os.environ.get("PORT", "5050"))
    print("공정 품질 AI Agent")
    print(f"  챗봇(기존)   http://localhost:{port}/")
    print(f"  대시보드(신) http://localhost:{port}/dashboard")
    app.run(host="127.0.0.1", port=port, debug=False)
