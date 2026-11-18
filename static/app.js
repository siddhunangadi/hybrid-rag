const $ = (sel, root = document) => root.querySelector(sel);
const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

const INSUFFICIENT = "Insufficient context";
const ACTIVE = new Set(["queued", "processing"]);
const SUPPORTED = /\.(pdf|txt|md)$/i;

const icon = (paths) => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
const ICONS = {
  trash: icon('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>'),
  copy: icon('<rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15"/>'),
  check: icon('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
  up: icon('<path d="M7 11v9H4v-9h3zM7 11l4-7.5a2 2 0 0 1 3.4 1.6L13.5 9H19a2 2 0 0 1 2 2.3l-1.1 6.6A2.5 2.5 0 0 1 17.4 20H7"/>'),
  down: icon('<path d="M7 13V4H4v9h3zM7 13l4 7.5a2 2 0 0 0 3.4-1.6l-.9-3.9H19a2 2 0 0 0 2-2.3l-1.1-6.6A2.5 2.5 0 0 0 17.4 4H7"/>'),
  search: icon('<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>'),
  info: icon('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>'),
  alert: icon('<path d="M12 3.5l9 16H3l9-16z"/><path d="M12 10v4M12 17h.01"/>'),
};

const els = {
  thread: $("#thread"),
  inner: $("#thread-inner"),
  composer: $("#composer"),
  question: $("#question"),
  send: $("#send"),
  docList: $("#doc-list"),
  docCount: $("#doc-count"),
  dropzone: $("#dropzone"),
  fileInput: $("#file-input"),
  conn: $("#conn"),
  settings: $("#settings"),
  keyInput: $("#api-key"),
  library: $("#library"),
  toasts: $("#toasts"),
};

const state = { history: [], pollTimer: 0, busy: false, docsKey: "" };

const keyStore = {
  get() { try { return localStorage.getItem("rag_api_key") || ""; } catch { return ""; } },
  set(value) { try { localStorage.setItem("rag_api_key", value); } catch { /* private mode: key lasts for this page */ } },
};
let apiKey = keyStore.get();

// ---------- API ----------
class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, options = {}) {
  let res;
  try {
    const auth = apiKey ? { Authorization: `Bearer ${apiKey}` } : {};  // no key: open-mode server
    res = await fetch(path, { ...options, headers: { ...options.headers, ...auth } });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  if (res.status === 204) return {};
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
  return body;
}

function friendly(err) {
  switch (err.status) {
    case 401: return "Your API key isn't valid. Open Connect to update it.";
    case 409: return "Feedback isn't enabled on this server.";
    case 502: return "A service this app relies on didn't respond. Please try again.";
    case 504: return "That took too long to answer. Please try again.";
    default: return err.message || "Something went wrong.";
  }
}

// ---------- Feedback UI ----------
function toast(message, tone = "") {
  const el = document.createElement("div");
  el.className = `toast ${tone}`;
  el.textContent = message;
  els.toasts.append(el);
  setTimeout(() => {
    el.classList.add("leaving");
    el.addEventListener("animationend", () => el.remove(), { once: true });
  }, 4200);
}

function setConn(name, label) {
  els.conn.dataset.state = name;
  $(".conn-label", els.conn).textContent = label;
}

// ---------- Library ----------
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
function ago(iso) {
  const seconds = (new Date(iso) - Date.now()) / 1000;
  for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

function docItem(d) {
  const type = (d.source.split(".").pop() || "").toUpperCase().slice(0, 4);
  const meta = {
    ready: `${d.chunks} ${d.chunks === 1 ? "passage" : "passages"} · ${ago(d.updated_at)}`,
    processing: "Processing…",
    queued: "Waiting to process…",
    failed: d.error || "Couldn't be processed",
  }[d.status] ?? d.status;
  return `<li class="doc" data-status="${esc(d.status)}" data-type="${esc(type)}">
    <span class="doc-badge" aria-hidden="true">${esc(type)}</span>
    <span class="doc-main">
      <span class="doc-name" title="${esc(d.source)}">${esc(d.source)}</span>
      <span class="doc-meta" title="${esc(meta)}"><span class="status-dot"></span><span class="doc-meta-text">${esc(meta)}</span></span>
    </span>
    <button class="icon-btn doc-delete" type="button" data-delete="${esc(d.source)}" aria-label="Delete ${esc(d.source)}">${ICONS.trash}</button>
  </li>`;
}

function renderDocs(docs, message) {
  els.docCount.textContent = docs?.length ? String(docs.length) : "";
  if (!docs) {
    els.docList.innerHTML = `<li class="doc-empty">${esc(message || "Connect with your API key to see your library.")}</li>`;
  } else if (!docs.length) {
    els.docList.innerHTML = `<li class="doc-empty">No documents yet. Add a PDF, Markdown or text file to get started.</li>`;
  } else {
    els.docList.innerHTML = docs.map(docItem).join("");
  }
}

async function refreshDocs() {
  clearTimeout(state.pollTimer);
  try {
    const { documents } = await api("/documents");
    setConn("on", "Connected");
    // Re-render only on change, so polling doesn't reset a pending delete confirmation.
    const key = JSON.stringify(documents.map((d) => [d.source, d.status, d.chunks, d.error]));
    if (key !== state.docsKey) {
      state.docsKey = key;
      renderDocs(documents);
    }
    if (documents.some((d) => ACTIVE.has(d.status))) state.pollTimer = setTimeout(refreshDocs, 2000);
  } catch (err) {
    state.docsKey = "";
    if (err.status === 401 && apiKey && !state.retriedWithoutKey) {
      // A saved key was rejected: try once without it, in case the server is in open mode.
      state.retriedWithoutKey = true;
      const saved = apiKey;
      apiKey = "";
      try {
        await api("/documents");
        keyStore.set("");  // open mode works, so forget the stale key
        return refreshDocs();
      } catch {
        apiKey = saved;
      }
    }
    if (err.status === 401 && !apiKey) {  // this server requires keys
      setConn("off", "Not connected");
      renderDocs(null);
      openSettings();
      return;
    }
    setConn("bad", err.status === 401 ? "Invalid key" : "Offline");
    renderDocs(null, friendly(err));
  }
}

els.docList.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-delete]");
  if (!btn) return;
  const source = btn.dataset.delete;
  if (!btn.classList.contains("confirm")) {
    btn.classList.add("confirm");
    btn.textContent = "Delete";
    btn.setAttribute("aria-label", `Confirm deleting ${source}`);
    setTimeout(() => {
      if (btn.isConnected && btn.classList.contains("confirm") && !btn.disabled) {
        btn.classList.remove("confirm");
        btn.innerHTML = ICONS.trash;
        btn.setAttribute("aria-label", `Delete ${source}`);
      }
    }, 3000);
    return;
  }
  btn.disabled = true;
  try {
    await api(`/documents/${encodeURIComponent(source)}`, { method: "DELETE" });
    toast(`Deleted ${source}`);
  } catch (err) {
    toast(friendly(err), "error");
  }
  state.docsKey = "";
  refreshDocs();
});

