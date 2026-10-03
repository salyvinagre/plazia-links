function updateSelection(active) {
  const items = [...document.querySelectorAll("[data-select-link]")];
  const form = document.getElementById("delete-selection");
  const all = document.querySelector("[data-select-all]");
  if (typeof active === "boolean" && form) {
    form.hidden = !active;
    all.checked = false;
    for (const item of items) {
      item.hidden = !active;
      item.checked = false;
    }
  }
  for (const item of items) item.disabled = all.checked;
  const count = all?.checked ? Number(all.dataset.total) : items.filter((item) => item.checked).length;
  if (all) all.indeterminate = !all.checked && count > 0;
  const status = document.getElementById("selection-count");
  if (status) status.textContent = all?.checked ? `All ${count} selected` : `${count} selected`;
  const button = document.querySelector("[data-delete-selection]");
  if (button) button.disabled = count === 0;
}

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-select-all]")) {
    for (const item of document.querySelectorAll("[data-select-link]")) {
      item.checked = event.target.checked;
    }
  }
  if (event.target.matches("[data-select-all], [data-select-link]")) updateSelection();
});

document.addEventListener("submit", (event) => {
  const message = event.target.querySelector("[data-select-all]:checked")
    ? event.target.dataset.confirmAll : event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

document.addEventListener("htmx:afterSwap", () => {
  updateSelection();
  document.querySelector('[aria-invalid="true"]')?.focus();
});
updateSelection();

document.addEventListener("htmx:beforeRequest", () => {
  for (const menu of document.querySelectorAll('details[name="resource-actions"][open]')) {
    menu.open = false;
  }
  const alert = document.getElementById("request-error");
  if (alert) alert.hidden = true;
});

document.addEventListener("click", (event) => {
  const action = event.target.closest("[data-select-links], [data-cancel-selection], [data-rename-pool]");
  if (action) {
    const rename = action.matches("[data-rename-pool]");
    const panel = document.getElementById("rename-pool-panel");
    if (panel) panel.hidden = !rename;
    if (rename) {
      updateSelection(false);
      document.getElementById("rename-pool").focus();
    } else {
      const active = action.matches("[data-select-links]");
      updateSelection(active);
      document.querySelector(active ? "[data-select-link]" : "[data-library-actions] summary")?.focus();
    }
    const menu = action.closest("details");
    if (menu) menu.open = false;
  }
  for (const menu of document.querySelectorAll('details[name="resource-actions"][open]')) {
    if (!menu.contains(event.target)) menu.open = false;
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  for (const menu of document.querySelectorAll('details[name="resource-actions"][open]')) {
    menu.open = false;
    menu.querySelector("summary").focus();
  }
});

document.addEventListener("htmx:beforeSwap", (event) => {
  if (!event.detail.xhr.getResponseHeader("Content-Type")?.includes("text/html")) {
    event.detail.shouldSwap = false;
    event.detail.isError = true;
  }
});

for (const event of ["htmx:responseError", "htmx:sendError", "htmx:timeout"]) {
  document.addEventListener(event, () => {
    const alert = document.getElementById("request-error");
    if (alert) alert.hidden = false;
  });
}
