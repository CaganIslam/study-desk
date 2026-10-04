// Live mode: follow the lecture as it happens. Opens the class running now (or a chosen course),
// its newest deck, or a questions-only page when the deck is not on Moodle yet.
import { api, enc } from "./api.js";
import { clearPage, setPage } from "./context.js";
import { escapeHtml as esc, highlightCode, renderMarkdown } from "./render.js";
import { t } from "./strings.js";

export async function showLive(view, crumbs, course = null) {
  const target = await api.get(`/api/live${course ? `?course=${enc(course)}` : ""}`);
  if (target.course && target.deck_id) {
    location.replace(`#/live/${target.deck_id}/${target.idx}`);
    return;
  }
  if (target.course) {
    location.replace(`#/live/course/${enc(target.course)}`);
    return;
  }
  const { courses } = await api.get("/api/courses");
  crumbs.innerHTML = `<span class="live-badge">${esc(t("live.badge"))}</span>`;
  view.innerHTML = `
    <h2>${esc(t("live.title"))}</h2>
    <p class="muted">${esc(t("live.no_class"))}</p>
    <ul class="cards">${courses
      .map((c) => `<li><a class="card" href="#/live/pick/${enc(c.code)}"><strong>${esc(c.code)}</strong><span>${esc(c.name)}</span></a></li>`)
      .join("")}</ul>`;
}

let deckless = null;

export function leaveDeckless() {
  if (deckless) clearPage(deckless.page);
  if (deckless) clearInterval(deckless.poll);
  deckless = null;
}

export async function showDeckless(view, crumbs, code) {
  crumbs.innerHTML = `<span class="live-badge">${esc(t("live.badge"))}</span><a href="#/course/${enc(code)}">${esc(code)}</a>`;
  view.innerHTML = `
    <section class="deckless">
      <p id="live-news" class="live-news" hidden></p>
      <h2>${esc(t("live.deckless", { code }))}</h2>
      <p class="muted">${esc(t("live.deckless_hint"))}</p>
      <div id="deckless-qa" class="questions"></div>
    </section>`;
  const page = {
    payload: () => ({ course_code: code, live: true, level: "short" }),
    showAnswer: async () => load(),
    handleAction: null,
  };
  deckless = { page, poll: null };
  setPage(page);

  async function load() {
    const data = await api.get(`/api/courses/${enc(code)}/deckless`);
    const box = document.getElementById("deckless-qa");
    if (!box) return;
    box.innerHTML = data.questions.length
      ? data.questions
          .slice()
          .reverse()
          .map((q) => `<div class="qa"><p class="q">${esc(q.question)}</p><div class="md">${renderMarkdown(q.answer_md)}</div></div>`)
          .join("")
      : `<p class="muted">${esc(t("live.no_questions"))}</p>`;
    highlightCode(box);
  }

  // A deck uploaded during the class appears here.
  const known = new Set((await api.get(`/api/courses/${enc(code)}/decks`)).decks.map((d) => d.id));
  deckless.poll = setInterval(async () => {
    await api.post("/api/sync/moodle?live=true").catch(() => {});
    const data = await api.get(`/api/courses/${enc(code)}/decks`).catch(() => null);
    const fresh = data?.decks.filter((d) => !known.has(d.id)) ?? [];
    if (fresh.length) {
      const deck = fresh.at(-1);
      const news = document.getElementById("live-news");
      news.innerHTML = `${esc(t("live.new_deck", { name: deck.filename.replace(/\.pdf$/i, "") }))}
        <a class="button primary" href="#/live/${deck.id}/1">${esc(t("live.open_deck"))}</a>`;
      news.hidden = false;
    }
  }, 60_000);
  await load();
}
