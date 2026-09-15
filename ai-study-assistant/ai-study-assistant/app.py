"""
AI Learning & Study Assistant
=============================
A Flask backend implementing the three capabilities from the brief:

  RAG      -> materials.py   (chunking + TF-IDF retrieval over uploaded course material)
  Memory   -> memory.py      (per-session conversation history persisted in SQLite)
  Tools    -> tools.py       (study-plan generator, quiz generator, summarizer)

Works with zero configuration (pure-Python fallbacks for every tool), and gets
noticeably smarter if you set ANTHROPIC_API_KEY, in which case the assistant
calls Claude with real tool-use to write answers, quizzes and study plans
grounded in whatever material the student uploaded.
"""

import os
import uuid

from flask import Flask, request, jsonify, session, send_from_directory

from db import init_db
from materials import save_material, list_materials, delete_material, retrieve_chunks
from memory import add_message, get_history, clear_history
from agent import answer_question, generate_quiz, generate_study_plan

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

MAX_UPLOAD_MB = 8
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def get_session_id():
    """Every browser tab gets its own memory + material shelf."""
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


@app.route("/")
def index():
    return app.send_static_file("index.html") if os.path.exists(
        os.path.join(app.static_folder, "index.html")
    ) else send_from_directory(app.template_folder, "index.html")


# ---------------------------------------------------------------- materials
@app.route("/api/materials", methods=["GET"])
def api_list_materials():
    sid = get_session_id()
    return jsonify(list_materials(sid))


@app.route("/api/materials", methods=["POST"])
def api_upload_material():
    sid = get_session_id()

    text = None
    title = None

    if "file" in request.files and request.files["file"].filename:
        f = request.files["file"]
        title = f.filename
        raw = f.read()
        text = extract_text(raw, f.filename)
    else:
        data = request.get_json(silent=True) or {}
        text = data.get("text")
        title = data.get("title") or "Pasted notes"

    if not text or not text.strip():
        return jsonify({"error": "No readable text found in that upload."}), 400

    material = save_material(sid, title, text)
    return jsonify(material), 201


@app.route("/api/materials/<material_id>", methods=["DELETE"])
def api_delete_material(material_id):
    sid = get_session_id()
    delete_material(sid, material_id)
    return jsonify({"deleted": material_id})


def extract_text(raw_bytes, filename):
    """Best-effort text extraction for txt/md/pdf uploads."""
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            import io

            reader = PdfReader(io.BytesIO(raw_bytes))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # pragma: no cover - defensive
            return f"[Could not parse PDF: {exc}]"
    # txt / md / anything else: decode as text
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("latin-1", errors="ignore")


# -------------------------------------------------------------------- chat
@app.route("/api/chat", methods=["POST"])
def api_chat():
    sid = get_session_id()
    data = request.get_json(force=True) or {}
    question = (data.get("message") or "").strip()
    if not question:
        return jsonify({"error": "Message can't be empty."}), 400

    history = get_history(sid, limit=12)
    chunks = retrieve_chunks(sid, question, top_k=4)

    reply, used_sources = answer_question(question, history, chunks)

    add_message(sid, "user", question)
    add_message(sid, "assistant", reply)

    return jsonify({"reply": reply, "sources": used_sources})


@app.route("/api/memory", methods=["GET"])
def api_get_memory():
    sid = get_session_id()
    return jsonify(get_history(sid, limit=200))


@app.route("/api/memory", methods=["DELETE"])
def api_clear_memory():
    sid = get_session_id()
    clear_history(sid)
    return jsonify({"cleared": True})


# ------------------------------------------------------------------ tools
@app.route("/api/quiz", methods=["POST"])
def api_quiz():
    sid = get_session_id()
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    n_questions = int(data.get("num_questions") or 5)
    n_questions = max(3, min(n_questions, 10))

    chunks = retrieve_chunks(sid, topic or "overview", top_k=6)
    quiz = generate_quiz(topic, chunks, n_questions)
    return jsonify(quiz)


@app.route("/api/plan", methods=["POST"])
def api_plan():
    sid = get_session_id()
    data = request.get_json(silent=True) or {}
    goal = (data.get("goal") or "").strip()
    days = int(data.get("days") or 7)
    minutes_per_day = int(data.get("minutes_per_day") or 45)
    days = max(1, min(days, 30))

    chunks = retrieve_chunks(sid, goal or "overview", top_k=6)
    plan = generate_study_plan(goal, days, minutes_per_day, chunks)
    return jsonify(plan)


@app.route("/api/health")
def api_health():
    from agent import LLM_AVAILABLE

    return jsonify({"status": "ok", "llm_backed": LLM_AVAILABLE})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
