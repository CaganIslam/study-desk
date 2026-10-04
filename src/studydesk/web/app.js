// All UI text comes from strings.<lang>.json (ARCHITECTURE: Text).
const strings = await fetch("strings.tr.json").then((r) => r.json());
const t = (key) => strings[key] ?? key;

for (const el of document.querySelectorAll("[data-text]")) {
  el.textContent = t(el.dataset.text);
}

const status = document.getElementById("status");
try {
  const health = await fetch("/api/health").then((r) => r.json());
  status.textContent = t(health.data_root_configured ? "app.ready" : "app.first_run");
} catch {
  status.textContent = t("app.server_down");
}
