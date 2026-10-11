// First-run setup and settings (#/setup): data folder, Moodle, courses, schedule, checks.
// Every step writes the files through /api/setup. A step that changes config.toml makes the
// server restart; the page waits until /api/health reports a new boot id.
import { api, enc } from "./api.js";
import { escapeHtml as esc } from "./render.js";
import { t } from "./strings.js";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const LECTURE_LANGUAGES = ["en", "tr"];

let view = null;
let state = null; // GET /api/setup
let rows = null; // course rows being edited (step 3)
let moodleList = null; // Moodle courses with suggestions, or an error code
let pdfs = {}; // code -> PDFs of the course
let drafts = {}; // code -> schedule form being edited
let busy = {}; // which buttons are waiting
let notices = {}; // step -> {kind: "error" | "ok", text}
let tools = null;
let claude = null;
let browser = null; // folder browser listing, when open
let values = {}; // what was typed into the kept inputs, so a re-render does not lose it

const kept = (id, fallback) => values[id] ?? fallback ?? "";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function message(error) {
  if (error.code === "config_invalid") return t("setup.invalid", { error: error.message });
  const key = `error.${error.code}`;
  return t(key) === key ? error.message || t("error.generic") : t(key);
}

function notice(step) {
  const n = notices[step];
  return n ? `<p class="${n.kind === "error" ? "error" : "ok-text"}">${esc(n.text)}</p>` : "";
}

async function reload() {
  state = await api.get("/api/setup");
}

/** Wait until the server answers with a new boot id (it restarts after config.toml changes). */
async function waitForRestart(oldBoot) {
  const until = Date.now() + 30000;
  while (Date.now() < until) {
    await sleep(600);
    try {
      const health = await api.get("/api/health");
      if (health.boot !== oldBoot) return true;
    } catch {
      // the server is between the old and the new process
    }
  }
  return false;
}

async function act(step, key, fn) {
  busy[key] = true;
  notices[step] = null;
  render();
  try {
    await fn();
  } catch (error) {
    notices[step] = { kind: "error", text: message(error) };
  } finally {
    busy[key] = false;
    render();
  }
}

async function restarted(result) {
  if (!result.restart) {
    notices.folder = { kind: "error", text: t("setup.restart_manual") };
    return;
  }
  if (!(await waitForRestart(result.boot))) notices.folder = { kind: "error", text: t("setup.restart_timeout") };
}

export async function showSetup(target, crumbs) {
  view = target;
  crumbs.textContent = "";
  rows = null;
  moodleList = null;
  drafts = {};
  pdfs = {};
  notices = {};
  browser = null;
  values = {};
  await reload();
  render();
  if (state.moodle.url && state.moodle.token_saved && state.folder.exists) loadMoodleCourses();
  loadTools();
}

// --- rendering ------------------------------------------------------------------

function step(id, number, title, done, locked, body) {
  return `<section class="setup-step${locked ? " locked" : ""}" id="step-${id}">
    <h3><span class="num">${number}</span> ${esc(title)} ${done ? `<span class="done">✓</span>` : ""}</h3>
    ${locked ? `<p class="muted">${esc(t("setup.locked"))}</p>` : body}
  </section>`;
}

