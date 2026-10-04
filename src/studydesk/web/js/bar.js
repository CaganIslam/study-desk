// The input bar: one box for questions and commands (⌘K or / to focus).
import { api } from "./api.js";
import { escapeHtml as esc, highlightCode, renderMarkdown } from "./render.js";
import { t } from "./strings.js";
import { page } from "./context.js";

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
    const result = await api.post("/api/command", { text, ...(page()?.payload() ?? {}) });
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
    case "live":
      location.hash = "#/live";
      return;
    case "none":
      show(`<p class="muted">${esc(t("bar.no_course"))}</p>`);
      return;
    case "today_summary":
      show(summaryHtml(action.sessions));
      return;
    case "search":
      show(searchHtml(action.query, action.results));
      return;
    default:
      if (!page()?.handleAction) show(`<p class="muted">${esc(t("bar.not_here"))}</p>`);
      else await page().handleAction(action);
  }
}

async function answer(result) {
  if (page()?.showAnswer) {
    await page().showAnswer(result.answer, result.idx);
    return;
  }
  show(`<strong>${esc(t("bar.answer_title"))}</strong><div class="md">${renderMarkdown(result.answer.answer_md)}</div>`);
}

const hhmm = (iso) => new Date(iso).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });

function summaryHtml(sessions) {
  if (!sessions.length) return `<p class="muted">${esc(t("summary.none"))}</p>`;
  return `<strong>${esc(t("summary.title"))}</strong><ul class="plain">${sessions
    .map((s) => {
      const line = t("summary.session", {
        course: s.course,
        start: hhmm(s.start),
        end: hhmm(s.end),
        minutes: s.minutes,
        slides: s.slides.length,
      });
      const extra = s.questions.length ? ` · ${t("summary.questions", { n: s.questions.length })}` : "";
      const titles = s.slides.slice(0, 6).map((x) => x.title).join(", ");
      return `<li>${esc(line + extra)}<br><span class="muted">${esc(titles)}${s.slides.length > 6 ? "…" : ""}</span></li>`;
    })
    .join("")}</ul>`;
}

function searchHtml(query, results) {
  if (!results.length) return `<p class="muted">${esc(t("search.none", { q: query }))}</p>`;
  return `<strong>${esc(t("search.title", { q: query }))}</strong><ul class="plain">${results
    .map(
      (r) => `<li><a href="#/deck/${r.deck_id}/${r.idx}">${esc(r.course_code)} · ${esc(r.label)}. ${esc(r.title)}</a>
        <span class="muted">(${esc(t(`search.kind.${r.kind}`))})</span><br><span class="muted">${esc(r.snippet)}</span></li>`,
    )
    .join("")}</ul>`;
}

function show(html) {
  output.innerHTML = html;
  output.hidden = false;
  highlightCode(output);
}
