// Markdown with LaTeX: math is cut out before markdown parsing, rendered with KaTeX, then put back.
import { marked } from "../vendor/marked/marked.esm.js";

const escapeHtml = (text) =>
  text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// Raw HTML in model output is shown as text, never injected.
marked.use({ renderer: { html: ({ text }) => escapeHtml(text) } });

export function renderMarkdown(markdown) {
  const math = [];
  const keep = (tex, display) => `@@MATH${math.push([tex, display]) - 1}@@`;
  let text = markdown.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => keep(tex, true));
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => keep(tex, true));
  text = text.replace(/\\\(([\s\S]+?)\\\)/g, (_, tex) => keep(tex, false));
  text = text.replace(/(^|[^\\$])\$([^\n$]+?)\$/g, (_, before, tex) => before + keep(tex, false));
  const html = marked.parse(text);
  return html.replace(/@@MATH(\d+)@@/g, (_, i) => {
    const [tex, display] = math[Number(i)];
    try {
      return window.katex.renderToString(tex, { displayMode: display, throwOnError: false });
    } catch {
      return escapeHtml(tex);
    }
  });
}

export function highlightCode(root) {
  for (const block of root.querySelectorAll("pre code")) window.hljs?.highlightElement(block);
}

export { escapeHtml };