function render() {
  if (!view || !state) return;
  const focused = document.activeElement?.id;
  const firstRun = !state.complete;
  view.innerHTML = `<div class="setup">
    <h2>${esc(t(firstRun ? "setup.title_first" : "setup.title"))}</h2>
    <p class="muted">${esc(t(firstRun ? "setup.intro_first" : "setup.intro"))}</p>
    ${state.catalog_error ? `<p class="error">${esc(t("setup.catalog_error", { error: state.catalog_error }))}</p>` : ""}
    ${
      state.restart_pending
        ? `<p class="setup-warning">${esc(t("setup.restart_pending"))} <button id="restart-now">${esc(t("setup.restart_now"))}</button></p>`
        : ""
    }
    ${step("folder", 1, t("setup.folder.title"), state.folder.exists, false, folderStep())}
    ${step("moodle", 2, t("setup.moodle.title"), Boolean(state.moodle.url && state.moodle.token_saved), !state.folder.exists, moodleStep())}
    ${step("courses", 3, t("setup.courses.title"), state.courses.length > 0, !state.folder.exists, coursesStep())}
    ${step("schedule", 4, t("setup.schedule.title"), state.courses.some((c) => c.slots.length), !state.courses.length, scheduleStep())}
    ${step("checks", 5, t("setup.checks.title"), claude?.ok && tools?.ffmpeg && tools?.whisper, false, checksStep())}
    <section class="setup-finish">
      ${
        state.complete
          ? `<a class="button primary" href="#/">${esc(t("setup.finish"))}</a>`
          : `<p class="muted">${esc(t("setup.finish_needs"))}</p>`
      }
    </section>
  </div>`;
  wire();
  if (focused) document.getElementById(focused)?.focus();
}

function folderStep() {
  const f = state.folder;
  const language = kept("folder-language", f.language);
  const options = f.languages
    .map((l) => `<option value="${esc(l.code)}"${l.code === language ? " selected" : ""}>${esc(t(`setup.lang.${l.code}`) === `setup.lang.${l.code}` ? l.name : t(`setup.lang.${l.code}`))}</option>`)
    .join("");
  const listing = browser
    ? `<div class="folder-browser">
        <div class="folder-head"><code>${esc(browser.path)}</code>
          ${browser.parent ? `<button data-dir="${esc(browser.parent)}">↑ ${esc(t("setup.folder.up"))}</button>` : ""}
          <button class="primary" id="folder-pick">${esc(t("setup.folder.pick_this"))}</button></div>
        <ul class="plain dirs">${
          browser.dirs.length
            ? browser.dirs.map((d) => `<li><button class="link" data-dir="${esc(`${browser.path}/${d}`)}">📁 ${esc(d)}</button></li>`).join("")
            : `<li class="muted">${esc(t("setup.folder.empty"))}</li>`
        }</ul>
      </div>`
    : "";
  return `
    <p>${esc(t("setup.folder.help"))}</p>
    <div class="setup-row">
      <input id="folder-path" data-keep class="wide" value="${esc(kept("folder-path", f.data_root ?? f.suggested))}" spellcheck="false">
      <button id="folder-browse">${esc(t(browser ? "setup.folder.close" : "setup.folder.browse"))}</button>
    </div>
    ${listing}
    <p class="muted small">${esc(t(f.icloud ? "setup.folder.icloud" : "setup.folder.note"))}</p>
    <label class="setup-label">${esc(t("setup.folder.language"))} <select id="folder-language" data-keep>${options}</select></label>
    <p class="muted small">${esc(t("setup.folder.language_help"))}</p>
    <button class="primary" id="folder-save"${busy.folder ? " disabled" : ""}>${esc(t(busy.folder ? "setup.saving" : "setup.save"))}</button>
    ${notice("folder")}`;
}

