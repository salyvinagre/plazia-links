function updateSelection() {
  const items = [...document.querySelectorAll("[data-select-link]")];
  const count = items.filter((item) => item.checked).length;
  const all = document.querySelector("[data-select-all]");
  if (all) {
    all.checked = items.length > 0 && count === items.length;
    all.indeterminate = count > 0 && count < items.length;
  }
  const status = document.getElementById("selection-count");
  if (status) status.textContent = `${count} selected`;
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
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

document.addEventListener("htmx:afterSwap", updateSelection);
updateSelection();

document.addEventListener("htmx:beforeRequest", () => {
  for (const menu of document.querySelectorAll('details[name="link-actions"][open]')) {
    menu.open = false;
  }
  const alert = document.getElementById("request-error");
  if (alert) alert.hidden = true;
});

document.addEventListener("click", (event) => {
  for (const menu of document.querySelectorAll('details[name="link-actions"][open]')) {
    if (!menu.contains(event.target)) menu.open = false;
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  for (const menu of document.querySelectorAll('details[name="link-actions"][open]')) {
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
