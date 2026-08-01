"""AI Agent 채팅 웹 인터페이스 — 로컬 서버.

agent.py의 로직(도구/시스템 프롬프트)을 그대로 재사용하고, 터미널 대신
브라우저 채팅창으로 질문/답변할 수 있게 감싸는 역할만 한다.

실행:
  export ANTHROPIC_API_KEY="본인 키"   (아직 안 했다면)
  python3 server.py
그 다음 브라우저에서 http://localhost:5050 접속.

API 키는 이 서버(내 컴퓨터)에서만 쓰이고 브라우저로는 절대 안 나간다 —
브라우저는 /api/ask에 질문 텍스트만 보내고, 답변 텍스트만 받는다.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import agent  # 같은 폴더의 agent.py — 도구/시스템 프롬프트/ask() 재사용

HERE = Path(__file__).resolve().parent

app = Flask(__name__)


@app.route("/")
def index():
    return send_from_directory(HERE, "chat.html")


@app.route("/api/ask", methods=["POST"])
def api_ask():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "질문이 비어있습니다."}), 400
    try:
        answer = agent.ask(question)
        return jsonify({"answer": answer})
    except Exception as exc:  # noqa: BLE001 — 데모용 서버, 원인 그대로 노출해 디버깅 쉽게
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    print("공정 품질 AI Agent — http://localhost:5050 에서 열어보세요")
    app.run(host="127.0.0.1", port=5050, debug=False)
