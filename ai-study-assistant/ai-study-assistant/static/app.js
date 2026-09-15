// ---------------------------------------------------------------- shell --
const tabs = document.querySelectorAll(".rail-tab");
const views = document.querySelectorAll(".view");

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((t) => t.classList.remove("is-active"));
    views.forEach((v) => v.classList.remove("is-active"));
    tab.classList.add("is-active");
    document.getElementById(`view-${tab.dataset.view}`).classList.add("is-active");
  });
});

fetch("/api/health")
  .then((r) => r.json())
  .then((d) => {
    const el = document.getElementById("llm-status");
    el.textContent = d.llm_backed
      ? "Claude-backed answers"
      : "Offline mode (no API key set)";
  })
  .catch(() => {
    document.getElementById("llm-status").textContent = "Engine status unknown";
  });

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------------------------------------------------------------- chat ---
const chatThread = document.getElementById("chat-thread");
const chatEmpty = document.getElementById("chat-empty");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

function renderMessage(role, content, sources) {
  chatEmpty.style.display = "none";
  const wrap = document.createElement("div");
  wrap.className = `msg msg-${role}`;
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.innerHTML = escapeHtml(content).replace(/\n/g, "<br>");
  wrap.appendChild(bubble);
  if (sources && sources.length) {
    const src = document.createElement("div");
    src.className = "msg-sources";
    src.textContent = `Grounded in: ${sources.join(", ")}`;
    wrap.appendChild(src);
  }
  chatThread.appendChild(wrap);
  chatThread.scrollTop = chatThread.scrollHeight;
}

async function loadMemory() {
  const res = await fetch("/api/memory");
  const history = await res.json();
  history.forEach((m) => renderMessage(m.role, m.content));
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  renderMessage("user", text);
  chatInput.value = "";
  chatInput.disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    if (data.error) {
      renderMessage("assistant", `Error: ${data.error}`);
    } else {
      renderMessage("assistant", data.reply, data.sources);
    }
  } catch (err) {
    renderMessage("assistant", `Network error: ${err.message}`);
  } finally {
    chatInput.disabled = false;
    chatInput.focus();
  }
});

loadMemory();

// ----------------------------------------------------------- materials --
const materialsList = document.getElementById("materials-list");
const fileInput = document.getElementById("file-input");
const browseBtn = document.getElementById("browse-btn");
const uploadDrop = document.getElementById("upload-drop");
const pasteText = document.getElementById("paste-text");
const pasteSubmit = document.getElementById("paste-submit");

async function loadMaterials() {
  const res = await fetch("/api/materials");
  const items = await res.json();
  materialsList.innerHTML = "";
  if (!items.length) {
    materialsList.innerHTML = '<li class="materials-empty">No materials uploaded yet.</li>';
    return;
  }
  items.forEach((m) => {
    const li = document.createElement("li");
    li.className = "material-row";
    li.innerHTML = `
      <div>
        <div class="material-title">${escapeHtml(m.title)}</div>
        <div class="material-meta">${m.chunk_count} chunk${m.chunk_count === 1 ? "" : "s"} indexed</div>
      </div>
      <button class="material-remove" data-id="${m.id}">Remove</button>
    `;
    materialsList.appendChild(li);
  });
  materialsList.querySelectorAll(".material-remove").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`/api/materials/${btn.dataset.id}`, { method: "DELETE" });
      loadMaterials();
    });
  });
}

async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/materials", { method: "POST", body: form });
  const data = await res.json();
  if (data.error) alert(data.error);
  loadMaterials();
}

browseBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) uploadFile(fileInput.files[0]);
});

["dragover", "dragenter"].forEach((evt) =>
  uploadDrop.addEventListener(evt, (e) => {
    e.preventDefault();
    uploadDrop.classList.add("is-dragover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  uploadDrop.addEventListener(evt, (e) => {
    e.preventDefault();
    uploadDrop.classList.remove("is-dragover");
  })
);
uploadDrop.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
});

pasteSubmit.addEventListener("click", async () => {
  const text = pasteText.value.trim();
  if (!text) return;
  const res = await fetch("/api/materials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title: `Pasted notes ${new Date().toLocaleTimeString()}` }),
  });
  const data = await res.json();
  if (data.error) alert(data.error);
  pasteText.value = "";
  loadMaterials();
});

loadMaterials();

// ----------------------------------------------------------------- quiz --
const quizForm = document.getElementById("quiz-form");
const quizBody = document.getElementById("quiz-body");

quizForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const topic = document.getElementById("quiz-topic").value.trim();
  const num_questions = parseInt(document.getElementById("quiz-count").value, 10);
  quizBody.innerHTML = '<p class="placeholder-copy">Building your quiz…</p>';

  const res = await fetch("/api/quiz", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, num_questions }),
  });
  const quiz = await res.json();
  renderQuiz(quiz);
});

function renderQuiz(quiz) {
  quizBody.innerHTML = "";
  quiz.questions.forEach((q, i) => {
    const card = document.createElement("div");
    card.className = "quiz-card";
    const optionsHtml = q.options
      .map((opt, oi) => `<button class="quiz-option" data-i="${oi}">${escapeHtml(opt)}</button>`)
      .join("");
    card.innerHTML = `
      <div class="quiz-index">${String(i + 1).padStart(2, "0")}</div>
      <div>
        <p class="quiz-question">${escapeHtml(q.question)}</p>
        <div class="quiz-options">${optionsHtml}</div>
        <div class="quiz-explain">${escapeHtml(q.explanation || "")}</div>
      </div>
    `;
    const buttons = card.querySelectorAll(".quiz-option");
    const explain = card.querySelector(".quiz-explain");
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        if (card.dataset.answered) return;
        card.dataset.answered = "true";
        const chosen = parseInt(btn.dataset.i, 10);
        buttons.forEach((b, bi) => {
          if (bi === q.correct_index) b.classList.add("is-correct");
          else if (bi === chosen) b.classList.add("is-wrong");
        });
        explain.classList.add("is-shown");
      });
    });
    quizBody.appendChild(card);
  });
}

// ----------------------------------------------------------------- plan --
const planForm = document.getElementById("plan-form");
const planBody = document.getElementById("plan-body");

planForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const goal = document.getElementById("plan-goal").value.trim();
  const days = parseInt(document.getElementById("plan-days").value, 10);
  const minutes_per_day = parseInt(document.getElementById("plan-minutes").value, 10);
  planBody.innerHTML = '<p class="placeholder-copy">Building your plan…</p>';

  const res = await fetch("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal, days, minutes_per_day }),
  });
  const plan = await res.json();
  renderPlan(plan);
});

function renderPlan(plan) {
  planBody.innerHTML = "";
  plan.days.forEach((d) => {
    const row = document.createElement("div");
    row.className = "plan-day";
    const tasksHtml = d.tasks.map((t) => `<li>${escapeHtml(t)}</li>`).join("");
    row.innerHTML = `
      <div class="plan-day-num">D${d.day}</div>
      <div>
        <p class="plan-focus">${escapeHtml(d.focus)}</p>
        <ul class="plan-tasks">${tasksHtml}</ul>
      </div>
    `;
    planBody.appendChild(row);
  });
  if (plan.note) {
    const note = document.createElement("p");
    note.className = "plan-note";
    note.textContent = plan.note;
    planBody.appendChild(note);
  }
}
