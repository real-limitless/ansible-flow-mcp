(function () {
  const path = (location.pathname.split("/").pop() || "index.html").replace(/\/$/, "");
  const page = path === "" || path === "/" ? "index.html" : path;

  document.querySelectorAll(".nav-links a[data-nav]").forEach((a) => {
    if (a.getAttribute("data-nav") === page) {
      a.setAttribute("aria-current", "page");
    }
  });

  const toggle = document.querySelector(".nav-toggle");
  const links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", () => {
      const open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
})();