function moodleStep() {
  const m = state.moodle;
  const connected = m.url && m.token_saved;
  return `
    <p>${esc(t("setup.moodle.help"))}</p>
    ${connected ? `<p class="ok-text">${esc(t("setup.moodle.connected", { url: m.url }))}</p>` : ""}
    <label class="setup-label">${esc(t("setup.moodle.url"))}
      <input id="moodle-url" data-keep class="wide" value="${esc(kept("moodle-url", m.url ?? ""))}" placeholder="https://moodle.okulun.edu.tr" spellcheck="false"></label>
    <label class="setup-label">${esc(t("setup.moodle.token"))}
      <input id="moodle-token" data-keep class="wide" type="password" autocomplete="off" value="${esc(kept("moodle-token", ""))}" placeholder="${esc(t(m.token_saved ? "setup.moodle.token_saved" : "setup.moodle.token_placeholder"))}"></label>
    <details class="howto"><summary>${esc(t("setup.moodle.howto"))}</summary>
      <ol>${["1", "2", "3", "4"].map((n) => `<li>${esc(t(`setup.moodle.howto${n}`))}</li>`).join("")}</ol>
      <p class="muted small">${esc(t("setup.moodle.howto_missing"))}</p>
      <p class="muted small">${esc(t("setup.moodle.howto_disabled"))}</p>
    </details>
    <div class="setup-row">
      <button class="primary" id="moodle-connect"${busy.moodle ? " disabled" : ""}>${esc(t(busy.moodle ? "setup.moodle.connecting" : "setup.moodle.connect"))}</button>
      ${m.url ? `<button id="moodle-remove">${esc(t("setup.moodle.remove"))}</button>` : `<span class="muted small">${esc(t("setup.moodle.optional"))}</span>`}
    </div>
    ${notice("moodle")}`;
}

function buildRows() {
  const configured = state.courses.map((c) => ({
    moodle_id: c.moodle_id ?? null,
    checked: true,
    code: c.code,
    name: c.name,
    folder: c.folder,
    aliases: c.aliases.join(", "),
    language: c.language || "en",
    label: c.moodle_id ? null : c.name,
    current: true,
    saved: true,
  }));
  const list = Array.isArray(moodleList) ? moodleList : [];
  for (const m of list) {
    const existing = configured.find((r) => r.moodle_id === m.id);
    if (existing) {
      existing.label = m.fullname;
      existing.shortname = m.shortname;
      continue;
    }
    configured.push({
      moodle_id: m.id,
      checked: false,
      code: m.suggested.code,
      name: m.suggested.name,
      folder: m.suggested.folder,
      aliases: m.suggested.aliases.join(", "),
      language: "en",
      label: m.fullname,
      shortname: m.shortname,
      current: m.current,
    });
  }
  return configured;
}

function courseRow(row, i) {
  const fields = row.checked
    ? `<div class="course-fields">
        <label>${esc(t("setup.courses.code"))}<input data-row="${i}" data-field="code" value="${esc(row.code)}"></label>
        <label>${esc(t("setup.courses.name"))}<input data-row="${i}" data-field="name" value="${esc(row.name)}"></label>
        <label>${esc(t("setup.courses.folder"))}<input data-row="${i}" data-field="folder" value="${esc(row.folder)}"></label>
        <label>${esc(t("setup.courses.aliases"))}<input data-row="${i}" data-field="aliases" value="${esc(row.aliases)}" placeholder="580, logic"></label>
        <label>${esc(t("setup.courses.lecture_language"))}<select data-row="${i}" data-field="language">${LECTURE_LANGUAGES.map(
          (l) => `<option value="${l}"${l === row.language ? " selected" : ""}>${esc(t(`setup.lang.${l}`))}</option>`,
        ).join("")}</select></label>
      </div>`
    : "";
  const title = row.moodle_id
    ? `${esc(row.label ?? row.name)} <span class="muted small">${esc(row.shortname ?? "")}</span>${row.current ? "" : ` <span class="pill">${esc(t("setup.courses.old"))}</span>`}`
    : `${esc(row.label || row.name || t("setup.courses.new"))} <span class="pill">${esc(t("setup.courses.manual"))}</span>`;
  const removal = row.saved && !row.checked ? `<span class="error small"> ${esc(t("setup.courses.will_remove"))}</span>` : "";
  return `<li class="course-row${row.checked ? " checked" : ""}">
    <label class="course-check"><input type="checkbox" data-row="${i}" data-field="checked"${row.checked ? " checked" : ""}> ${title}</label>${removal}
    ${fields}
  </li>`;
}

