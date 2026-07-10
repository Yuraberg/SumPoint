// Apply the saved (or OS-preferred) theme before first paint — no flash.
// External (not inline) so the CSP can forbid inline scripts.
(function () {
  var t = localStorage.getItem("sp_theme");
  if (!t) t = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", t);
})();
