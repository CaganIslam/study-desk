import { api, enc } from "./api.js";
import { escapeHtml as esc } from "./render.js";
import { t } from "./strings.js";

export async function showCourse(view, crumbs, code) {
  const [data, last] = await Promise.all([
    api.get(`/api/courses/${enc(code)}/decks`),
    api.get(`/api/resume?course=${enc(code)}`),
  ]);
  crumbs.innerHTML = `<span>${esc(data.code)}</span>`;
  const resume = last.resume
    ? `<p class="resume">${esc(t("course.resume", { deck: last.resume.deck, label: last.resume.label }))}
        <a class="button primary" href="#/deck/${last.resume.deck_id}/${last.resume.idx}">${esc(t("course.continue"))}</a></p>`
    : "";
  if (!data.decks.length) {
    view.innerHTML = `<p class="muted">${esc(t("course.no_decks"))}</p>`;
    return;
  }
  view.innerHTML = `
    ${resume}
    <h2>${esc(t("course.decks"))}</h2>
    <ul class="list">
      ${data.decks
        .map(
          (d) => `<li><a href="#/deck/${d.id}/1">${esc(d.filename.replace(/\.pdf$/i, ""))}</a>
            <span class="muted">${esc(t("course.slides", { n: d.slides }))}</span></li>`,
        )
        .join("")}
    </ul>`;
}
