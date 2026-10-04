// The input bar: one box for questions and commands (⌘K or / to focus).
import { api } from "./api.js";
import { escapeHtml as esc, highlightCode, renderMarkdown } from "./render.js";
import { t } from "./strings.js";
import * as study from "./study.js";

const input = document.getElementById("bar-input");
const output = document.getElementById("bar-output");
let busy = false;

export function initBar() {
  input.disabled = false;
  input.placeholder = t("bar.placeholder");
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      submit();
    } else if (event.key === "Escape") {
      input.blur();
    }
  });
  document.addEventListener("keydown", (event) => {
    const typing = ["INPUT", "TEXTAREA"].includes(event.target.tagName);
    if ((event.metaKey && event.key.toLowerCase() === "k") || (!typing && event.key === "/")) {
      event.preventDefault();
      input.focus();
    }
  });
  window.addEventListener("hashchange", () => (output.hidden = true));
}

async function submit() {
  const text = input.value.trim();
  if (!text || busy) return;
  busy = true;
  const started = Date.now();
  const placeholder = input.placeholder;
  const tick = () => (input.placeholder = t("bar.thinking", { s: Math.round((Date.now() - started) / 1000) }));
  input.value = "";
  tick();
  const timer = setInterval(tick, 1000);
  input.disabled = true;
  try {
    const context = study.context();
    const result = await api.post("/api/command", { text, ...(context ?? {}) });
    if (result.kind === "action") await act(result.action);
    else await answer(result);
  } catch (error) {
    const key = `error.${error.code}`;
    show(`<p class="error">${esc(t(key) === key ? error.message || t("error.generic") : t(key))}</p>`);
    input.value = text;
  } finally {
    clearInterval(timer);
    input.placeholder = placeholder;
    input.disabled = false;
    busy = false;
    input.focus();
  }
}

async function act(action) {
  output.hidden = true;
  switch (action.type) {
    case "open":
      location.hash = action.deck_id ? `#/deck/${action.deck_id}/${action.idx || 1}` : `#/course/${encodeURIComponent(action.course)}`;
      return;
    case "home":
      location.hash = "#/";
      return;
    case "none":
      show(`<p class="muted">${esc(t("bar.no_course"))}</p>`);
      return;
    default:
      if (!study.context()) show(`<p class="muted">${esc(t("bar.not_here"))}</p>`);
      else await study.handleAction(action);
  }
}

async function answer(result) {
  if (study.context()) {
    await study.showAnswer(result.answer, result.idx);
    return;
  }
  show(`<strong>${esc(t("bar.answer_title"))}</strong><div class="md">${renderMarkdown(result.answer.answer_md)}</div>`);
}

function show(html) {
  output.innerHTML = html;
  output.hidden = false;
  highlightCode(output);
}
