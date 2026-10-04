import { api, enc } from "./api.js";
import { escapeHtml as esc } from "./render.js";
import { t } from "./strings.js";

export async function showHome(view, crumbs) {
  crumbs.textContent = "";
  const [health, courses] = await Promise.all([api.get("/api/health"), api.get("/api/courses")]);
  if (!health.data_root_configured) {
    view.innerHTML = `<p class="muted">${esc(t("app.first_run"))}</p>`;
    return;
  }
  if (!courses.courses.length) {
    view.innerHTML = `<p class="muted">${esc(t("app.no_courses"))}</p>`;
    return;
  }
  view.innerHTML = `
    <h2>${esc(t("nav.courses"))}</h2>
    <ul class="cards">
      ${courses.courses
        .map(
          (c) => `<li><a class="card" href="#/course/${enc(c.code)}">
            <strong>${esc(c.code)}</strong><span>${esc(c.name)}</span></a></li>`,
        )
        .join("")}
    </ul>`;
}