async function upload(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  files.filter((f) => !SUPPORTED.test(f.name))
    .forEach((f) => toast(`${f.name}: only PDF, Markdown and text files are supported`, "error"));
  const accepted = files.filter((f) => SUPPORTED.test(f.name));
  if (!accepted.length) return;

  const form = new FormData();
  accepted.forEach((f) => form.append("files", f));
  const title = $(".dz-title", els.dropzone);
  els.dropzone.classList.add("busy");
  title.textContent = accepted.length === 1 ? "Uploading…" : `Uploading ${accepted.length} files…`;
  try {
    const { documents } = await api("/ingest", { method: "POST", body: form });
    const failed = documents.filter((d) => d.error);
    failed.forEach((d) => toast(`${d.source}: ${d.error}`, "error"));
    const added = documents.length - failed.length;
    if (added) toast(added === 1 ? "Added 1 document. It will be ready in a moment." : `Added ${added} documents. They will be ready in a moment.`);
  } catch (err) {
    toast(friendly(err), "error");
  } finally {
    els.dropzone.classList.remove("busy");
    title.textContent = "Add documents";
    els.fileInput.value = "";
    state.docsKey = "";
    refreshDocs();
  }
}

els.dropzone.addEventListener("click", () => els.fileInput.click());
els.fileInput.addEventListener("change", () => upload(els.fileInput.files));

let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
document.addEventListener("dragenter", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth += 1;
  document.body.classList.add("dragging");
});
document.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
document.addEventListener("dragleave", (e) => {
  if (!hasFiles(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) document.body.classList.remove("dragging");
});
document.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging");
  upload(e.dataTransfer.files);
});

// ---------- Conversation ----------
function showIntro() {
  els.inner.replaceChildren($("#intro-template").content.cloneNode(true));
}

function scrollToEnd() {
  els.thread.scrollTo({ top: els.thread.scrollHeight, behavior: "smooth" });
}

function addMessage(className) {
  $(".intro", els.inner)?.remove();
  const el = document.createElement("div");
  el.className = `msg ${className}`;
  els.inner.append(el);
  return el;
}

