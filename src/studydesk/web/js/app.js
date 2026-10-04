import { applyStrings, t } from "./strings.js";
import { escapeHtml } from "./render.js";
import { showHome } from "./home.js";
import { showCourse } from "./course.js";
import { leaveStudy, showStudy } from "./study.js";
import { initBar } from "./bar.js";
import { showTerms } from "./terms.js";

applyStrings();
initBar();

// New Moodle files are fetched in the background whenever the app is opened.
fetch("/api/sync/moodle", { method: "POST" }).catch(() => {});

const view = document.getElementById("view");
const crumbs = document.getElementById("crumbs");

async function route() {
  leaveStudy();
  const [page, a, b] = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  try {
    if (page === "course" && a) await showCourse(view, crumbs, a);
    else if (page === "deck" && a) await showStudy(view, crumbs, Number(a), Number(b) || 1);
    else if (page === "terms") await showTerms(view, crumbs, a);
    else await showHome(view, crumbs);
  } catch (error) {
    const key = `error.${error.code}`;
    const message = t(key) === key ? error.message || t("error.generic") : t(key);
    view.innerHTML = `<p class="error">${escapeHtml(message)}</p>`;
  }
}

window.addEventListener("hashchange", route);
route();
