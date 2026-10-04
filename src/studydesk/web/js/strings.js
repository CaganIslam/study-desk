// All UI text comes from strings.<lang>.json (ARCHITECTURE: Text).
const strings = await fetch("strings.tr.json").then((r) => r.json());

export function t(key, vars = {}) {
  let text = strings[key] ?? key;
  for (const [name, value] of Object.entries(vars)) text = text.replaceAll(`{${name}}`, value);
  return text;
}

export function applyStrings(root = document) {
  for (const el of root.querySelectorAll("[data-text]")) el.textContent = t(el.dataset.text);
}