// Minimal, safe formatting: escape first, then paragraphs, bullet lists, **bold** and [n] citations.
function renderText(text, citedIds) {
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(\d+)\]/g, (match, n) => (citedIds.has(Number(n))
      ? `<button type="button" class="cite" data-n="${n}" aria-label="Show source ${n}">${n}</button>`
      : match));
  return text.trim().split(/\n{2,}/).map((block) => {
    const lines = block.split("\n");
    if (lines.every((l) => /^\s*[-*•]\s+/.test(l))) {
      return `<ul>${lines.map((l) => `<li>${inline(l.replace(/^\s*[-*•]\s+/, ""))}</li>`).join("")}</ul>`;
    }
    return `<p>${lines.map(inline).join("<br>")}</p>`;
  }).join("");
}

function sourceCard(c) {
  // Chunks are stored as "[Document > section]\n" + text; show the label separately.
  const match = /^\[(.+?)\]\n/.exec(c.content);
  const section = match ? match[1] : "";
  // Drop bare Markdown code-fence lines that OCR transcriptions sometimes contain.
  const text = (match ? c.content.slice(match[0].length) : c.content).replace(/^\s*```\w*\s*$/gm, "").trim();
  return `<article class="source" data-n="${c.id}" tabindex="0" aria-label="Source ${c.id}: ${esc(c.source)}">
    <div class="source-head">
      <span class="source-num">${c.id}</span>
      <span class="source-file">${esc(c.source)}</span>
      ${c.page ? `<span class="source-where">p. ${c.page}</span>` : ""}
    </div>
    ${section ? `<div class="source-section">${esc(section)}</div>` : ""}
    <div class="source-text">${esc(text.trim())}</div>
  </article>`;
}

function noAnswerHint(reason, gated) {
  if (reason === "No documents indexed") return "Your library is empty. Add documents first.";
  if (gated) return "Nothing in your library is close to this question. Try rephrasing, or add a document that covers it.";
  return "The closest passages don't answer it, so no answer was made up.";
}

function techDetails(d, tokens) {
  const rows = [
    ["Retrieval", `${d.latency_ms.retrieval} ms`],
    ["Generation", `${d.latency_ms.generation} ms`],
    ["Top similarity", d.top_similarity],
    ["OpenAI tokens", tokens || "none"],
  ];
  if (d.reason) rows.push(["Note", d.reason]);
  (d.citations || []).forEach((c) => rows.push([
    `Source ${c.id}`, `RRF ${c.score.toFixed(4)} · dense #${c.dense_rank ?? "–"} · lexical #${c.sparse_rank ?? "–"}`,
  ]));
  return `<dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
}

function renderAnswer(el, asked, data) {
  const { answer, citations = [], latency_ms: timing, gated, reason, question, trace_id: traceId, usage } = data;
  const tokens = usage ? Object.values(usage).reduce((a, b) => a + b, 0) : 0;
  const parts = [];
  if (question && question !== asked) {
    parts.push(`<div class="searched">${ICONS.search}<span>Searched for “${esc(question)}”</span></div>`);
  }
  if (answer === INSUFFICIENT) {
    parts.push(`<div class="notice">${ICONS.info}<div><p class="notice-title">Your documents don't cover this.</p>`
      + `<p class="notice-text">${esc(noAnswerHint(reason, gated))}</p></div></div>`);
  } else {
    parts.push(`<div class="answer-text">${renderText(answer, new Set(citations.map((c) => c.id)))}</div>`);
    if (citations.length) parts.push(`<div class="sources">${citations.map(sourceCard).join("")}</div>`);
  }
  const vote = traceId
    ? `<span class="vote" data-trace="${esc(traceId)}">`
      + `<button class="icon-btn" type="button" data-score="1" aria-label="Helpful">${ICONS.up}</button>`
      + `<button class="icon-btn" type="button" data-score="0" aria-label="Not helpful">${ICONS.down}</button></span>`
    : "";
  parts.push(`<div class="answer-foot">
    <span class="timing">${(timing.total / 1000).toFixed(1)} s</span>
    ${answer === INSUFFICIENT ? "" : `<button class="icon-btn copy" type="button" aria-label="Copy answer">${ICONS.copy}</button>`}
    ${vote}
    <button class="details-toggle" type="button" aria-expanded="false">Details</button>
  </div>`);
  parts.push(`<div class="tech">${techDetails(data, tokens)}</div>`);
  el.innerHTML = parts.join("");
  el.dataset.copy = answer.replace(/\s*\[\d+\]/g, "").replace(/\*\*/g, "").trim();
}