function coursesStep() {
  if (!rows) rows = buildRows();
  const moodleNote = !state.moodle.url
    ? t("setup.courses.no_moodle")
    : moodleList === null
      ? t("setup.courses.loading")
      : typeof moodleList === "string"
        ? t(`error.${moodleList}`) === `error.${moodleList}` ? t("error.generic") : t(`error.${moodleList}`)
        : t("setup.courses.from_moodle");
  return `
    <p>${esc(t("setup.courses.help"))}</p>
    <p class="muted small">${esc(moodleNote)}</p>
    <ul class="plain course-rows">${rows.map(courseRow).join("")}</ul>
    <div class="setup-row">
      <button id="course-add">+ ${esc(t("setup.courses.add"))}</button>
      <button class="primary" id="courses-save"${busy.courses ? " disabled" : ""}>${esc(t(busy.courses ? "setup.saving" : "setup.courses.save"))}</button>
    </div>
    ${notice("courses")}`;
}

function summary(course) {
  if (!course.slots.length && !course.exams.length && !course.topics.length) return t("setup.schedule.empty");
  return t("setup.schedule.summary", { slots: course.slots.length, exams: course.exams.length, topics: course.topics.length });
}

function slotText(s) {
  return `${t(`day.${s.day}`)} ${s.start}-${s.end}${s.kind && s.kind !== "lecture" ? ` (${s.kind})` : ""}`;
}

function draftForm(code, d) {
  const dayOptions = (value) => DAYS.map((day) => `<option value="${day}"${day === value ? " selected" : ""}>${esc(t(`day.${day}`))}</option>`).join("");
  const input = (kind, i, field, value, type = "text") =>
    `<input type="${type}" data-code="${esc(code)}" data-kind="${kind}" data-i="${i}" data-field="${field}" value="${esc(value ?? "")}">`;
  const remove = (kind, i) => `<button class="link" data-code="${esc(code)}" data-remove="${kind}" data-i="${i}" title="${esc(t("setup.schedule.remove"))}">✕</button>`;
  const slots = d.slots
    .map(
      (s, i) => `<tr><td><select data-code="${esc(code)}" data-kind="slots" data-i="${i}" data-field="day">${dayOptions(s.day)}</select></td>
        <td>${input("slots", i, "start", s.start, "time")}</td><td>${input("slots", i, "end", s.end, "time")}</td>
        <td>${input("slots", i, "kind", s.kind)}</td><td>${input("slots", i, "location", s.location)}</td><td>${remove("slots", i)}</td></tr>`,
    )
    .join("");
  const exams = d.exams
    .map(
      (e, i) => `<tr><td>${input("exams", i, "date", e.date, "date")}</td><td>${input("exams", i, "title", e.title)}</td>
        <td>${input("exams", i, "start", e.start, "time")}</td><td>${remove("exams", i)}</td></tr>`,
    )
    .join("");
  const topics = d.topics
    .map((tp, i) => `<tr><td>${input("topics", i, "week_of", tp.week_of, "date")}</td><td class="grow">${input("topics", i, "title", tp.title)}</td><td>${remove("topics", i)}</td></tr>`)
    .join("");
  const warn = d.notes || d.hours_inferred ? `<p class="setup-warning">${esc([d.hours_inferred ? t("setup.schedule.hours_inferred") : "", d.notes].filter(Boolean).join(" "))}</p>` : "";
  return `<div class="schedule-form">
    ${warn}
    <h4>${esc(t("setup.schedule.slots"))}</h4>
    <table class="setup-table"><thead><tr><th>${esc(t("setup.schedule.day"))}</th><th>${esc(t("setup.schedule.start"))}</th><th>${esc(t("setup.schedule.end"))}</th><th>${esc(t("setup.schedule.kind"))}</th><th>${esc(t("setup.schedule.location"))}</th><th></th></tr></thead><tbody>${slots}</tbody></table>
    <button class="link" data-code="${esc(code)}" data-add="slots">+ ${esc(t("setup.schedule.add_slot"))}</button>
    <h4>${esc(t("setup.schedule.exams"))}</h4>
    <table class="setup-table"><thead><tr><th>${esc(t("setup.schedule.date"))}</th><th>${esc(t("setup.schedule.exam_title"))}</th><th>${esc(t("setup.schedule.start"))}</th><th></th></tr></thead><tbody>${exams}</tbody></table>
    <button class="link" data-code="${esc(code)}" data-add="exams">+ ${esc(t("setup.schedule.add_exam"))}</button>
    <h4>${esc(t("setup.schedule.topics"))}</h4>
    <table class="setup-table"><thead><tr><th>${esc(t("setup.schedule.week_of"))}</th><th>${esc(t("setup.schedule.topic"))}</th><th></th></tr></thead><tbody>${topics}</tbody></table>
    <button class="link" data-code="${esc(code)}" data-add="topics">+ ${esc(t("setup.schedule.add_topic"))}</button>
    <div class="setup-row">
      <button class="primary" data-code="${esc(code)}" data-schedule-save${busy[`save:${code}`] ? " disabled" : ""}>${esc(t("setup.save"))}</button>
      <button data-code="${esc(code)}" data-schedule-cancel>${esc(t("setup.cancel"))}</button>
    </div>
  </div>`;
}

