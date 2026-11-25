// On small screens tables are shown as one card per row (see base.css). Each cell gets the
// text of its column header as data-label, so the card can show "Role: Analyst".
// Done once for the whole app with a MutationObserver, so pages need no extra markup.

function label(root: ParentNode) {
  root.querySelectorAll<HTMLTableElement>(".table-wrap table").forEach((table) => {
    const heads = Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent?.trim() ?? "");
    table.querySelectorAll("tbody tr").forEach((tr) => {
      Array.from(tr.children).forEach((td, i) => {
        if (td instanceof HTMLElement && td.getAttribute("colspan") == null && heads[i] !== undefined && td.dataset.label !== heads[i]) {
          td.dataset.label = heads[i];
        }
      });
    });
  });
}

export function installResponsiveTables() {
  let scheduled = false;
  const run = () => {
    scheduled = false;
    label(document);
  };
  new MutationObserver(() => {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(run);
    }
  }).observe(document.body, { childList: true, subtree: true });
  run();
}
