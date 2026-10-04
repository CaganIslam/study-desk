// The study screen: one slide, its explanation, and the controls around it.
import { api, enc } from "./api.js";
import { escapeHtml as esc, highlightCode, renderMarkdown } from "./render.js";
import { t } from "./strings.js";

const LEVELS = ["short", "normal", "detailed"];
const VARIANTS = ["simpler", "example", "different", "formula"];

const storage = {
  get(key, fallback) {
    try {
      return localStorage.getItem(key) ?? fallback;
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* private mode: the setting just isn't remembered */
    }
  },
};

let state = null;
let keyHandler = null;
const $ = (id) => document.getElementById(id);

export function leaveStudy() {
  if (keyHandler) document.removeEventListener("keydown", keyHandler);
  keyHandler = null;
  if (state) clearInterval(state.timer);
  state = null;
}

export async function showStudy(view, crumbs, deckId, idx) {
  const listing = await api.get(`/api/decks/${deckId}/slides`);
  const code = listing.deck.code;
  state = { deckId, idx, listing, code, level: storage.get(`level:${code}`, "normal"), token: 0, timer: null };
  crumbs.innerHTML = `<a href="#/course/${enc(code)}">${esc(code)}</a><span class="sep">›</span><span>${esc(
    listing.deck.filename.replace(/\.pdf$/i, ""),
  )}</span>`;
  view.innerHTML = template();
  bind();
  keyHandler = onKey;
  document.addEventListener("keydown", keyHandler);
  await go(idx);
}

function template() {
  return `
  <section class="study">
    <div class="strip" id="strip"></div>
    <div class="panes">
      <div class="slide-pane">
        <img id="slide-img" alt="">
        <div class="nav">
          <button id="prev">◀ ${esc(t("study.prev"))}</button>
          <label class="pos" title="${esc(t("study.jump"))}">
            <input id="jump" inputmode="numeric" autocomplete="off"><span id="total"></span>
          </label>
          <button id="know" title="B">${esc(t("study.know"))} ⏭</button>
          <button id="next" class="primary" title="Space">${esc(t("study.next"))} ⏎</button>
        </div>
        <p id="known-flag" class="muted known-flag"></p>
      </div>
      <div class="explain-pane">
        <h2 id="slide-title"></h2>
        <div class="levels" role="group" aria-label="${esc(t("study.level"))}">
          ${LEVELS.map((l, i) => `<button data-level="${l}" title="${i + 1}">${esc(t(`study.level.${l}`))}</button>`).join("")}
        </div>
        <div id="explanation" class="explanation" aria-live="polite"></div>
        <div class="variants">
          ${VARIANTS.map((v) => `<button data-variant="${v}">${esc(t(`study.variant.${v}`))}</button>`).join("")}
        </div>
      </div>
    </div>
  </section>`;
}

function bind() {
  $("prev").onclick = () => go(state.idx - 1);
  $("next").onclick = next;
  $("know").onclick = knowAndSkip;
  $("jump").onkeydown = async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    try {
      const found = await api.get(`/api/decks/${state.deckId}/find?label=${enc($("jump").value)}`);
      await go(found.idx);
    } catch {
      $("jump").value = current().label;
    }
  };
  for (const button of document.querySelectorAll("[data-level]")) button.onclick = () => setLevel(button.dataset.level);
  for (const button of document.querySelectorAll("[data-variant]")) button.onclick = () => loadExplanation(button.dataset.variant);
}

const current = () => state.listing.slides[state.idx - 1];
const slideCount = () => state.listing.slides.length;

async function go(idx) {
  if (!state) return;
  state.idx = Math.min(Math.max(1, idx), slideCount());
  const slide = current();
  history.replaceState(null, "", `#/deck/${state.deckId}/${state.idx}`);
  $("slide-img").src = `/api/decks/${state.deckId}/slides/${state.idx}/image?size=view`;
  $("slide-img").alt = slide.title;
  $("slide-title").textContent = slide.title;
  $("jump").value = slide.label;
  $("total").textContent = ` / ${state.listing.slides.at(-1).label}`;
  $("prev").disabled = state.idx === 1;
  renderStrip();
  renderKnown();
  renderLevels();
  await loadExplanation();
}

function next() {
  if (state.idx < slideCount()) return go(state.idx + 1);
  $("explanation").insertAdjacentHTML("beforeend", `<p class="deck-end">${esc(t("study.deck_end"))}</p>`);
}

async function knowAndSkip() {
  const idx = state.idx;
  const result = await api.put(`/api/decks/${state.deckId}/slides/${idx}/marks/known`);
  state.listing.slides[idx - 1].marks = result.marks;
  if (idx < slideCount()) await go(idx + 1);
  else renderStrip();
}

async function unmarkKnown() {
  const result = await api.del(`/api/decks/${state.deckId}/slides/${state.idx}/marks/known`);
  current().marks = result.marks;
  renderKnown();
  renderStrip();
}

