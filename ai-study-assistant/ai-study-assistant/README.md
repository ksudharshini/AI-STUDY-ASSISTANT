# AI Learning & Study Assistant

A full-stack study assistant matching the use case: creates learning plans, answers
questions from course materials, and generates quizzes — using **RAG + Memory + Tools**.

| Capability | How it's implemented |
|---|---|
| **RAG** | `materials.py` — uploads are chunked and indexed with TF-IDF; questions retrieve the most relevant chunks by cosine similarity (`sklearn`). No embeddings API required. |
| **Memory** | `memory.py` — every message is persisted per-session in SQLite, so conversation history survives page reloads and server restarts. |
| **Tools** | `agent.py` — a quiz generator and a study-plan generator, callable directly from the UI, plus the RAG-grounded chat itself. |

It runs **out of the box with zero configuration** using deterministic, rule-based
fallbacks for every tool. Set `ANTHROPIC_API_KEY` to upgrade chat answers, quizzes, and
study plans to be written by Claude, grounded in your retrieved material.

## Quick start

```bash
# 1. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) enable Claude-backed answers
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...

# 4. Run it
python app.py
```

Then open **http://localhost:5000** in your browser.

If you skip step 3, the app still fully works: chat gives extractive answers
from your uploaded notes, quizzes use fill-in-the-blank questions built from
your material, and study plans use a structured template — no external API
calls are made.

## Project layout

```
ai-study-assistant/
├── app.py            Flask routes (upload, chat, quiz, plan, memory)
├── db.py             SQLite schema + connection helper
├── materials.py       RAG: chunking + TF-IDF retrieval
├── memory.py          Per-session conversation history
├── agent.py            LLM calls + deterministic fallbacks (the "tools")
├── templates/
│   └── index.html      App shell
├── static/
│   ├── style.css       Design
│   └── app.js            Frontend logic (fetch calls, rendering)
├── data/                SQLite database lives here at runtime (gitignored)
├── requirements.txt
├── .env.example
└── README.md
```

## API reference

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/materials` | List uploaded materials for this session |
| `POST` | `/api/materials` | Upload a file (`multipart/form-data`, field `file`) or paste text (`{"text": "...", "title": "..."}`) |
| `DELETE` | `/api/materials/<id>` | Remove a material and its chunks |
| `POST` | `/api/chat` | `{"message": "..."}` → `{"reply": "...", "sources": [...]}` |
| `GET`  | `/api/memory` | Full conversation history for this session |
| `DELETE` | `/api/memory` | Clear conversation history |
| `POST` | `/api/quiz` | `{"topic": "...", "num_questions": 5}` → quiz JSON |
| `POST` | `/api/plan` | `{"goal": "...", "days": 7, "minutes_per_day": 45}` → plan JSON |
| `GET`  | `/api/health` | `{"status": "ok", "llm_backed": true/false}` |

## Notes on sessions & storage

- Each browser gets an anonymous session id in a signed cookie (Flask's
  built-in session, keyed by `SECRET_KEY`). Materials, chat history, and
  memory are all scoped to that session id in SQLite (`data/study_assistant.db`).
- This is intentionally simple (no user accounts) so it's easy to run
  locally or extend. For multi-user production use, add real
  authentication and swap SQLite for Postgres.

## Deploying

Any host that runs a WSGI app works. Example with gunicorn:

```bash
pip install -r requirements.txt
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

Make sure `data/` is writable, and set `SECRET_KEY` / `ANTHROPIC_API_KEY`
as real environment variables (don't ship your `.env` file).
