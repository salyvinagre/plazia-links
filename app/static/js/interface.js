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