function scheduleCard(course) {
  const code = course.code;
  const files = pdfs[code];
  const fileOptions = files?.length
    ? files.map((f) => `<option value="${esc(f.file)}"${f.file === (course.syllabus ?? "") || (!course.syllabus && f.syllabus) ? " selected" : ""}>${esc(f.file)}</option>`).join("")
    : "";
  const reading = busy[`propose:${code}`];
  const controls = files == null
    ? `<p class="muted small">${esc(t("setup.loading"))}</p>`
    : `<div class="setup-row">
        ${files.length ? `<select data-code="${esc(code)}" class="syllabus-pick">${fileOptions}</select>
        <button class="primary" data-code="${esc(code)}" data-propose${reading ? " disabled" : ""}>${esc(t(reading ? "setup.schedule.reading" : "setup.schedule.read"))}</button>` : `<span class="muted small">${esc(t("setup.schedule.no_pdf"))}</span>`}
        <button data-code="${esc(code)}" data-upload>${esc(t("setup.schedule.upload"))}</button>
        <button data-code="${esc(code)}" data-manual>${esc(t("setup.schedule.manual"))}</button>
        <button class="link" data-code="${esc(code)}" data-reveal>${esc(t("setup.schedule.reveal"))}</button>
      </div>`;
  const current = course.slots.length ? `<p class="small">${esc(course.slots.map(slotText).join(" · "))}</p>` : "";
  return `<li class="schedule-card">
    <div class="schedule-head"><strong>${esc(code)}</strong> ${esc(course.name)} <span class="muted small">· ${esc(summary(course))}</span></div>
    ${current}
    ${controls}
    ${drafts[code] ? draftForm(code, drafts[code]) : ""}
    ${notice(`schedule:${code}`)}
  </li>`;
}

function scheduleStep() {
  for (const course of state.courses) if (pdfs[course.code] === undefined) loadPdfs(course.code);
  return `
    <p>${esc(t("setup.schedule.help"))}</p>
    <ul class="plain schedule-cards">${state.courses.map(scheduleCard).join("")}</ul>
    <div class="setup-row term-row">
      <label class="setup-label">${esc(t("setup.schedule.term_end"))} <input id="term-end" data-keep type="date" value="${esc(kept("term-end", state.catalog.term_end ?? ""))}"></label>
      <label class="setup-label">${esc(t("setup.schedule.timezone"))} <input id="term-tz" data-keep value="${esc(kept("term-tz", state.catalog.timezone))}" spellcheck="false"></label>
      <button id="term-save">${esc(t("setup.save"))}</button>
    </div>
    ${notice("term")}`;
}