function setLevel(level) {
  if (!LEVELS.includes(level) || level === state.level) return;
  state.level = level;
  storage.set(`level:${state.code}`, level);
  renderLevels();
  loadExplanation();
}

function renderLevels() {
  for (const button of document.querySelectorAll("[data-level]")) {
    button.classList.toggle("active", button.dataset.level === state.level);
  }
}

function renderKnown() {
  const flag = $("known-flag");
  if (current().marks.includes("known")) {
    flag.innerHTML = `✓ ${esc(t("study.marked_known"))} · <a href="#" id="unmark">${esc(t("study.unmark"))}</a>`;
    $("unmark").onclick = (event) => {
      event.preventDefault();
      unmarkKnown();
    };
  } else {
    flag.textContent = "";
  }
}

function renderStrip() {
  const strip = $("strip");
  strip.innerHTML = state.listing.slides
    .map((s) => {
      const classes = ["chip"];
      if (s.idx === state.idx) classes.push("current");
      if (s.marks.includes("known")) classes.push("known");
      else if (s.explained) classes.push("explained");
      return `<button class="${classes.join(" ")}" data-idx="${s.idx}" title="${esc(s.title)}">${esc(s.label)}</button>`;
    })
    .join("");
  for (const chip of strip.querySelectorAll(".chip")) chip.onclick = () => go(Number(chip.dataset.idx));
  strip.querySelector(".current")?.scrollIntoView({ block: "nearest", inline: "center" });
}

async function loadExplanation(variant = null, refresh = false) {
  if (!state) return;
  const token = ++state.token;
  const { deckId, idx } = state;
  const box = $("explanation");
  const started = Date.now();
  const tick = () => {
    box.innerHTML = `<p class="muted loading">${esc(t("study.preparing", { s: Math.round((Date.now() - started) / 1000) }))}</p>`;
  };
  clearInterval(state.timer);
  const pending = setTimeout(tick, 150); // cached explanations arrive before anything flickers
  state.timer = setInterval(tick, 1000);
  try {
    const data = await api.post(`/api/decks/${deckId}/slides/${idx}/explain`, { level: state.level, variant, refresh });
    if (!state || token !== state.token) return;
    renderExplanation(data, variant);
    state.listing.slides[idx - 1].explained = true;
    renderStrip();
  } catch (error) {
    if (!state || token !== state.token) return;
    const key = `error.${error.code}`;
    const message = t(key) === key ? error.message || t("error.generic") : t(key);
    box.innerHTML = `<p class="error">${esc(message)}</p><button id="retry">${esc(t("study.retry"))}</button>`;
    $("retry").onclick = () => loadExplanation(variant, true);
  } finally {
    clearTimeout(pending);
    if (state && token === state.token) clearInterval(state.timer);
  }
}

function renderExplanation(data, variant) {
  const box = $("explanation");
  const parts = [];
  if (variant) {
    parts.push(
      `<p class="variant-tag">${esc(t(`study.variant.${variant}`))} · <a href="#" id="back-main">${esc(t("study.variant.back"))}</a></p>`,
    );
  }
  parts.push(`<div class="md">${renderMarkdown(data.explanation_md)}</div>`);
  if (data.exam_notes?.length) {
    parts.push(
      `<aside class="exam"><strong>${esc(t("study.exam_notes"))}</strong><ul>${data.exam_notes
        .map((n) => `<li>${renderMarkdown(n).replace(/^<p>|<\/p>\s*$/g, "")}</li>`)
        .join("")}</ul></aside>`,
    );
  }
  if (data.terms?.length) {
    parts.push(
      `<div class="terms"><strong>${esc(t("study.terms"))}</strong>${data.terms
        .map((term) => `<span class="term" title="${esc(`${term.definition_en}\n${term.meaning}`)}">${esc(term.term)}</span>`)
        .join("")}</div>`,
    );
  }
  if (data.idx === slideCount()) parts.push(`<p class="deck-end">${esc(t("study.deck_end"))}</p>`);
  box.innerHTML = parts.join("");
  highlightCode(box);
  const back = $("back-main");
  if (back) {
    back.onclick = (event) => {
      event.preventDefault();
      loadExplanation();
    };
  }
}

function onKey(event) {
  const typing = ["INPUT", "TEXTAREA"].includes(event.target.tagName);
  if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
  const actions = {
    " ": next,
    Enter: next,
    ArrowRight: next,
    ArrowLeft: () => go(state.idx - 1),
    b: knowAndSkip,
    d: () => loadExplanation("simpler"),
    1: () => setLevel("short"),
    2: () => setLevel("normal"),
    3: () => setLevel("detailed"),
  };
  const action = actions[event.key];
  if (action) {
    event.preventDefault();
    action();
  }
}
