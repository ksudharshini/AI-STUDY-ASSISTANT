"""
Agent layer -- turns (question | memory | retrieved chunks) into a reply,
and exposes two "tools" a student can invoke directly: quiz generation and
study-plan generation.

If ANTHROPIC_API_KEY is set, every function below calls Claude, grounded in
the retrieved material and passed the recent conversation as memory. If it
isn't set, deterministic fallbacks kick in so the whole app still works with
zero configuration -- useful for local testing or grading without a key.
"""

import json
import os
import random
import re

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
LLM_AVAILABLE = bool(ANTHROPIC_API_KEY)

_client = None
if LLM_AVAILABLE:
    try:
        import anthropic

        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception:
        LLM_AVAILABLE = False
        _client = None

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


def _format_context(chunks):
    if not chunks:
        return "No course material has been uploaded yet."
    parts = []
    for c in chunks:
        parts.append(f"[Source: {c['source']}]\n{c['content']}")
    return "\n\n".join(parts)


def _format_memory(history):
    if not history:
        return []
    return [{"role": h["role"], "content": h["content"]} for h in history]


# --------------------------------------------------------------- chat / RAG
def answer_question(question, history, chunks):
    sources = sorted({c["source"] for c in chunks}) if chunks else []

    if LLM_AVAILABLE:
        system = (
            "You are a friendly, encouraging AI study assistant for students. "
            "Answer using the course material context below when it's relevant; "
            "if the context doesn't cover the question, answer from general "
            "knowledge but say so. Keep answers focused and use short paragraphs "
            "or bullet points for clarity.\n\n"
            f"COURSE MATERIAL CONTEXT:\n{_format_context(chunks)}"
        )
        messages = _format_memory(history) + [{"role": "user", "content": question}]
        try:
            resp = _client.messages.create(
                model=MODEL,
                max_tokens=800,
                system=system,
                messages=messages,
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            return text.strip(), sources
        except Exception as exc:  # pragma: no cover - network/runtime issues
            return (
                f"(LLM call failed, showing extractive fallback: {exc})\n\n"
                + _extractive_answer(question, chunks),
                sources,
            )

    return _extractive_answer(question, chunks), sources


def _extractive_answer(question, chunks):
    if not chunks:
        return (
            "I don't have any course material uploaded yet, so I can't ground an "
            "answer in your notes. Upload a document in the Materials tab, or set "
            "ANTHROPIC_API_KEY on the server for open-ended answers."
        )
    best = chunks[0]
    snippet = best["content"]
    if len(snippet) > 600:
        snippet = snippet[:600].rsplit(" ", 1)[0] + "..."
    return (
        f"Here's the most relevant passage I found in **{best['source']}**:\n\n"
        f"> {snippet}\n\n"
        "(This is a plain-text extractive match. Set ANTHROPIC_API_KEY on the "
        "server for a fully reasoned, synthesized answer.)"
    )


# -------------------------------------------------------------------- quiz
def generate_quiz(topic, chunks, n_questions):
    if LLM_AVAILABLE:
        context = _format_context(chunks)
        prompt = (
            f"Create a {n_questions}-question multiple-choice quiz about "
            f"'{topic or 'the uploaded material'}' using ONLY the context below. "
            "Return strict JSON: "
            '{"title": str, "questions": [{"question": str, "options": [str,str,str,str], '
            '"correct_index": int, "explanation": str}]}. No prose outside the JSON.\n\n'
            f"CONTEXT:\n{context}"
        )
        try:
            resp = _client.messages.create(
                model=MODEL,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            return _safe_json(text, fallback=lambda: _fallback_quiz(topic, chunks, n_questions))
        except Exception:
            return _fallback_quiz(topic, chunks, n_questions)

    return _fallback_quiz(topic, chunks, n_questions)


def _fallback_quiz(topic, chunks, n_questions):
    """Rule-based fill-in-the-blank quiz built from the retrieved sentences."""
    sentences = []
    for c in chunks:
        for s in re.split(r"(?<=[.!?])\s+", c["content"]):
            s = s.strip()
            words = s.split()
            if 8 <= len(words) <= 32:
                sentences.append((s, c["source"]))

    random.shuffle(sentences)
    questions = []
    for sentence, source in sentences:
        if len(questions) >= n_questions:
            break
        words = [w for w in sentence.split() if len(re.sub(r"[^\w]", "", w)) > 5]
        if not words:
            continue
        answer_word = random.choice(words)
        blanked = sentence.replace(answer_word, "ـ" * len(re.sub(r"[^\w]", "", answer_word)), 1)
        clean_answer = re.sub(r"[^\w]", "", answer_word)

        distractors = _distractor_pool(clean_answer, [w for s, _ in sentences for w in s.split()])
        options = list({clean_answer, *distractors})
        while len(options) < 4:
            options.append(random.choice(["concept", "process", "system", "method"]))
        options = options[:4]
        random.shuffle(options)

        questions.append(
            {
                "question": f"Fill in the blank: {blanked}",
                "options": options,
                "correct_index": options.index(clean_answer),
                "explanation": f"From your material ({source}): \"{sentence}\"",
            }
        )

    if not questions:
        questions = [
            {
                "question": "No course material has enough content to quiz on yet -- "
                "upload some notes in the Materials tab first!",
                "options": ["Upload material", "Try again", "N/A", "N/A"],
                "correct_index": 0,
                "explanation": "The quiz tool builds questions from your uploaded material.",
            }
        ]

    return {"title": f"Quiz: {topic or 'Your material'}", "questions": questions}


def _distractor_pool(answer, all_words):
    candidates = {
        re.sub(r"[^\w]", "", w)
        for w in all_words
        if len(re.sub(r"[^\w]", "", w)) > 5 and re.sub(r"[^\w]", "", w).lower() != answer.lower()
    }
    return random.sample(list(candidates), k=min(3, len(candidates)))


def _safe_json(text, fallback):
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return fallback()
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return fallback()


# ------------------------------------------------------------- study plan
def generate_study_plan(goal, days, minutes_per_day, chunks):
    if LLM_AVAILABLE:
        context = _format_context(chunks)
        prompt = (
            f"Build a {days}-day study plan ({minutes_per_day} minutes/day) for the goal: "
            f"'{goal or 'general review of the uploaded material'}'. Ground it in the context "
            "below where relevant. Return strict JSON: "
            '{"goal": str, "days": [{"day": int, "focus": str, "tasks": [str, ...]}]}. '
            "No prose outside the JSON.\n\n"
            f"CONTEXT:\n{context}"
        )
        try:
            resp = _client.messages.create(
                model=MODEL,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            return _safe_json(
                text, fallback=lambda: _fallback_plan(goal, days, minutes_per_day, chunks)
            )
        except Exception:
            return _fallback_plan(goal, days, minutes_per_day, chunks)

    return _fallback_plan(goal, days, minutes_per_day, chunks)


def _fallback_plan(goal, days, minutes_per_day, chunks):
    topics = [c["source"] for c in chunks] or ["your material"]
    topics = list(dict.fromkeys(topics))  # de-dupe, keep order

    stages = ["Skim & orient", "Deep read", "Practice recall", "Apply & quiz", "Review gaps"]
    plan_days = []
    for i in range(1, days + 1):
        stage = stages[min(i - 1, len(stages) - 1)] if i <= len(stages) else "Cumulative review"
        topic = topics[(i - 1) % len(topics)]
        plan_days.append(
            {
                "day": i,
                "focus": f"{stage}: {topic}",
                "tasks": [
                    f"Spend ~{max(minutes_per_day // 3, 10)} min re-reading key sections of {topic}",
                    "Write a 5-bullet summary from memory, then check it against the source",
                    "Use the Quiz tool on this topic and log any missed questions",
                ],
            }
        )

    return {
        "goal": goal or "Review uploaded material",
        "days": plan_days,
        "note": "Deterministic fallback plan -- set ANTHROPIC_API_KEY for a plan tailored "
        "by an LLM to your specific goal and material.",
    }