function checksStep() {
  const claudeLine = claude
    ? claude.ok
      ? `<p class="ok-text">✓ ${esc(t("setup.checks.claude_ok"))}</p>`
      : `<p class="error">✗ ${esc(t(`setup.checks.claude_${claude.code}`) === `setup.checks.claude_${claude.code}` ? claude.message : t(`setup.checks.claude_${claude.code}`))}</p>`
    : "";
  const tool = (ok, label, fix) => `<li>${ok ? "✓" : "✗"} ${esc(t(label))}${ok ? "" : ` <span class="muted small">${esc(t(fix))}</span>`}</li>`;
  const toolList = tools
    ? `<ul class="plain checks">
        ${tool(tools.ffmpeg, "setup.checks.ffmpeg", "setup.checks.ffmpeg_fix")}
        ${tool(tools.whisper, "setup.checks.whisper", "setup.checks.whisper_fix")}
        ${tool(tools.whisper_model, "setup.checks.model", "setup.checks.model_fix")}
      </ul>`
    : `<p class="muted small">${esc(t("setup.loading"))}</p>`;
  return `
    <h4>Claude Code</h4>
    <p class="muted small">${esc(t("setup.checks.claude_help"))}</p>
    <button id="check-claude"${busy.claude ? " disabled" : ""}>${esc(t(busy.claude ? "setup.checks.checking" : "setup.checks.check"))}</button>
    ${claudeLine}
    <h4>${esc(t("setup.checks.recordings"))}</h4>
    <p class="muted small">${esc(t("setup.checks.recordings_help"))}</p>
    ${toolList}`;
}

// --- loading -------------------------------------------------------------------

async function loadMoodleCourses() {
  try {
    moodleList = (await api.get("/api/setup/moodle/courses")).courses;
  } catch (error) {
    moodleList = error.code ?? "generic";
  }
  rows = null;
  render();
}

async function loadPdfs(code) {
  pdfs[code] = null; // loading
  try {
    pdfs[code] = (await api.get(`/api/setup/courses/${enc(code)}/pdfs`)).pdfs;
  } catch {
    pdfs[code] = [];
  }
  render();
}

async function loadTools() {
  try {
    tools = await api.get("/api/setup/check/tools");
  } catch {
    tools = { ffmpeg: false, whisper: false, whisper_model: false };
  }
  render();
}

async function waitForSync() {
  for (let i = 0; i < 300; i += 1) {
    const sync = await api.get("/api/sync/moodle");
    if (!sync.running) return sync;
    await sleep(1000);
  }
  return null;
}

// --- events ------------------------------------------------------------------------

function readRows() {
  for (const el of view.querySelectorAll("[data-row]")) {
    const row = rows[Number(el.dataset.row)];
    if (el.dataset.field === "checked") row.checked = el.checked;
    else row[el.dataset.field] = el.value;
  }
}

function readDrafts() {
  for (const el of view.querySelectorAll("[data-kind][data-code]")) {
    const d = drafts[el.dataset.code];
    if (d) d[el.dataset.kind][Number(el.dataset.i)][el.dataset.field] = el.value;
  }
}

function draftFrom(course) {
  const copy = (list) => list.map((x) => ({ ...x }));
  return {
    slots: copy(course.slots).map((s) => ({ kind: "lecture", location: "", ...s })),
    exams: copy(course.exams).map((e) => ({ start: "", ...e })),
    topics: copy(course.topics),
    notes: "",
    hours_inferred: false,
    term_end: "",
  };
}

