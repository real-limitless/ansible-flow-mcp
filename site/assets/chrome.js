/** Inject shared nav + footer. data-base on <html> prefixes links for project Pages. */
(function () {
  const base = document.documentElement.getAttribute("data-base") || "";
  const p = (href) => base + href;

  const nav = document.getElementById("site-nav");
  if (nav) {
    nav.innerHTML =
      '<a class="brand" href="' +
      p("index.html") +
      '">' +
      '<div class="brand-mark" aria-hidden="true"></div>' +
      '<div class="brand-name">ansible-flow<span>-mcp</span></div>' +
      "</a>" +
      '<button type="button" class="nav-toggle" aria-expanded="false" aria-controls="nav-menu">Menu</button>' +
      '<ul class="nav-links" id="nav-menu">' +
      '<li><a data-nav="why.html" href="' +
      p("why.html") +
      '">Why</a></li>' +
      '<li><a data-nav="how.html" href="' +
      p("how.html") +
      '">How</a></li>' +
      '<li><a data-nav="fabric.html" href="' +
      p("fabric.html") +
      '">Fabric</a></li>' +
      '<li><a data-nav="security.html" href="' +
      p("security.html") +
      '">Security</a></li>' +
      '<li><a data-nav="start.html" href="' +
      p("start.html") +
      '">Start</a></li>' +
      '<li><a class="cta-nav" href="https://github.com/real-limitless/ansible-flow-mcp" rel="noopener">GitHub</a></li>' +
      "</ul>";
  }

  const foot = document.getElementById("site-footer");
  if (foot) {
    foot.innerHTML =
      '<div class="wrap foot-grid">' +
      "<div>" +
      '<div class="brand" style="margin-bottom:10px">' +
      '<div class="brand-mark" aria-hidden="true"></div>' +
      '<div class="brand-name">ansible-flow<span>-mcp</span></div></div>' +
      '<p class="legal">Apache-2.0. Not affiliated with Red Hat or the Ansible project beyond the public CLI and docs. Dual-track with <a href="https://github.com/real-limitless/OpenFlow" rel="noopener">OpenFlow</a>.</p>' +
      "</div>" +
      '<div style="display:flex;flex-direction:column;gap:8px;font-family:var(--font-mono);font-size:11px;letter-spacing:0.06em;text-transform:uppercase">' +
      '<a href="' +
      p("how.html") +
      '">Schema Lab</a>' +
      '<a href="' +
      p("start.html") +
      '">Quick start</a>' +
      '<a href="https://github.com/real-limitless/ansible-flow-mcp/blob/main/docs/HUB.md" rel="noopener">Hub ops</a>' +
      '<a href="https://github.com/real-limitless/ansible-flow-mcp/blob/main/docs/SECURITY.md" rel="noopener">Security model</a>' +
      "</div></div>";
  }
})();
