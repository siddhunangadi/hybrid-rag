const $ = (sel) => document.querySelector(sel);
const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);
const keyInput = $("#api-key");
const ACTIVE = new Set(["queued", "processing"]);
let pollTimer;
let history = [];

try { keyInput.value = localStorage.getItem("rag_api_key") || ""; } catch {}

async function api(path, options = {}) {
  const headers = { ...options.headers, Authorization: `Bearer ${keyInput.value.trim()}` };
  const res = await fetch(path, { ...options, headers });
  if (res.status === 204) return {};
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? res.statusText);
    throw new Error(`${res.status}: ${detail}`);
  }
  return body;
}

function logLine(text, cls = "") {
  const li = document.createElement("li");
  li.className = cls;
  li.textContent = text;
  $("#ingest-log").prepend(li);
}

async function refreshDocs() {
  clearTimeout(pollTimer);
  if (!keyInput.value.trim()) return;
  try {
    const { documents } = await api("/documents");
    $("#docs").innerHTML = documents.map((d) => `<tr>
        <td>${esc(d.source)}</td>
        <td class="status ${d.status}">${d.status}${d.error ? `: ${esc(d.error)}` : ""}</td>
        <td>${d.chunks}</td>
        <td><button class="link" data-delete="${esc(d.source)}">Delete</button></td>
      </tr>`).join("") || `<tr><td colspan="4" class="muted">No documents yet.</td></tr>`;
    if (documents.some((d) => ACTIVE.has(d.status))) pollTimer = setTimeout(refreshDocs, 2000);
  } catch (err) {
    $("#docs").innerHTML = `<tr><td colspan="4" class="status failed">${esc(err.message)}</td></tr>`;
  }
}

function addMessage(cls, html) {
  $("#messages .empty")?.remove();
  const el = document.createElement("div");
  el.className = `msg ${cls}`;
  el.innerHTML = html;
  $("#messages").append(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}

function renderAnswer(el, asked, { answer, citations, latency_ms: t, gated, reason, top_similarity, usage, question, trace_id }) {
  const body = esc(answer)
    .replace(/\n/g, "<br>")
    .replace(/\[(\d+)\]/g, (_, n) => `<a href="#" class="cite" data-n="${n}">[${n}]</a>`);
  const sources = citations.map((c) => {
    const ranks = [c.dense_rank && `dense #${c.dense_rank}`, c.sparse_rank && `lexical #${c.sparse_rank}`].filter(Boolean).join(", ");
    const where = c.page ? `page ${c.page}` : `chunk ${c.chunk_index}`;
    return `<details data-n="${c.id}"><summary><span class="badge">[${c.id}]</span> ${esc(c.source)} · ${where} · RRF ${c.score.toFixed(4)} (${ranks})</summary><p>${esc(c.content)}</p></details>`;
  }).join("");
  const stats = [
    `retrieval ${t.retrieval} ms`, `generation ${t.generation} ms`, `total ${t.total} ms`, `top sim ${top_similarity}`,
    usage && `${Object.values(usage).reduce((a, b) => a + b, 0)} tokens`, gated && "gated, no LLM call", reason && esc(reason),
  ].filter(Boolean).join(" · ");
  const rewritten = question !== asked ? `<div class="stats">searched for: ${esc(question)}</div>` : "";
  const vote = trace_id ? `<span class="vote" data-trace="${trace_id}"><button class="link" data-score="1" title="Helpful">👍</button><button class="link" data-score="0" title="Not helpful">👎</button></span>` : "";
  el.className = "msg bot";
  el.innerHTML = `${rewritten}<div>${body}</div>${sources && `<div class="sources">${sources}</div>`}<div class="stats">${stats} ${vote}</div>`;
}

keyInput.addEventListener("change", () => {
  try { localStorage.setItem("rag_api_key", keyInput.value.trim()); } catch {}
  refreshDocs();
});

$("#docs").addEventListener("click", async (e) => {
  const source = e.target.dataset.delete;
  if (!source || !confirm(`Delete ${source} and all its chunks?`)) return;
  try {
    await api(`/documents/${encodeURIComponent(source)}`, { method: "DELETE" });
  } catch (err) {
    logLine(`✗ ${err.message}`, "err");
  }
  refreshDocs();
});

$("#messages").addEventListener("click", async (e) => {
  const vote = e.target.closest(".vote button");
  if (vote) {
    const box = vote.parentElement;
    try {
      await api("/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trace_id: box.dataset.trace, score: Number(vote.dataset.score) }),
      });
      box.textContent = "thanks for the feedback";
    } catch (err) {
      box.textContent = err.message;
    }
    return;
  }
  const link = e.target.closest(".cite");
  if (!link) return;
  e.preventDefault();
  const details = link.closest(".msg").querySelector(`details[data-n="${link.dataset.n}"]`);
  if (details) {
    details.open = true;
    details.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
});

$("#upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData();
  [...$("#files").files].forEach((f) => form.append("files", f));
  e.submitter.disabled = true;
  try {
    const { documents } = await api("/ingest", { method: "POST", body: form });
    documents.filter((d) => d.error).forEach((d) => logLine(`✗ ${d.source}: ${d.error}`, "err"));
    e.target.reset();
  } catch (err) {
    logLine(`✗ ${err.message}`, "err");
  } finally {
    e.submitter.disabled = false;
    refreshDocs();
  }
});

$("#ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#question");
  const question = input.value.trim();
  if (!question) return;
  addMessage("user", esc(question));
  input.value = "";
  e.submitter.disabled = true;
  const pending = addMessage("bot pending", "Searching and generating…");
  try {
    const data = await api("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    });
    renderAnswer(pending, question, data);
    history = [...history, { role: "user", content: question }, { role: "assistant", content: data.answer }].slice(-6);
  } catch (err) {
    pending.className = "msg bot error";
    pending.textContent = err.message;
  } finally {
    e.submitter.disabled = false;
    input.focus();
  }
});

$("#new-chat").addEventListener("click", () => {
  history = [];
  $("#messages").innerHTML = `<p class="muted empty">New conversation. Ask a question.</p>`;
});

refreshDocs();
