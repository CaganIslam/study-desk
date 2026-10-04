// The Today screen: what is on now, where to continue, what is coming.
import { api, enc } from "./api.js";
import { escapeHtml as esc } from "./render.js";
import { t } from "./strings.js";

function ago(iso) {
  if (!iso) return null;
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 2) return t("time.just_now");
  if (minutes < 60) return t("time.minutes_ago", { n: minutes });
  if (minutes < 60 * 24) return t("time.hours_ago", { n: Math.round(minutes / 60) });
  return t("time.days_ago", { n: Math.round(minutes / 1440) });
}

const hhmm = (iso) => (iso ? new Date(iso).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : null);

function daysLeft(n) {
  if (n === 0) return t("today.today");
  if (n === 1) return t("today.tomorrow");
  return t("today.days_left", { n });
}

export async function showHome(view, crumbs) {
  crumbs.textContent = "";
  const health = await api.get("/api/health");
  if (!health.data_root_configured) {
    view.innerHTML = `<p class="muted">${esc(t("app.first_run"))}</p>`;
    return;
  }
  const [today, overview, sync] = await Promise.all([
    api.get("/api/today"),
    api.get("/api/overview"),
    api.get("/api/sync/moodle"),
  ]);
  if (!overview.courses.length) {
    view.innerHTML = `<p class="muted">${esc(t("app.no_courses"))}</p>`;
    return;
  }
  const stats = Object.fromEntries(overview.courses.map((c) => [c.code, c]));
  const dateTitle = new Date(`${today.date}T12:00:00`).toLocaleDateString("tr-TR", { weekday: "long", day: "numeric", month: "long" });

  const now = today.current
    ? `<section class="now">
        <span>${esc(t("today.now", { ...today.current, start: today.current.start, end: today.current.end }))}</span>
        <a class="button primary" href="#/live">${esc(t("today.go_live"))}</a>
      </section>`
    : "";

  const resume = overview.resume
    ? `<section class="continue"><a href="#/deck/${overview.resume.deck_id}/${overview.resume.idx}">
        <strong>${esc(t("today.continue"))} →</strong>
        <span class="muted">${esc(t("today.continue_detail", overview.resume))}</span></a></section>`
    : "";

  const classes = today.classes.length
    ? `<ul class="plain">${today.classes
        .map(
          (c) => `<li><a href="#/course/${enc(c.code)}">${esc(c.start)}-${esc(c.end)} · <strong>${esc(c.code)}</strong> ${esc(c.name)}</a>
            <span class="muted">${esc([c.kind !== "lecture" ? c.kind : "", c.location || "", c.topic || ""].filter(Boolean).join(" · "))}</span></li>`,
        )
        .join("")}</ul>`
    : `<p class="muted">${esc(t("today.no_classes"))}</p>`;

  const exams = today.exams.length
    ? `<ul class="plain">${today.exams
        .map((e) => {
          const s = stats[e.code] ?? {};
          const studied = s.last_studied ? t("today.last_studied", { when: ago(s.last_studied) }) : t("today.never_studied");
          const hard = s.hard_terms ? ` · ${t("today.hard_terms", { n: s.hard_terms })}` : "";
          return `<li><strong>${esc(e.code)}</strong> ${esc(e.title)} · ${esc(e.date)}${e.start ? ` ${esc(e.start)}` : ""}
            <span class="pill">${esc(daysLeft(e.days_left))}</span><br><span class="muted">${esc(studied + hard)}</span></li>`;
        })
        .join("")}</ul>`
    : `<p class="muted">${esc(t("today.no_exams"))}</p>`;

  const courses = `<ul class="cards">${overview.courses
    .map(
      (c) => `<li><a class="card" href="#/course/${enc(c.code)}"><strong>${esc(c.code)}</strong><span>${esc(c.name)}</span>
        <small class="muted">${esc(c.last_studied ? t("today.last_studied", { when: ago(c.last_studied) }) : t("today.never_studied"))}</small></a></li>`,
    )
    .join("")}</ul>`;

  const fresh = sync.last_result?.new?.length
    ? `<section><h3>${esc(t("today.new_files"))}</h3><ul class="plain">${sync.last_result.new
        .map((f) => `<li>${esc(f.replace("/", " · "))}</li>`)
        .join("")}</ul></section>`
    : "";

  view.innerHTML = `
    <div class="today">
      <h2>${esc(t("today.title"))} <span class="muted">· ${esc(dateTitle)}</span></h2>
      ${now}
      ${resume}
      <div class="today-grid">
        <section><h3>${esc(t("today.classes"))}</h3>${classes}</section>
        <section><h3>${esc(t("today.exams"))}</h3>${exams}</section>
      </div>
      <h3>${esc(t("today.courses"))}</h3>
      ${courses}
      ${fresh}
      <p class="muted small">${esc(
        t("today.footer", {
          minutes: overview.studied_minutes_today,
          sync: sync.last_sync ? hhmm(sync.last_sync) : t("today.never_synced"),
        }),
      )}</p>
    </div>`;
}