function wire() {
  const on = (id, fn) => document.getElementById(id)?.addEventListener("click", fn);
  for (const el of view.querySelectorAll("[data-keep]")) {
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
      values[el.id] = el.value;
    });
  }

  on("restart-now", () =>
    act("folder", "restart", async () => {
      const result = await api.post("/api/setup/restart");
      await restarted(result);
      await reload();
    }),
  );

  // step 1
  on("folder-browse", async () => {
    if (browser) {
      browser = null;
      return render();
    }
    try {
      browser = await api.get(`/api/setup/dirs?path=${enc(document.getElementById("folder-path").value || "~")}`);
    } catch {
      browser = await api.get("/api/setup/dirs");
    }
    render();
  });
  for (const el of view.querySelectorAll("[data-dir]")) {
    el.addEventListener("click", async () => {
      browser = await api.get(`/api/setup/dirs?path=${enc(el.dataset.dir)}`);
      render();
    });
  }
  on("folder-pick", () => {
    values["folder-path"] = browser.path;
    browser = null;
    render();
    document.getElementById("folder-path").value = values["folder-path"];
  });
  on("folder-save", () => {
    const data_root = document.getElementById("folder-path").value;
    const language = document.getElementById("folder-language").value;
    act("folder", "folder", async () => {
      const result = await api.post("/api/setup/folder", { data_root, language });
      await restarted(result);
      await reload();
      rows = null;
      delete values["folder-path"];
      delete values["folder-language"];
      if (!notices.folder) notices.folder = { kind: "ok", text: t("setup.saved") };
    });
  });

  // step 2
  on("moodle-connect", () => {
    const url = document.getElementById("moodle-url").value;
    const token = document.getElementById("moodle-token").value;
    act("moodle", "moodle", async () => {
      const result = await api.post("/api/setup/moodle", { url, token });
      if (result.restart) await waitForRestart(result.boot);
      await reload();
      notices.moodle = { kind: "ok", text: t("setup.moodle.ok", { site: result.site, user: result.user }) };
      delete values["moodle-token"];
      delete values["moodle-url"];
      moodleList = null;
      rows = null;
      loadMoodleCourses();
    });
  });
  on("moodle-remove", () =>
    act("moodle", "moodle", async () => {
      const result = await api.del("/api/setup/moodle");
      if (result.restart) await waitForRestart(result.boot);
      await reload();
      moodleList = null;
      rows = null;
    }),
  );

  // step 3
  for (const el of view.querySelectorAll("[data-row]")) {
    el.addEventListener(el.type === "checkbox" ? "change" : "input", () => {
      readRows();
      if (el.type === "checkbox") render();
    });
  }
  on("course-add", () => {
    readRows();
    rows.push({ moodle_id: null, checked: true, code: "", name: "", folder: "", aliases: "", language: "en", label: "", current: true });
    render();
  });
  on("courses-save", () => {
    readRows();
    const courses = rows
      .filter((r) => r.checked)
      .map((r) => ({
        code: r.code.trim(),
        name: r.name.trim(),
        folder: r.folder.trim(),
        aliases: r.aliases.split(",").map((a) => a.trim()).filter(Boolean),
        language: r.language,
        moodle_id: r.moodle_id,
      }));
    act("courses", "courses", async () => {
      state = { ...(await api.post("/api/setup/courses", { courses })), restart_pending: state.restart_pending };
      rows = null;
      pdfs = {};
      if (state.moodle.url && courses.some((c) => c.moodle_id)) {
        notices.courses = { kind: "ok", text: t("setup.courses.syncing") };
        render();
        await api.post("/api/sync/moodle?force=true");
        const sync = await waitForSync();
        const n = sync?.last_result?.new?.length ?? 0;
        notices.courses = { kind: "ok", text: t("setup.courses.synced", { n }) };
        pdfs = {};
      } else {
        notices.courses = { kind: "ok", text: t("setup.saved") };
      }
    });
  });

  // step 4
  for (const el of view.querySelectorAll("[data-kind][data-code]")) el.addEventListener("input", readDrafts);
  for (const el of view.querySelectorAll("[data-propose]")) {
    el.addEventListener("click", () => {
      const code = el.dataset.code;
      const file = view.querySelector(`.syllabus-pick[data-code="${CSS.escape(code)}"]`)?.value;
      if (!file) return;
      act(`schedule:${code}`, `propose:${code}`, async () => {
        const result = await api.post(`/api/setup/courses/${enc(code)}/schedule/propose`, { file });
        const course = state.courses.find((c) => c.code === code);
        drafts[code] = { ...draftFrom(course), ...result.proposal, syllabus: file };
        if (!result.proposal.slots.length && !result.proposal.exams.length && !result.proposal.topics.length) {
          notices[`schedule:${code}`] = { kind: "error", text: t("setup.schedule.nothing_found") };
        }
      });
    });
  }
  for (const el of view.querySelectorAll("[data-manual]")) {
    el.addEventListener("click", () => {
      const course = state.courses.find((c) => c.code === el.dataset.code);
      drafts[course.code] = draftFrom(course);
      render();
    });
  }
  for (const el of view.querySelectorAll("[data-upload]")) {
    el.addEventListener("click", () => {
      const code = el.dataset.code;
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".pdf,application/pdf";
      input.addEventListener("change", () => {
        const file = input.files[0];
        if (!file) return;
        act(`schedule:${code}`, `upload:${code}`, async () => {
          await api.upload(`/api/setup/courses/${enc(code)}/pdfs`, file);
          await loadPdfs(code);
        });
      });
      input.click();
    });
  }
  for (const el of view.querySelectorAll("[data-reveal]")) {
    el.addEventListener("click", () => api.post(`/api/setup/courses/${enc(el.dataset.code)}/reveal`).catch(() => {}));
  }
  for (const el of view.querySelectorAll("[data-add]")) {
    el.addEventListener("click", () => {
      readDrafts();
      const blank = { slots: { day: "mon", start: "09:00", end: "10:00", kind: "lecture", location: "" }, exams: { date: "", title: "", start: "" }, topics: { week_of: "", title: "" } };
      drafts[el.dataset.code][el.dataset.add].push({ ...blank[el.dataset.add] });
      render();
    });
  }
  for (const el of view.querySelectorAll("[data-remove]")) {
    el.addEventListener("click", () => {
      readDrafts();
      drafts[el.dataset.code][el.dataset.remove].splice(Number(el.dataset.i), 1);
      render();
    });
  }
  for (const el of view.querySelectorAll("[data-schedule-cancel]")) {
    el.addEventListener("click", () => {
      delete drafts[el.dataset.code];
      render();
    });
  }
  for (const el of view.querySelectorAll("[data-schedule-save]")) {
    el.addEventListener("click", () => {
      readDrafts();
      const code = el.dataset.code;
      const d = drafts[code];
      act(`schedule:${code}`, `save:${code}`, async () => {
        const body = {
          slots: d.slots,
          exams: d.exams.filter((e) => e.date),
          topics: d.topics.filter((tp) => tp.week_of && tp.title),
          syllabus: d.syllabus ?? null,
        };
        state = { ...(await api.put(`/api/setup/courses/${enc(code)}/schedule`, body)), restart_pending: state.restart_pending };
        if (d.term_end && !state.catalog.term_end) {
          state = { ...(await api.put("/api/setup/term", { term_end: d.term_end })), restart_pending: state.restart_pending };
        }
        delete drafts[code];
        notices[`schedule:${code}`] = { kind: "ok", text: t("setup.saved") };
      });
    });
  }
  on("term-save", () => {
    const term_end = document.getElementById("term-end").value || null;
    const timezone = document.getElementById("term-tz").value || null;
    act("term", "term", async () => {
      state = { ...(await api.put("/api/setup/term", { term_end, timezone })), restart_pending: state.restart_pending };
      notices.term = { kind: "ok", text: t("setup.saved") };
    });
  });

  // step 5
  on("check-claude", () =>
    act("checks", "claude", async () => {
      claude = await api.get("/api/setup/check/claude");
    }),
  );
}