function focusSource(msg, n) {
  const card = msg?.querySelector(`.source[data-n="${n}"]`);
  if (!card) return;
  card.classList.add("open", "flash");
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  setTimeout(() => card.classList.remove("flash"), 1400);
}

els.inner.addEventListener("click", async (e) => {
  const chip = e.target.closest(".chip");
  if (chip) { setQuestion(chip.dataset.q); return; }

  const cite = e.target.closest(".cite");
  if (cite) { focusSource(cite.closest(".msg"), cite.dataset.n); return; }

  const source = e.target.closest(".source");
  if (source) { source.classList.toggle("open"); return; }

  const toggle = e.target.closest(".details-toggle");
  if (toggle) {
    const open = toggle.closest(".msg").querySelector(".tech").classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "Hide details" : "Details";
    return;
  }

  const copy = e.target.closest(".copy");
  if (copy) {
    try {
      await navigator.clipboard.writeText(copy.closest(".msg").dataset.copy);
      copy.innerHTML = ICONS.check;
      copy.classList.add("done");
      setTimeout(() => { copy.innerHTML = ICONS.copy; copy.classList.remove("done"); }, 1600);
    } catch {
      toast("Couldn't copy to the clipboard.", "error");
    }
    return;
  }

  const vote = e.target.closest(".vote [data-score]");
  if (vote) {
    const box = vote.parentElement;
    box.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      await api("/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trace_id: box.dataset.trace, score: Number(vote.dataset.score) }),
      });
      box.outerHTML = `<span class="thanks">${ICONS.check}Thanks for the feedback</span>`;
    } catch (err) {
      box.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      toast(friendly(err), "error");
    }
  }
});

els.inner.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches(".source")) {
    e.preventDefault();
    e.target.classList.toggle("open");
  }
});

// ---------- Composer ----------
function autosize() {
  const q = els.question;
  q.style.height = "auto";
  // Only measure real text: an empty field keeps its natural one-line height.
  if (q.value) q.style.height = `${Math.min(q.scrollHeight, 168)}px`;
  els.send.disabled = state.busy || !q.value.trim();
}

function setQuestion(text) {
  els.question.value = text;
  autosize();
  els.question.focus();
}

els.question.addEventListener("input", autosize);
els.question.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    els.composer.requestSubmit();
  }
});

els.composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = els.question.value.trim();
  if (!question || state.busy) return;

  state.busy = true;
  addMessage("user").textContent = question;
  els.question.value = "";
  autosize();
  const pending = addMessage("answer");
  pending.innerHTML = `<div class="typing"><span class="dots"><i></i><i></i><i></i></span>Searching your documents</div>`;
  scrollToEnd();
  try {
    const data = await api("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: state.history }),
    });
    renderAnswer(pending, question, data);
    state.history = [...state.history, { role: "user", content: question }, { role: "assistant", content: data.answer }].slice(-6);
  } catch (err) {
    pending.innerHTML = `<div class="notice error">${ICONS.alert}<div><p class="notice-title">Couldn't answer that.</p>`
      + `<p class="notice-text">${esc(friendly(err))}</p></div></div>`;
    if (err.status === 401) setConn("bad", "Invalid key");
  } finally {
    state.busy = false;
    autosize();
    els.question.focus();
    scrollToEnd();
  }
});

$("#new-chat").addEventListener("click", () => {
  state.history = [];
  showIntro();
  els.question.focus();
});

// ---------- Settings ----------
function openSettings() {
  els.keyInput.value = apiKey;
  els.keyInput.type = "password";
  $("#toggle-key").textContent = "Show";
  if (!els.settings.open) els.settings.showModal();
  els.keyInput.focus();
}

$("#toggle-key").addEventListener("click", () => {
  const show = els.keyInput.type === "password";
  els.keyInput.type = show ? "text" : "password";
  $("#toggle-key").textContent = show ? "Hide" : "Show";
});
els.keyInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); els.settings.close("save"); }
});
els.settings.addEventListener("close", async () => {
  if (els.settings.returnValue !== "save") return;
  apiKey = els.keyInput.value.trim();
  keyStore.set(apiKey);
  state.docsKey = "";
  await refreshDocs();
  if (els.conn.dataset.state === "on") toast("Connected");
});

// ---------- Library panel (narrow screens) ----------
function setLibrary(open) {
  els.library.classList.toggle("open", open);
  document.body.classList.toggle("library-open", open);
}
$("#open-library").addEventListener("click", () => setLibrary(true));
$("#close-library").addEventListener("click", () => setLibrary(false));
$("#scrim").addEventListener("click", () => setLibrary(false));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") setLibrary(false); });

// ---------- Start ----------
showIntro();
autosize();
refreshDocs();
