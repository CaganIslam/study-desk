// Lecture recordings: drop them anywhere in the window; they are matched to a course,
// transcribed and checked. A broken transcript is never used silently.
import { api, enc } from "./api.js";
import { escapeHtml as esc, renderMarkdown } from "./render.js";
import { t } from "./strings.js";

const output = document.getElementById("bar-output");

function say(html) {
  output.innerHTML = html;
  output.hidden = false;
}

export function initDrop() {
  const overlay = document.createElement("div");
  overlay.className = "drop-overlay";
  overlay.textContent = t("rec.drop");
  overlay.hidden = true;
  document.body.append(overlay);
  let depth = 0;
  const hasFiles = (event) => [...(event.dataTransfer?.types ?? [])].includes("Files");
  window.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    depth += 1;
    overlay.hidden = false;
  });
  window.addEventListener("dragleave", () => {
    depth = Math.max(0, depth - 1);
    if (!depth) overlay.hidden = true;
  });
  window.addEventListener("dragover", (event) => hasFiles(event) && event.preventDefault());
  window.addEventListener("drop", async (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    depth = 0;
    overlay.hidden = true;
    const files = [...event.dataTransfer.files];
    if (!files.length) return;
    say(`<p class="muted">${esc(t("rec.uploading", { n: files.length }))}</p>`);
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    try {
      const response = await fetch("/api/recordings", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message ?? response.statusText);
      const rows = data.recordings
        .map((r) => `<li>${esc(r.name)} · ${esc(r.course ?? "")} <span class="pill">${esc(t(`rec.status.${r.status}`))}</span></li>`)
        .join("");
      say(`<p>${esc(t("rec.uploaded", { n: files.length }))}</p><ul class="plain">${rows}</ul>`);
      document.dispatchEvent(new CustomEvent("recordings-changed"));
    } catch (error) {
      say(`<p class="error">${esc(error.message || t("error.generic"))}</p>`);
    }
  });
}

/** The recordings section of the Today screen; refreshes itself while work is pending. */
export async function recordingsSection(container, courses) {
  let timer = null;
  const render = async () => {
    if (!container.isConnected) return clearInterval(timer);
    const { recordings } = await api.get("/api/recordings");
    if (!recordings.length) {
      container.innerHTML = `<p class="muted">${esc(t("rec.none"))}</p>`;
      return;
    }
    container.innerHTML = `<ul class="plain">${recordings
      .slice(0, 12)
      .map((r) => {
        const when = new Date(r.started).toLocaleString("tr-TR", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
        let extra = "";
        if (r.status === "done") extra = `<a href="#/recording/${r.id}">${esc(t("rec.open"))}</a>`;
        if (r.status === "bad_quality") {
          const reasons = r.reasons.map((x) => t(`rec.reason.${x}`)).join(", ");
          extra = `<br><span class="error">${esc(t("rec.bad_hint", { reasons }))}</span><br>
            ${r.has_audio ? `<button data-retry="${r.id}">${esc(t("rec.retry_large"))}</button>` : ""}
            <a href="#/recording/${r.id}">${esc(t("rec.open"))}</a>
            <button data-discard="${r.id}">${esc(t("rec.discard"))}</button>`;
        }
        if (r.status === "needs_course") {
          extra = `<br><span class="muted">${esc(t("rec.choose_course"))}</span>
            <select data-course="${r.id}"><option value=""></option>${courses
              .map((c) => `<option value="${esc(c.code)}">${esc(c.code)} ${esc(c.name)}</option>`)
              .join("")}</select>`;
        }
        if (r.status === "failed") extra = `<br><span class="error">${esc(r.error ?? "")}</span>`;
        return `<li>${esc(when)} · <strong>${esc(r.course ?? "?")}</strong> · ${r.minutes} dk
          <span class="pill">${esc(t(`rec.status.${r.status}`))}</span> ${extra}</li>`;
      })
      .join("")}</ul>`;
    for (const b of container.querySelectorAll("[data-retry]")) {
      b.onclick = async () => {
        await api.post(`/api/recordings/${b.dataset.retry}/retry`, { model: "large" });
        render();
      };
    }
    for (const b of container.querySelectorAll("[data-discard]")) {
      b.onclick = async () => {
        await api.del(`/api/recordings/${b.dataset.discard}`);
        render();
      };
    }
    for (const s of container.querySelectorAll("[data-course]")) {
      s.onchange = async () => {
        if (!s.value) return;
        await api.post(`/api/recordings/${s.dataset.course}/course`, { course: s.value });
        render();
      };
    }
    const busy = recordings.some((r) => ["queued", "transcribing"].includes(r.status));
    clearInterval(timer);
    if (busy) timer = setInterval(render, 5000);
  };
  document.addEventListener("recordings-changed", render);
  await render();
}

export async function showRecording(view, crumbs, id) {
  const { markdown } = await api.get(`/api/recordings/${enc(id)}/transcript`);
  crumbs.innerHTML = `<span>${esc(t("rec.transcript"))}</span>`;
  view.innerHTML = `<article class="transcript md">${renderMarkdown(markdown)}</article>`;
}
