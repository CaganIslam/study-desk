// The glossary: the term card (a dialog) and the terms page.
import { api, enc } from "./api.js";
import { escapeHtml as esc } from "./render.js";
import { t } from "./strings.js";

const STATUSES = ["new", "hard", "known"];
const dialog = document.getElementById("term-card");

function speak(text) {
  try {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    speechSynthesis.cancel();
    speechSynthesis.speak(utterance);
  } catch {
    /* no speech synthesis available */
  }
}

function cardHtml(card) {
  const seen = card.seen
    .map(
      (s) => `<li><a href="#/deck/${s.deck_id}/${s.idx}">${esc(s.course)} · ${esc(s.deck)} · ${esc(s.label)}. ${esc(s.title)}</a>
        <span class="muted">(${esc(t(`terms.source.${s.source}`))})</span></li>`,
    )
    .join("");
  return `
    <div class="card-head">
      <h2>${esc(card.term)}</h2>
      <button data-speak title="${esc(t("terms.speak"))}">🔊</button>
    </div>
    <p class="meaning">${esc(card.meaning)}</p>
    ${card.definition_en ? `<p><strong>${esc(t("terms.definition"))}:</strong> ${esc(card.definition_en)}</p>` : ""}
    ${card.example ? `<p><strong>${esc(t("terms.example"))}:</strong> ${esc(card.example)}</p>` : ""}
    <div class="status-row">${STATUSES.map(
      (s) => `<button data-status="${s}" class="${s === card.status ? "active" : ""}">${esc(t(`terms.status.${s}`))}</button>`,
    ).join("")}</div>
    ${seen ? `<h3>${esc(t("terms.seen"))}</h3><ul class="plain">${seen}</ul>` : ""}
    <form method="dialog"><button>${esc(t("terms.close"))}</button></form>`;
}

export async function openTerm({ id, name }) {
  const card = id ? await api.get(`/api/terms/${id}`) : await api.get(`/api/terms/lookup?term=${enc(name)}`);
  render(card);
  if (!dialog.open) dialog.showModal();
}

function render(card) {
  dialog.innerHTML = cardHtml(card);
  dialog.querySelector("[data-speak]").onclick = () => speak(card.term);
  for (const button of dialog.querySelectorAll("[data-status]")) {
    button.onclick = async () => {
      const updated = await fetch(`/api/terms/${card.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: button.dataset.status }),
      }).then((r) => r.json());
      render(updated);
      document.dispatchEvent(new CustomEvent("term-changed", { detail: updated }));
    };
  }
  for (const link of dialog.querySelectorAll("a")) link.addEventListener("click", () => dialog.close());
}

export async function showTerms(view, crumbs, course) {
  crumbs.innerHTML = course ? `<a href="#/course/${enc(course)}">${esc(course)}</a>` : "";
  let status = "";
  view.innerHTML = `
    <div class="terms-head">
      <h2>${esc(t("terms.title"))}${course ? ` · ${esc(course)}` : ""}</h2>
      <input id="term-filter" type="search" placeholder="${esc(t("terms.filter"))}">
    </div>
    <div class="status-row" id="term-status">
      <button data-filter="" class="active">${esc(t("terms.all"))}</button>
      ${STATUSES.map((s) => `<button data-filter="${s}">${esc(t(`terms.status.${s}`))}</button>`).join("")}
    </div>
    <p class="muted" id="term-count"></p>
    <ul class="term-list" id="term-list"></ul>`;
  const list = document.getElementById("term-list");
  const load = async () => {
    const query = document.getElementById("term-filter").value.trim();
    const params = new URLSearchParams();
    if (course) params.set("course", course);
    if (status) params.set("status", status);
    if (query) params.set("q", query);
    const data = await api.get(`/api/terms?${params}`);
    document.getElementById("term-count").textContent = data.terms.length ? t("terms.count", { n: data.terms.length }) : t("terms.none");
    list.innerHTML = data.terms
      .map(
        (term) => `<li><button class="term-row status-${term.status}" data-id="${term.id}">
          <strong>${esc(term.term)}</strong><span>${esc(term.meaning)}</span>
          <span class="pill">${esc(t(`terms.status.${term.status}`))}</span></button></li>`,
      )
      .join("");
    for (const row of list.querySelectorAll("[data-id]")) row.onclick = () => openTerm({ id: Number(row.dataset.id) });
  };
  document.getElementById("term-filter").oninput = load;
  for (const button of document.querySelectorAll("[data-filter]")) {
    button.onclick = () => {
      status = button.dataset.filter;
      for (const b of document.querySelectorAll("[data-filter]")) b.classList.toggle("active", b === button);
      load();
    };
  }
  document.addEventListener("term-changed", load);
  await load();
}
