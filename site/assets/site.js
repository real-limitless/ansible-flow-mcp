(function () {
  const path = (location.pathname.split("/").pop() || "index.html").replace(/\/$/, "");
  const page = path === "" || path === "/" ? "index.html" : path;
  document.querySelectorAll(".meta-pills a[data-nav]").forEach((a) => {
    if (a.getAttribute("data-nav") === page) {
      a.setAttribute("aria-current", "page");
      a.classList.add("accent");
    }
  });
})();
