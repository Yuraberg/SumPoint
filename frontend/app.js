/* ── SumPoint frontend ───────────────────────────────────────────────────────── */

const API = "/api/v1";
// The JWT now lives in an HttpOnly cookie the browser sends automatically — it
// is intentionally NOT readable from JS (XSS can't steal it). currentUser is
// populated from /auth/me once the cookie is known good.
let currentUser = null;
let isMiniApp = !!(window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData);

let filters = { dateFrom: "", dateTo: "", category: "", channelId: "", unreadOnly: false };
let density = localStorage.getItem("sp_density") || "medium";
let lastPosts = [];
let selectedPostIds = new Set();  // ids of checked posts, for selective export
let lastEvents = [];
let allLoadedEvents = [];  // events after server + topic filters, before the free-text search filter
let selectedEventKeys = new Set();  // keys (name+date+idx) of checked events, for selective .ics export
let lastSchedules = [];  // schedules from the last /schedule/ load, so the edit modal can prefill without a refetch
let schedEditId = null;  // id of the schedule being edited, or null when the modal is in "create" mode

// Feed pagination / infinite-scroll state. searchMode disables paging because
// search returns a single fixed result set, not an offset-able feed.
const FEED_PAGE = 40;
let feed = { offset: 0, loading: false, done: false, searchMode: false };
let feedObserver = null;

// ── Toasts (replaces blocking alert()) ────────────────────────────────────────
function toast(message, type = "info", ms = 3500) {
  const container = document.getElementById("toast-container");
  if (!container) { console.log(`[${type}]`, message); return; }
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 250);
  }, ms);
}

// ── Theme (light / dark) ──────────────────────────────────────────────────────
// The initial theme is applied by an inline <head> script to avoid a flash;
// this just handles the toggle and keeps the button label in sync.
function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "light";
}
function applyThemeButton() {
  const btn = document.getElementById("theme-btn");
  if (!btn) return;
  btn.textContent = currentTheme() === "dark" ? t("sidebar.themeLight") : t("sidebar.themeDark");
}
function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("sp_theme", next);
  applyThemeButton();
}

// ── Keyboard navigation (posts page) ──────────────────────────────────────────
let kbIndex = -1;

function isPostsPageActive() {
  const p = document.getElementById("page-posts");
  return p && p.classList.contains("active");
}

function kbRows() {
  return Array.from(document.querySelectorAll("#posts-tbody tr.data-row"));
}

function setKbActive(idx) {
  const rows = kbRows();
  rows.forEach(r => r.classList.remove("kb-active"));
  if (idx < 0 || idx >= rows.length) { kbIndex = -1; return; }
  kbIndex = idx;
  const row = rows[idx];
  row.classList.add("kb-active");
  row.scrollIntoView({ block: "nearest" });
}

function handleFeedKey(e) {
  const tag = (e.target.tagName || "").toLowerCase();
  const typing = tag === "input" || tag === "textarea" || tag === "select";

  // "/" focuses search from anywhere on the posts page.
  if (e.key === "/" && !typing && isPostsPageActive()) {
    e.preventDefault();
    document.getElementById("search-input").focus();
    return;
  }
  if (e.key === "Escape") {
    if (typing) { e.target.blur(); return; }
    const cluster = document.getElementById("cluster-modal");
    if (cluster && cluster.style.display !== "none") { closeClusterModal(); return; }
    const modal = document.getElementById("sched-modal");
    if (modal && modal.style.display !== "none") { closeSchedModal(); return; }
    setKbActive(-1);
    return;
  }
  if (typing || !isPostsPageActive()) return;

  const rows = kbRows();
  if (e.key === "j") {
    e.preventDefault();
    setKbActive(Math.min((kbIndex < 0 ? -1 : kbIndex) + 1, rows.length - 1));
    if (kbIndex >= rows.length - 3) loadMorePosts();
  } else if (e.key === "k") {
    e.preventDefault();
    setKbActive(Math.max((kbIndex < 0 ? 1 : kbIndex) - 1, 0));
  } else if (e.key === "o" || e.key === "Enter") {
    if (kbIndex >= 0 && rows[kbIndex]) { e.preventDefault(); rows[kbIndex].click(); }
  }
}

// ── Resizable table columns ──────────────────────────────────────────────────
// Drags the header cell's own width (table-layout:fixed takes column widths
// from the header row), persisted per-table in localStorage so it survives
// a reload.
function initResizableColumns(tableId, storageKey) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const ths = Array.from(table.querySelectorAll("thead th[data-col]"));
  if (!ths.length) return;

  const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
  ths.forEach(th => {
    const w = saved[th.dataset.col];
    if (w) th.style.width = w + "px";
  });

  ths.forEach((th, i) => {
    if (i === ths.length - 1) return; // no handle on the last column
    const handle = document.createElement("div");
    handle.className = "col-resize-handle";
    th.appendChild(handle);

    let startX = 0;
    let startWidth = 0;

    function onMouseMove(e) {
      const delta = e.clientX - startX;
      th.style.width = Math.max(40, startWidth + delta) + "px";
    }
    function onMouseUp() {
      handle.classList.remove("active");
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      const widths = JSON.parse(localStorage.getItem(storageKey) || "{}");
      widths[th.dataset.col] = th.offsetWidth;
      localStorage.setItem(storageKey, JSON.stringify(widths));
    }
    handle.addEventListener("mousedown", e => {
      e.preventDefault();
      e.stopPropagation();
      handle.classList.add("active");
      startX = e.clientX;
      startWidth = th.offsetWidth;
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });
  });
}

// ── Row density (Compact / Medium / Expanded) ────────────────────────────────
function setDensity(d) {
  density = d;
  localStorage.setItem("sp_density", d);
  document.querySelectorAll(".density-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.density === d);
  });
  const container = document.getElementById("posts-table-container");
  if (container) container.dataset.density = d;
  renderPosts(lastPosts);
}

// ── Auth ──────────────────────────────────────────────────────────────────────
// credentials:"include" makes the browser send the HttpOnly session cookie with
// every API call. No Authorization header, no token in JS.

function authHeaders() {
  return { "Content-Type": "application/json" };
}

async function apiFetch(path, opts = {}) {
  const resp = await fetch(API + path, {
    credentials: "include",
    ...opts,
    headers: { ...authHeaders(), ...(opts.headers || {}) },
  });
  if (resp.status === 401) { onUnauthed(); return null; }
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

// A 401 mid-session means the cookie expired or was revoked — drop to login
// instead of a reload loop.
function onUnauthed() {
  currentUser = null;
  const app = document.getElementById("app");
  const login = document.getElementById("login-screen");
  if (app) app.style.display = "none";
  if (login) login.style.display = "flex";
}

// ── Mini App auto-login ──────────────────────────────────────────────────────

async function tryMiniAppLogin() {
  if (!isMiniApp) return false;
  try {
    const inviteEl = document.getElementById("invite-code-input");
    const invite = inviteEl ? inviteEl.value.trim() : "";
    const resp = await fetch(`${API}/auth/telegram/miniapp`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: window.Telegram.WebApp.initData, invite_code: invite || null }),
    });
    if (!resp.ok) {
      console.error("MiniApp auth failed:", await resp.text());
      return false;
    }
    return true;  // cookie is set; caller confirms via /auth/me
  } catch (e) {
    console.error("MiniApp auth error:", e);
    return false;
  }
}

// ── Magic Link ────────────────────────────────────────────────────────────────

async function tryMagicLinkVerify() {
  const params = new URLSearchParams(window.location.search);
  const magicToken = params.get("token");
  if (!magicToken) return false;

  // Clean URL so the one-time token isn't left in history.
  window.history.replaceState({}, "", "/");

  try {
    const resp = await fetch(
      `${API}/auth/telegram/magic-link/verify?token=${encodeURIComponent(magicToken)}`,
      { credentials: "include" },
    );
    if (!resp.ok) {
      const err = await resp.json();
      toast(err.detail || t("login.errLinkInvalid"), "error");
      return false;
    }
    return true;  // cookie is set
  } catch (e) {
    toast(t("login.errAuth") + e.message, "error");
    return false;
  }
}

// Confirm the session cookie is valid and load the current user.
async function fetchMe() {
  try {
    const resp = await fetch(`${API}/auth/me`, { credentials: "include" });
    if (!resp.ok) return null;
    currentUser = await resp.json();
    return currentUser;
  } catch {
    return null;
  }
}

function _on(id, event, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener(event, fn);
}

function wireStaticHandlers() {
  // Login
  _on("magic-btn", "click", requestMagicLink);

  // Schedule modal open/close/create
  _on("sched-open-btn", "click", () => openSchedModal());
  _on("sched-close-btn", "click", () => closeSchedModal());
  _on("sched-cancel-btn", "click", () => closeSchedModal());
  _on("sched-create-btn", "click", saveSchedule);
  _on("sched-modal", "click", e => closeSchedModal(e));
  _on("m-cron-preset", "change", e => onPresetChange(e.target));
  const typeBtns = document.getElementById("type-btns");
  if (typeBtns) typeBtns.addEventListener("click", e => {
    const btn = e.target.closest(".type-btn");
    if (btn) selectType(btn);
  });

  // Cluster sources modal
  _on("cluster-modal", "click", e => closeClusterModal(e));
  _on("cluster-modal-close", "click", () => closeClusterModal());

  // Pending-approval screen
  _on("pending-invite-btn", "click", activatePendingInvite);
  _on("pending-invite-input", "keydown", e => { if (e.key === "Enter") activatePendingInvite(); });
  _on("pending-logout-btn", "click", logout);

  // Owner admin page
  _on("create-invite-btn", "click", createInvite);
  const pendingList = document.getElementById("pending-users-list");
  if (pendingList) pendingList.addEventListener("click", _onRowAction);
  const invitesList = document.getElementById("invites-list");
  if (invitesList) invitesList.addEventListener("click", _onRowAction);

  // Delegated row actions (rows are built via innerHTML, so listeners can't be
  // bound at creation without inline handlers). data-action + data-id drive it.
  const channelsList = document.getElementById("channels-list");
  if (channelsList) channelsList.addEventListener("click", _onRowAction);
  const schedTbody = document.getElementById("sched-tbody");
  if (schedTbody) schedTbody.addEventListener("click", _onRowAction);
}

function _onRowAction(e) {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const id = btn.dataset.id;
  switch (btn.dataset.action) {
    case "remove-channel": removeChannel(Number(id)); break;
    case "toggle-channel": toggleChannel(Number(id)); break;
    case "delete-schedule": deleteSchedule(Number(id)); break;
    case "toggle-schedule": toggleSchedule(Number(id), btn); break;
    case "edit-schedule": openSchedModal(Number(id)); break;
    case "approve-user": approveUser(Number(id)); break;
    case "delete-invite": deleteInvite(Number(id)); break;
  }
}

async function requestMagicLink() {
  const input = document.getElementById("magic-username");
  const btn = document.getElementById("magic-btn");
  const status = document.getElementById("magic-status");
  const username = input.value.trim();
  
  if (!username) {
    status.textContent = t("login.enterUsername");
    return;
  }

  btn.disabled = true;
  btn.textContent = t("login.magicBtnSending");
  status.textContent = "";

  try {
    const resp = await fetch(`${API}/auth/telegram/magic-link/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      status.textContent = data.detail || t("login.errGeneric");
      status.className = "magic-status error";
    } else {
      status.textContent = data.message;
      status.className = "magic-status success";
    }
  } catch (e) {
    status.textContent = t("login.errNetwork");
    status.className = "magic-status error";
  } finally {
    btn.disabled = false;
    btn.textContent = t("login.magicBtn");
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

async function boot() {
  // Magic Link from URL — sets the session cookie.
  const params = new URLSearchParams(window.location.search);
  if (params.get("token")) {
    if (await tryMagicLinkVerify() && await fetchMe()) { showApp(); return; }
  }

  // Mini App: auto-login via initData — sets the session cookie.
  if (isMiniApp) {
    if (await tryMiniAppLogin() && await fetchMe()) { showApp(); return; }
    // Fall through to widget if MiniApp auth fails
  }

  // Otherwise: do we already have a valid session cookie?
  if (await fetchMe()) {
    showApp();
  } else {
    document.getElementById("login-screen").style.display = "flex";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  applyI18n();
  const langBtn = document.getElementById("lang-btn");
  if (langBtn) langBtn.addEventListener("click", () => setLang(lang === "en" ? "ru" : "en"));

  boot();
  loadPublicConfig();

  document.getElementById("logout-btn").addEventListener("click", logout);

  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", e => {
      e.preventDefault();
      navigate(item.dataset.page);
    });
  });

  // Filters
  document.getElementById("filter-date-from").addEventListener("change", e => {
    filters.dateFrom = e.target.value;
    loadFeed();
  });
  document.getElementById("filter-date-to").addEventListener("change", e => {
    filters.dateTo = e.target.value;
    loadFeed();
  });
  document.getElementById("filter-category").addEventListener("change", e => {
    filters.category = e.target.value;
    loadFeed();
  });
  document.getElementById("filter-channel").addEventListener("change", e => {
    filters.channelId = e.target.value;
    loadFeed();
  });
  document.getElementById("fav-filter-category").addEventListener("change", loadFavorites);
  document.getElementById("search-btn").addEventListener("click", runSearch);
  document.getElementById("search-input").addEventListener("keydown", e => {
    if (e.key === "Enter") runSearch();
  });

  // Events page filters
  document.getElementById("ev-date-from").addEventListener("change", loadEvents);
  document.getElementById("ev-date-to").addEventListener("change", loadEvents);
  document.getElementById("ev-filter-topic").addEventListener("change", loadEvents);
  document.getElementById("ev-filter-type").addEventListener("change", loadEvents);
  document.getElementById("ev-search-input").addEventListener("input", applyEventSearch);
  document.getElementById("ev-select-all").addEventListener("change", toggleAllEventsSelected);
  document.getElementById("ev-reset-btn").addEventListener("click", resetEventFilters);
  document.getElementById("ev-ics-btn").addEventListener("click", exportEventsIcs);

  document.getElementById("gen-digest-btn").addEventListener("click", generateDigest);
  document.getElementById("add-channel-btn").addEventListener("click", addChannel);
  document.getElementById("channel-input").addEventListener("keydown", e => {
    if (e.key === "Enter") addChannel();
  });
  document.getElementById("import-btn").addEventListener("click", importChannels);
  document.getElementById("sync-btn").addEventListener("click", syncChannels);

  // Unread controls
  document.getElementById("unread-only").addEventListener("change", e => {
    filters.unreadOnly = e.target.checked;
    loadFeed();
  });
  document.getElementById("mark-all-read-btn").addEventListener("click", markAllRead);
  document.getElementById("post-select-all").addEventListener("change", toggleAllPostsSelected);

  const exportBtn = document.getElementById("export-btn");
  if (exportBtn) exportBtn.addEventListener("click", e => {
    e.stopPropagation();
    const menu = document.getElementById("export-menu");
    menu.style.display = menu.style.display === "none" ? "block" : "none";
  });
  document.querySelectorAll("#export-menu button").forEach(b => {
    b.addEventListener("click", () => {
      document.getElementById("export-menu").style.display = "none";
      exportPosts(b.dataset.format);
    });
  });
  document.addEventListener("click", () => {
    const menu = document.getElementById("export-menu");
    if (menu) menu.style.display = "none";
  });

  // Theme toggle
  applyThemeButton();
  document.getElementById("theme-btn").addEventListener("click", toggleTheme);

  const statsDays = document.getElementById("stats-days");
  if (statsDays) statsDays.addEventListener("change", loadStats);

  const chatSend = document.getElementById("chat-send-btn");
  if (chatSend) chatSend.addEventListener("click", sendChatQuestion);
  const chatInput = document.getElementById("chat-input");
  if (chatInput) chatInput.addEventListener("keydown", e => {
    if (e.key === "Enter") sendChatQuestion();
  });

  // Handlers moved out of inline on* attributes so the CSP can forbid inline
  // scripts (defends the localStorage token against injected-script XSS).
  wireStaticHandlers();

  // Keyboard navigation
  document.addEventListener("keydown", handleFeedKey);

  // Row density toggle — reflect the saved preference and wire up clicks.
  document.querySelectorAll(".density-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.density === density);
    btn.addEventListener("click", () => setDensity(btn.dataset.density));
  });
  const postsContainer = document.getElementById("posts-table-container");
  if (postsContainer) postsContainer.dataset.density = density;

  // Resizable columns — header rows are static, so this only needs to run once.
  initResizableColumns("posts-table", "sp_col_widths_posts");
  initResizableColumns("events-table", "sp_col_widths_events");
  initResizableColumns("sched-table", "sp_col_widths_sched");
});

// ── Public config (bot username, base URL) ─────────────────────────────────────
async function loadPublicConfig() {
  try {
    const resp = await fetch(`${API}/auth/config`);
    if (!resp.ok) return;
    const cfg = await resp.json();
    if (cfg.bot_username) {
      const usernameEl = document.getElementById("bot-username");
      const linkEl = document.getElementById("bot-link");
      if (usernameEl) usernameEl.textContent = cfg.bot_username;
      if (linkEl) linkEl.href = `https://t.me/${encodeURIComponent(cfg.bot_username)}`;

      const container = document.getElementById("telegram-widget-container");
      if (container) {
        const script = document.createElement("script");
        script.async = true;
        script.src = "https://telegram.org/js/telegram-widget.js?22";
        script.setAttribute("data-telegram-login", cfg.bot_username);
        script.setAttribute("data-size", "large");
        script.setAttribute("data-onauth", "onTelegramAuth(user)");
        script.setAttribute("data-request-access", "write");
        // The widget silently renders nothing if the site's domain isn't
        // registered for this bot via @BotFather /setdomain — no error, no
        // button, just an empty area. Fall back to a visible hint instead of
        // leaving that unexplained blank space (and also catch a genuine
        // load failure, e.g. no network to telegram.org).
        script.onerror = () => showWidgetFallback(container);
        container.appendChild(script);
        setTimeout(() => {
          if (!container.querySelector("iframe")) showWidgetFallback(container);
        }, 4000);
      }
    }
  } catch {
    // Non-critical — login screen still works via Magic Link without bot link.
  }
}

function showWidgetFallback(container) {
  if (container.querySelector(".login-widget-fallback")) return;
  container.innerHTML =
    `<p class="login-widget-fallback">${escHtml(t("login.widgetFallback"))}</p>`;
}

// ── Show app ──────────────────────────────────────────────────────────────────

function showApp() {
  document.getElementById("login-screen").style.display = "none";

  if (currentUser && currentUser.is_approved === false) {
    document.getElementById("pending-screen").style.display = "flex";
    document.getElementById("app").style.display = "none";
    return;
  }
  document.getElementById("pending-screen").style.display = "none";

  document.getElementById("app").style.display = "flex";
  const nameEl = document.getElementById("sidebar-user");
  if (nameEl && currentUser) nameEl.textContent = currentUser.first_name || "";
  const adminNav = document.getElementById("nav-admin");
  if (adminNav) adminNav.style.display = (currentUser && currentUser.is_owner) ? "" : "none";
  loadChannelsDropdown();
  refreshUnreadCount();
  navigate("posts");
}

async function logout() {
  try {
    await fetch(`${API}/auth/logout`, { method: "POST", credentials: "include" });
  } catch { /* clear locally regardless */ }
  currentUser = null;
  location.reload();
}

// ── Navigation ────────────────────────────────────────────────────────────────

function navigate(page) {
  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".page").forEach(el => el.classList.remove("active"));

  const navEl = document.querySelector(`.nav-item[data-page="${page}"]`);
  const pageEl = document.getElementById(`page-${page}`);
  if (navEl) navEl.classList.add("active");
  if (pageEl) pageEl.classList.add("active");

  if (page === "posts") loadFeed();
  else if (page === "favorites") loadFavorites();
  else if (page === "events") loadEvents();
  else if (page === "stats") loadStats();
  else if (page === "chat") { const i = document.getElementById("chat-input"); if (i) i.focus(); }
  else if (page === "channels") loadChannels();
  else if (page === "schedule") loadSchedule();
  else if (page === "admin") loadAdmin();
}

// ── Access control (pending screen + owner admin page) ─────────────────────────

async function activatePendingInvite() {
  const input = document.getElementById("pending-invite-input");
  const status = document.getElementById("pending-status");
  const code = input.value.trim();
  if (!code) return;
  try {
    await apiFetch("/auth/redeem-invite", { method: "POST", body: JSON.stringify({ code }) });
    status.textContent = t("pending.accepted");
    status.className = "magic-status success";
    setTimeout(() => location.reload(), 800);
  } catch (e) {
    status.textContent = t("pending.rejected");
    status.className = "magic-status error";
  }
}

async function loadAdmin() {
  try {
    const pending = await apiFetch("/admin/pending-users");
    const list = document.getElementById("pending-users-list");
    const empty = document.getElementById("pending-users-empty");
    list.innerHTML = "";
    empty.style.display = (pending && pending.length) ? "none" : "block";
    (pending || []).forEach(u => {
      const li = document.createElement("li");
      li.className = "channel-item";
      const name = escHtml(u.username ? "@" + u.username : u.first_name);
      li.innerHTML = `
        <span class="channel-item-name">${name} <span style="color:var(--muted);font-size:12px">id ${u.id}</span></span>
        <button class="btn-ghost-sm" data-action="approve-user" data-id="${u.id}">${t("admin.approve")}</button>
      `;
      list.appendChild(li);
    });
  } catch (e) {
    toast(t("admin.errPending") + e.message, "error");
  }

  try {
    const invites = await apiFetch("/admin/invites");
    const list = document.getElementById("invites-list");
    const empty = document.getElementById("invites-empty");
    list.innerHTML = "";
    empty.style.display = (invites && invites.length) ? "none" : "block";
    (invites || []).forEach(inv => {
      const li = document.createElement("li");
      li.className = "channel-item";
      const used = `${inv.uses}/${inv.max_uses}`;
      li.innerHTML = `
        <span class="channel-item-name">
          <code>${escHtml(inv.code)}</code>
          <span style="color:var(--muted);font-size:12px">${t("admin.usedCount", used)}</span>
        </span>
        <button class="channel-remove" data-action="delete-invite" data-id="${inv.id}">✕</button>
      `;
      list.appendChild(li);
    });
  } catch (e) {
    toast(t("admin.errInvites") + e.message, "error");
  }
}

async function approveUser(id) {
  try {
    await apiFetch(`/admin/pending-users/${id}/approve`, { method: "POST" });
    toast(t("admin.userApproved"), "success");
    loadAdmin();
  } catch (e) {
    toast(t("admin.error") + e.message, "error");
  }
}

async function createInvite() {
  try {
    const inv = await apiFetch("/admin/invites", { method: "POST", body: JSON.stringify({}) });
    toast(t("admin.inviteCreated", inv.code), "success");
    loadAdmin();
  } catch (e) {
    toast(t("admin.error") + e.message, "error");
  }
}

async function deleteInvite(id) {
  try {
    await fetch(`${API}/admin/invites/${id}`, { method: "DELETE", credentials: "include" });
    loadAdmin();
  } catch (e) {
    toast(t("admin.error") + e.message, "error");
  }
}

// ── Telegram login ────────────────────────────────────────────────────────────

async function onTelegramAuth(data) {
  try {
    const inviteEl = document.getElementById("invite-code-input");
    const invite = inviteEl ? inviteEl.value.trim() : "";
    const qs = invite ? `?invite_code=${encodeURIComponent(invite)}` : "";
    const resp = await fetch(`${API}/auth/telegram${qs}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!resp.ok) throw new Error("Auth failed");
    location.reload();  // session cookie is set; boot() → /auth/me → app
  } catch (e) {
    toast(t("login.errAuth") + e.message, "error");
  }
}

// ── Feed (Posts Table) ────────────────────────────────────────────────────────

function buildFeedUrl(offset) {
  let url = `/posts/?limit=${FEED_PAGE}&offset=${offset}`;
  if (filters.category) url += `&category=${encodeURIComponent(filters.category)}`;
  if (filters.channelId) url += `&channel_id=${filters.channelId}`;
  if (filters.dateFrom) url += `&date_from=${filters.dateFrom}`;
  if (filters.dateTo) url += `&date_to=${filters.dateTo}`;
  if (filters.unreadOnly) url += `&unread_only=true`;
  return url;
}

async function exportPosts(format) {
  // If the user checked specific posts, export just those (client-side, from
  // what's already loaded) instead of hitting the server for the whole filtered feed.
  if (selectedPostIds.size > 0) {
    exportSelectedPosts(format);
    return;
  }

  let url = `/posts/export?format=${format}`;
  if (filters.category) url += `&category=${encodeURIComponent(filters.category)}`;
  if (filters.channelId) url += `&channel_id=${filters.channelId}`;
  if (filters.dateFrom) url += `&date_from=${filters.dateFrom}`;
  if (filters.dateTo) url += `&date_to=${filters.dateTo}`;
  if (filters.unreadOnly) url += `&unread_only=true`;
  try {
    // Can't use a plain <a href> — the download needs the Bearer token.
    const resp = await fetch(API + url, { credentials: "include", headers: authHeaders() });
    if (resp.status === 401) { logout(); return; }
    if (!resp.ok) throw new Error(await resp.text());
    const blob = await resp.blob();
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = `sumpoint-posts.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objUrl);
    toast(t("posts.exportReady", format.toUpperCase()), "success");
  } catch (e) {
    toast(t("posts.errExport") + e.message, "error");
  }
}

// Client-side export of just the checked posts, mirroring the columns of the
// server-side /posts/export endpoint (which has no way to filter by post id).
function _csvField(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function _postExportRecord(post) {
  const username = post.channel_username;
  return {
    id: post.id,
    published_at: post.published_at || "",
    channel_title: post.channel_title || "",
    channel_username: username || "",
    category: post.category || "",
    is_read: !!post.is_read,
    cluster_size: Math.max(post.cluster_size || 1, 1),
    summary: post.summary || "",
    text: post.text || "",
    telegram_url: username ? `https://t.me/${username}/${post.telegram_message_id}` : "",
  };
}

function exportSelectedPosts(format) {
  const posts = lastPosts.filter(p => selectedPostIds.has(p.id));
  if (posts.length === 0) {
    toast(t("posts.noneSelected"), "error");
    return;
  }
  const records = posts.map(_postExportRecord);
  const columns = ["id", "published_at", "channel_title", "channel_username",
    "category", "is_read", "cluster_size", "summary", "text", "telegram_url"];

  let body, media;
  if (format === "json") {
    body = JSON.stringify(records, null, 2);
    media = "application/json";
  } else {
    const lines = [columns.join(",")];
    records.forEach(r => lines.push(columns.map(c => _csvField(r[c])).join(",")));
    body = lines.join("\r\n");
    media = "text/csv";
  }

  const blob = new Blob([body], { type: `${media};charset=utf-8` });
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = `sumpoint-posts.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objUrl);
  toast(t("posts.exportedCount", records.length), "success");
}

function toggleAllPostsSelected(e) {
  const checked = e.target.checked;
  lastPosts.forEach(post => {
    if (checked) selectedPostIds.add(post.id);
    else selectedPostIds.delete(post.id);
  });
  document.querySelectorAll(".post-row-check").forEach(cb => { cb.checked = checked; });
}

function updatePostsSelectAllState() {
  const selectAll = document.getElementById("post-select-all");
  if (!selectAll) return;
  const ids = lastPosts.map(p => p.id);
  const selectedVisible = ids.filter(id => selectedPostIds.has(id));
  selectAll.checked = ids.length > 0 && selectedVisible.length === ids.length;
  selectAll.indeterminate = selectedVisible.length > 0 && selectedVisible.length < ids.length;
}

function showSkeletons(n = 6) {
  const tbody = document.getElementById("posts-tbody");
  const widths = ["70%", "90%", "60%", "80%", "75%", "85%"];
  tbody.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const tr = document.createElement("tr");
    tr.className = "skeleton-row";
    tr.innerHTML = `
      <td><div class="skeleton-bar" style="width:16px"></div></td>
      <td><div class="skeleton-bar" style="width:80%"></div></td>
      <td><div class="skeleton-bar" style="width:16px"></div></td>
      <td><div class="skeleton-bar" style="width:${widths[i % widths.length]}"></div></td>
      <td><div class="skeleton-bar" style="width:50%"></div></td>
      <td><div class="skeleton-bar" style="width:60%"></div></td>`;
    tbody.appendChild(tr);
  }
}

// Search results arrive as a fixed array; paging is off (searchMode).
async function loadFeed(overrideRows = null) {
  const tbody = document.getElementById("posts-tbody");
  const noPostsEl = document.getElementById("no-posts");
  noPostsEl.style.display = "none";
  document.getElementById("feed-loader").style.display = "none";

  feed = { offset: 0, loading: false, done: false, searchMode: !!overrideRows };
  kbIndex = -1;
  selectedPostIds.clear();
  updatePostsSelectAllState();

  if (overrideRows) {
    lastPosts = overrideRows;
    tbody.innerHTML = "";
    if (overrideRows.length === 0) { noPostsEl.style.display = "block"; return; }
    appendPosts(overrideRows);
    feed.done = true;
    return;
  }

  showSkeletons();
  try {
    const data = await apiFetch(buildFeedUrl(0));
    lastPosts = data || [];
    tbody.innerHTML = "";
    if (!data || data.length === 0) {
      noPostsEl.style.display = "block";
      feed.done = true;
      return;
    }
    appendPosts(data);
    feed.offset = data.length;
    feed.done = data.length < FEED_PAGE;
    ensureFeedObserver();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="table-message">${escHtml(t("posts.errLoading"))}${escHtml(e.message)}</td></tr>`;
  }
}

async function loadMorePosts() {
  if (feed.loading || feed.done || feed.searchMode) return;
  feed.loading = true;
  const moreEl = document.getElementById("feed-more");
  moreEl.style.display = "block";
  try {
    const data = await apiFetch(buildFeedUrl(feed.offset));
    if (!data || data.length === 0) {
      feed.done = true;
    } else {
      appendPosts(data);
      lastPosts = lastPosts.concat(data);
      feed.offset += data.length;
      if (data.length < FEED_PAGE) feed.done = true;
    }
  } catch (e) {
    toast(t("posts.errLoadingMore") + e.message, "error");
  } finally {
    feed.loading = false;
    moreEl.style.display = "none";
  }
}

function ensureFeedObserver() {
  const sentinel = document.getElementById("feed-sentinel");
  if (!sentinel) return;
  if (feedObserver) return;  // one observer for the lifetime of the page
  feedObserver = new IntersectionObserver(entries => {
    if (entries.some(en => en.isIntersecting)) loadMorePosts();
  }, { rootMargin: "300px" });
  feedObserver.observe(sentinel);
}

// Re-render the already-loaded posts in place (e.g. after a density change),
// without refetching or resetting pagination.
function renderPosts(data) {
  const tbody = document.getElementById("posts-tbody");
  tbody.innerHTML = "";
  appendPosts(data);
}

function appendPosts(data) {
  const tbody = document.getElementById("posts-tbody");
  data.forEach(post => {
    const { mainRow, detailRow } = renderPostRow(post);
    tbody.appendChild(mainRow);
    tbody.appendChild(detailRow);
  });
  updatePostsSelectAllState();
}

function renderPostRow(post) {
  const date = new Date(post.published_at).toLocaleDateString(localeDate(), { day: "2-digit", month: "2-digit" });
  const channelName = (post.channel_title || post.channel_username || "—");
  const channelShort = channelName.length > 24 ? channelName.slice(0, 22) + "…" : channelName;
  const rawText = (post.text || "").replace(/\*\*/g, "").replace(/\n/g, " ").trim();
  const previewLen = density === "compact" ? 70 : density === "expanded" ? 400 : 130;
  const preview = rawText.length > previewLen ? rawText.slice(0, previewLen - 2) + "…" : rawText;

  const simBadge = post.similarity != null
  ? `<span class="sim-badge">${Math.round((1 - post.similarity) * 100)}%</span>`
  : "";

  const hasSummary = !!post.summary;
  const hasEvents = post.events && (Array.isArray(post.events) ? post.events.length > 0 : Object.keys(post.events).length > 0);
  const dot1 = hasSummary ? "dot-green" : "dot-gray";
  const dot2 = hasEvents ? "dot-orange" : "dot-gray";

  const tgLink = post.channel_username
    ? `https://t.me/${post.channel_username}/${post.telegram_message_id}`
    : null;

  const dupBadge = (post.cluster_size && post.cluster_size > 1 && post.cluster_id != null)
    ? `<span class="dup-badge" data-cluster="${post.cluster_id}" title="${escHtml(t("posts.dupBadgeTitle", post.cluster_size))}">${escHtml(t("posts.dupBadge", post.cluster_size))}</span>`
    : "";

  const mainRow = document.createElement("tr");
  mainRow.className = "data-row" + (post.is_read ? " is-read" : "");
  mainRow.innerHTML = `
    <td class="cell-check"><input type="checkbox" class="post-row-check" ${selectedPostIds.has(post.id) ? "checked" : ""} /></td>
    <td class="cell-channel" title="${escHtml(channelName)}">${favStarHtml(post.is_favorite)}${escHtml(channelShort)}</td>
    <td><div class="cell-dots"><div class="dot ${dot1}"></div><div class="dot ${dot2}"></div></div></td>
    <td class="cell-post" title="${escHtml(rawText.slice(0, 300))}">${escHtml(preview)}</td>
    <td class="cell-topics">${post.category ? `<span class="topic-tag">${escHtml(categoryLabel(post.category))}</span>` : ""}${dupBadge}</td>
    <td class="cell-date">${simBadge} ${date}</td>
  `;

  const checkCell = mainRow.querySelector(".cell-check");
  checkCell.addEventListener("click", e => e.stopPropagation());
  mainRow.querySelector(".post-row-check").addEventListener("change", e => {
    if (e.target.checked) selectedPostIds.add(post.id);
    else selectedPostIds.delete(post.id);
    updatePostsSelectAllState();
  });

  wireFavStar(mainRow, post.id, -1, post.is_favorite, next => { post.is_favorite = next; });

  const badgeEl = mainRow.querySelector(".dup-badge");
  if (badgeEl) {
    badgeEl.addEventListener("click", e => {
      e.stopPropagation();  // don't toggle the row
      openClusterModal(post.cluster_id);
    });
  }

  const detailRow = document.createElement("tr");
  detailRow.className = "detail-row";

  const originalSafe = post.text ? escHtml(post.text.slice(0, 2000)) : "";
  const summaryBlock = post.summary ? `
    <div>
      <div class="detail-label">${escHtml(t("posts.summaryLabel"))}</div>
      <div class="detail-summary">${escHtml(post.summary)}</div>
    </div>` : "";
  const originalBlock = originalSafe ? `
    <div>
      <div class="detail-label">${escHtml(t("posts.originalLabel"))}</div>
      <div class="detail-original">${originalSafe}</div>
    </div>` : "";
  const safeTgLink = sanitizeUrl(tgLink);
  const linkBlock = safeTgLink ? `<a class="detail-link" href="${escHtml(safeTgLink)}" target="_blank" rel="noopener">${escHtml(t("posts.readMore"))}</a>` : "";

  detailRow.innerHTML = `<td colspan="6"><div class="detail-inner">${summaryBlock}${originalBlock}${linkBlock}</div></td>`;

  if (density === "expanded") {
    mainRow.classList.add("expanded");
    detailRow.classList.add("visible");
  }

  mainRow.addEventListener("click", () => {
    const open = detailRow.classList.contains("visible");
    mainRow.classList.toggle("expanded", !open);
    detailRow.classList.toggle("visible", !open);
    // Opening a post marks it read (once).
    if (!open && !post.is_read) markPostRead(post, mainRow);
  });

  return { mainRow, detailRow };
}

// ── Duplicate-cluster sources ───────────────────────────────────────────────
async function openClusterModal(clusterId) {
  const modal = document.getElementById("cluster-modal");
  const body = document.getElementById("cluster-modal-body");
  if (!modal || !body) return;
  body.innerHTML = `<div class='table-message'>${escHtml(t("common.loading"))}</div>`;
  modal.style.display = "flex";
  try {
    const rows = await apiFetch(`/posts/cluster/${clusterId}`);
    if (!rows || !rows.length) {
      body.innerHTML = `<div class='table-message'>${escHtml(t("cluster.empty"))}</div>`;
      return;
    }
    body.innerHTML = rows.map(r => {
      const name = escHtml(r.channel_title || r.channel_username || "—");
      const date = new Date(r.published_at).toLocaleString(localeDate(),
        { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
      const link = r.channel_username
        ? sanitizeUrl(`https://t.me/${r.channel_username}/${r.telegram_message_id}`)
        : null;
      const openLink = link
        ? `<a class="cluster-src-link" href="${escHtml(link)}" target="_blank" rel="noopener">${escHtml(t("cluster.openLink"))}</a>`
        : "";
      return `<div class="cluster-src">
        <div class="cluster-src-head">
          <span class="cluster-src-name">${name}</span>
          <span class="cluster-src-date">${date}</span>
        </div>
        ${r.summary ? `<div class="cluster-src-sum">${escHtml(r.summary)}</div>` : ""}
        ${openLink}
      </div>`;
    }).join("");
  } catch (e) {
    body.innerHTML = `<div class='table-message'>${escHtml(t("cluster.error"))}</div>`;
    toast(t("cluster.errToast") + e.message, "error");
  }
}

function closeClusterModal(e) {
  if (e && e.target && e.target.id !== "cluster-modal" && e.target.id !== "cluster-modal-close") return;
  const modal = document.getElementById("cluster-modal");
  if (modal) modal.style.display = "none";
}

// ── Favorites ────────────────────────────────────────────────────────────────
function favStarHtml(isFavorite) {
  return `<button type="button" class="fav-star${isFavorite ? " active" : ""}" title="${escHtml(t(isFavorite ? "posts.favRemove" : "posts.favAdd"))}">${isFavorite ? "★" : "☆"}</button>`;
}

// Wires the ★/☆ button rendered by favStarHtml() inside `rowEl` to toggle a
// post (eventIndex = -1) or a specific favorited event (eventIndex >= 0).
// `onChange(nextState)` lets the caller keep its in-memory item in sync so a
// later re-render of the same row (e.g. re-opening the detail panel) shows
// the current state without a full reload.
function wireFavStar(rowEl, postId, eventIndex, isFavorite, onChange) {
  const btn = rowEl.querySelector(".fav-star");
  if (!btn) return;
  let current = isFavorite;
  btn.addEventListener("click", async e => {
    e.stopPropagation();
    btn.disabled = true;
    try {
      const next = await toggleFavorite(postId, eventIndex);
      current = next;
      btn.classList.toggle("active", next);
      btn.textContent = next ? "★" : "☆";
      btn.title = t(next ? "posts.favRemove" : "posts.favAdd");
      if (onChange) onChange(next);
      toast(t(next ? "favorites.added" : "favorites.removed"), "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  });
  return () => current;
}

async function toggleFavorite(postId, eventIndex = -1) {
  const res = await apiFetch("/favorites/toggle", {
    method: "POST",
    body: JSON.stringify({ post_id: postId, event_index: eventIndex }),
  });
  return !!(res && res.is_favorite);
}

async function loadFavorites() {
  const list = document.getElementById("favorites-list");
  const loader = document.getElementById("favorites-loader");
  const empty = document.getElementById("favorites-empty");
  if (!list) return;
  list.innerHTML = "";
  loader.style.display = "block";
  empty.style.display = "none";

  const category = document.getElementById("fav-filter-category").value;

  try {
    const postsUrl = "/favorites/posts" + (category ? `?category=${encodeURIComponent(category)}` : "");
    const [posts, eventsRes] = await Promise.all([
      apiFetch(postsUrl),
      apiFetch("/favorites/events"),
    ]);
    loader.style.display = "none";

    let events = (eventsRes && eventsRes.events) || [];
    if (category) events = events.filter(ev => ev.post_category === category);

    if ((!posts || posts.length === 0) && events.length === 0) {
      empty.style.display = "block";
      return;
    }

    renderFavoritesList(list, posts || [], events);
  } catch (e) {
    loader.style.display = "none";
    list.innerHTML = `<div class="table-message">${escHtml(t("favorites.errLoading"))}${escHtml(e.message)}</div>`;
  }
}

function renderFavoritesList(container, posts, events) {
  const byCategory = new Map();
  const bucket = cat => {
    const key = cat || "Прочее";
    if (!byCategory.has(key)) byCategory.set(key, { posts: [], events: [] });
    return byCategory.get(key);
  };
  posts.forEach(p => bucket(p.category).posts.push(p));
  events.forEach(ev => bucket(ev.post_category).events.push(ev));

  for (const [category, items] of byCategory) {
    const group = document.createElement("div");
    group.className = "fav-group";
    group.innerHTML = `<h3 class="fav-group-title">${escHtml(categoryLabel(category))}</h3>`;

    if (items.posts.length) {
      const sub = document.createElement("div");
      sub.className = "fav-subgroup-title";
      sub.textContent = t("favorites.posts");
      group.appendChild(sub);
      items.posts.forEach(post => group.appendChild(renderFavoritePostCard(post)));
    }
    if (items.events.length) {
      const sub = document.createElement("div");
      sub.className = "fav-subgroup-title";
      sub.textContent = t("favorites.events");
      group.appendChild(sub);
      items.events.forEach(ev => group.appendChild(renderFavoriteEventCard(ev)));
    }
    container.appendChild(group);
  }
}

function renderFavoritePostCard(post) {
  const card = document.createElement("div");
  card.className = "fav-card";
  const channelName = post.channel_title || post.channel_username || "—";
  const summary = (post.summary || post.text || "").slice(0, 200);
  const date = new Date(post.published_at).toLocaleDateString(localeDate(), { day: "2-digit", month: "2-digit", year: "numeric" });
  const tgLink = post.channel_username ? sanitizeUrl(`https://t.me/${post.channel_username}/${post.telegram_message_id}`) : null;
  card.innerHTML = `
    ${favStarHtml(true)}
    <div class="fav-card-body">
      <div class="fav-card-head"><b>${escHtml(channelName)}</b> <span class="fav-card-date">${date}</span></div>
      <div class="fav-card-text">${escHtml(summary)}</div>
      ${tgLink ? `<a class="detail-link" href="${escHtml(tgLink)}" target="_blank" rel="noopener">${escHtml(t("posts.readMore"))}</a>` : ""}
    </div>
  `;
  wireFavStar(card, post.id, -1, true, next => { if (!next) card.remove(); });
  return card;
}

function renderFavoriteEventCard(ev) {
  const card = document.createElement("div");
  card.className = "fav-card";
  const date = ev.date
    ? new Date(ev.date + "T00:00:00").toLocaleDateString(localeDate(), { day: "2-digit", month: "2-digit", year: "numeric" })
    : "—";
  const safeEvLink = sanitizeUrl(ev.link);
  card.innerHTML = `
    ${favStarHtml(true)}
    <div class="fav-card-body">
      <div class="fav-card-head"><b>${escHtml(ev.name || "—")}</b> <span class="fav-card-date">${date}${ev.time ? " " + escHtml(ev.time) : ""}</span></div>
      <div class="fav-card-text">${escHtml(ev.channel_title || "")}${ev.location ? " · " + escHtml(ev.location) : ""}</div>
      ${safeEvLink ? `<a class="detail-link" href="${escHtml(safeEvLink)}" target="_blank" rel="noopener">${escHtml(t("events.readMore"))}</a>` : ""}
    </div>
  `;
  wireFavStar(card, ev.post_id, ev.event_index, true, next => { if (!next) card.remove(); });
  return card;
}

// ── Unread tracking ───────────────────────────────────────────────────────────
async function markPostRead(post, rowEl) {
  post.is_read = true;
  rowEl.classList.add("is-read");
  adjustUnreadBadge(-1);
  try {
    await apiFetch("/posts/mark-read", {
      method: "POST",
      body: JSON.stringify({ post_ids: [post.id] }),
    });
  } catch {
    // Non-fatal — the row already shows as read; the count re-syncs on reload.
  }
}

async function refreshUnreadCount() {
  try {
    const data = await apiFetch("/posts/unread-count");
    setUnreadBadge(data ? data.count : 0);
  } catch { /* leave the badge as-is on a transient error */ }
}

function setUnreadBadge(n) {
  const el = document.getElementById("unread-badge");
  if (!el) return;
  el.textContent = n > 99 ? "99+" : String(n);
  el.style.display = n > 0 ? "inline-flex" : "none";
}

function adjustUnreadBadge(delta) {
  const el = document.getElementById("unread-badge");
  if (!el) return;
  const cur = parseInt(el.textContent, 10) || 0;
  setUnreadBadge(Math.max(0, cur + delta));
}

async function markAllRead() {
  try {
    let url = "/posts/mark-all-read";
    const params = [];
    if (filters.category) params.push(`category=${encodeURIComponent(filters.category)}`);
    if (filters.channelId) params.push(`channel_id=${filters.channelId}`);
    if (params.length) url += "?" + params.join("&");
    const res = await apiFetch(url, { method: "POST" });
    toast(t("posts.markedReadCount", res ? res.marked : 0), "success");
    await refreshUnreadCount();
    loadFeed();
  } catch (e) {
    toast(t("posts.markReadFailed") + e.message, "error");
  }
}

function escHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Only allow http(s) URLs in href attributes — blocks javascript:/data: XSS
// from untrusted content (e.g. links extracted by the AI from post text).
function sanitizeUrl(url) {
  if (!url) return null;
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.href;
    }
  } catch {
    return null;
  }
  return null;
}

// ── Search ────────────────────────────────────────────────────────────────────

async function runSearch() {
  const q = document.getElementById("search-input").value.trim();
  if (!q) { loadFeed(); return; }
  try {
    const results = await apiFetch(`/posts/semantic-search?q=${encodeURIComponent(q)}&limit=80`);
    loadFeed(results);
  } catch (e) {
    toast(t("posts.errSearch") + e.message, "error");
  }
}

// ── Channels dropdown ─────────────────────────────────────────────────────────

async function loadChannelsDropdown() {
  try {
    const data = await apiFetch("/channels/");
    const sel = document.getElementById("filter-channel");
    while (sel.options.length > 1) sel.remove(1);
    if (data) {
      data.forEach(ch => {
        const opt = document.createElement("option");
        opt.value = ch.id;
        opt.textContent = ch.title || ch.username || ch.telegram_id;
        sel.appendChild(opt);
      });
    }
  } catch (e) {
    console.error("Channels dropdown error:", e);
  }
}

// ── Statistics ────────────────────────────────────────────────────────────────

async function loadStats() {
  const loader = document.getElementById("stats-loader");
  const daysSel = document.getElementById("stats-days");
  const days = daysSel ? daysSel.value : 30;
  if (loader) loader.style.display = "block";
  try {
    const data = await apiFetch(`/stats/overview?days=${days}`);
    if (loader) loader.style.display = "none";
    if (!data) return;
    renderStatCards(data.totals);
    renderDayChart(data.per_day);
    renderBarList("stats-percat", data.per_category, r => r.category);
    renderBarList("stats-perchan", data.per_channel, r => r.title || r.username || "—");
  } catch (e) {
    if (loader) loader.style.display = "none";
    toast(t("stats.errLoading") + e.message, "error");
  }
}

function renderStatCards(totals) {
  const el = document.getElementById("stats-cards");
  if (!el || !totals) return;
  const cards = [
    { label: t("stats.cardPosts"), value: totals.posts, accent: false },
    { label: t("stats.cardUnread"), value: totals.unread, accent: true },
    { label: t("stats.cardEvents"), value: totals.events, accent: false },
    { label: t("stats.cardChannels"), value: totals.channels, accent: false },
  ];
  el.innerHTML = cards.map(c => `
    <div class="stat-card${c.accent ? " accent" : ""}">
      <div class="stat-value">${c.value}</div>
      <div class="stat-label">${c.label}</div>
    </div>`).join("");
}

function renderDayChart(days) {
  const el = document.getElementById("stats-perday");
  if (!el) return;
  if (!days || !days.length) { el.innerHTML = `<span style='color:var(--muted);font-size:13px'>${escHtml(t("stats.noData"))}</span>`; return; }
  const max = Math.max(1, ...days.map(d => d.count));
  el.innerHTML = days.map(d => {
    const pct = (d.count / max) * 100;
    const label = new Date(d.date + "T00:00:00").toLocaleDateString(localeDate(), { day: "numeric", month: "short" });
    return `<div class="day-bar" title="${label}: ${d.count}">
      <div class="day-tip">${label}: ${d.count}</div>
      <div class="day-fill" style="height:${pct}%"></div>
    </div>`;
  }).join("");
}

function renderBarList(elId, rows, nameFn) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!rows || !rows.length) { el.innerHTML = `<span style='color:var(--muted);font-size:13px'>${escHtml(t("stats.noData"))}</span>`; return; }
  const max = Math.max(1, ...rows.map(r => r.count));
  el.innerHTML = rows.map(r => {
    const pct = (r.count / max) * 100;
    return `<div class="bar-row">
      <span class="bar-name" title="${escHtml(nameFn(r))}">${escHtml(nameFn(r))}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
      <span class="bar-count">${r.count}</span>
    </div>`;
  }).join("");
}

// ── Assistant (RAG chat) ───────────────────────────────────────────────────────

let chatBusy = false;

function appendChatMessage(role, innerHtml) {
  const box = document.getElementById("chat-messages");
  const empty = document.getElementById("chat-empty");
  if (empty) empty.remove();
  const msg = document.createElement("div");
  msg.className = "chat-msg chat-msg-" + role;
  msg.innerHTML = innerHtml;
  box.appendChild(msg);
  box.scrollTop = box.scrollHeight;
  return msg;
}

// Turn [N] citations in the answer into clickable chips scrolling to the source.
function linkifyCitations(text) {
  return escHtml(text).replace(/\[(\d+)\]/g,
    (m, n) => `<a class="cite" href="#" data-cite="${n}">[${n}]</a>`);
}

function renderChatSources(sources) {
  if (!sources || !sources.length) return "";
  const items = sources.map((s, i) => {
    const n = i + 1;
    const name = escHtml(s.channel_title || s.channel_username || "—");
    const date = s.published_at
      ? new Date(s.published_at).toLocaleDateString(localeDate(), { day: "2-digit", month: "2-digit", year: "numeric" })
      : "";
    const link = s.channel_username
      ? sanitizeUrl(`https://t.me/${s.channel_username}/${s.telegram_message_id}`)
      : null;
    const nameHtml = link
      ? `<a href="${escHtml(link)}" target="_blank" rel="noopener">${name}</a>`
      : name;
    const snippet = s.snippet ? escHtml(s.snippet.slice(0, 220)) : "";
    return `<div class="chat-src" data-src="${n}">
      <span class="chat-src-n">[${n}]</span>
      <div class="chat-src-body">
        <div class="chat-src-head">${nameHtml} <span class="chat-src-date">${date}</span></div>
        <div class="chat-src-snip">${snippet}</div>
      </div>
    </div>`;
  }).join("");
  return `<div class="chat-sources"><div class="chat-sources-label">${escHtml(t("chat.sources"))}</div>${items}</div>`;
}

async function sendChatQuestion() {
  const input = document.getElementById("chat-input");
  const q = input.value.trim();
  if (!q || chatBusy) return;
  chatBusy = true;
  input.value = "";
  appendChatMessage("user", escHtml(q));
  const thinking = appendChatMessage("bot", `<span class='chat-thinking'>${escHtml(t("chat.thinking"))}</span>`);
  try {
    const res = await apiFetch("/chat/ask", {
      method: "POST",
      body: JSON.stringify({ question: q }),
    });
    thinking.remove();
    const answer = (res && res.answer) ? res.answer : t("chat.noAnswer");
    const bot = appendChatMessage("bot",
      `<div class="chat-answer">${linkifyCitations(answer)}</div>${renderChatSources(res && res.sources)}`);
    bot.querySelectorAll(".cite").forEach(a => {
      a.addEventListener("click", e => {
        e.preventDefault();
        const el = bot.querySelector(`.chat-src[data-src="${a.dataset.cite}"]`);
        if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("cite-flash"); setTimeout(() => el.classList.remove("cite-flash"), 1200); }
      });
    });
  } catch (e) {
    thinking.remove();
    appendChatMessage("bot", `<span class='chat-error'>${escHtml(t("chat.error"))}${escHtml(e.message)}</span>`);
  } finally {
    chatBusy = false;
    input.focus();
  }
}

// ── Events ────────────────────────────────────────────────────────────────────

function resetEventFilters() {
  document.getElementById("ev-date-from").value = "";
  document.getElementById("ev-date-to").value = "";
  document.getElementById("ev-filter-topic").value = "";
  document.getElementById("ev-filter-type").value = "";
  document.getElementById("ev-search-input").value = "";
  loadEvents();
}

async function loadEvents() {
  const tbody = document.getElementById("events-tbody");
  const loader = document.getElementById("events-loader");
  const noEvEl = document.getElementById("no-events");
  if (!tbody) return;
  tbody.innerHTML = "";
  loader.style.display = "block";
  noEvEl.style.display = "none";

  const dateFrom = document.getElementById("ev-date-from").value;
  const dateTo = document.getElementById("ev-date-to").value;
  const evType = document.getElementById("ev-filter-type").value;
  const topicFilter = document.getElementById("ev-filter-topic").value;

  let url = "/digest/events?days_ahead=365";
  if (dateFrom) url += `&date_from=${dateFrom}`;
  if (dateTo) url += `&date_to=${dateTo}`;
  if (evType) url += `&event_type=${encodeURIComponent(evType)}`;

  try {
    const data = await apiFetch(url);
    loader.style.display = "none";
    let events = (data && data.events) ? data.events : [];

    // Client-side topic filter
    if (topicFilter) {
      events = events.filter(ev => {
        const topics = ev.topics || [];
        return topics.some(t => t.toLowerCase().includes(topicFilter.toLowerCase()));
      });
    }

    // Assign a stable per-load key so checkboxes survive re-renders from the search box.
    events.forEach((ev, i) => { ev._evKey = `${i}:${ev.name || ""}:${ev.date || ""}`; });
    allLoadedEvents = events;
    selectedEventKeys.clear();

    // Populate topic dropdown from loaded events (first load only)
    populateTopicsDropdown(data.events || []);

    applyEventSearch();
  } catch (e) {
    loader.style.display = "none";
    tbody.innerHTML = `<tr><td colspan="9" class="table-message">${escHtml(t("events.errLoading"))}${escHtml(e.message)}</td></tr>`;
  }
}

// Free-text client-side search over the already-loaded/filtered events, plus
// re-render (the events endpoint has no server-side text search like /posts/search).
function applyEventSearch() {
  const tbody = document.getElementById("events-tbody");
  const noEvEl = document.getElementById("no-events");
  if (!tbody) return;

  const q = document.getElementById("ev-search-input").value.trim().toLowerCase();
  let events = allLoadedEvents;
  if (q) {
    events = events.filter(ev => {
      const haystack = [
        ev.name, ev.location, ev.channel_title,
        ...(ev.topics || []), ...(ev.speakers || []), ...(ev.partners || []),
      ].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }

  lastEvents = events;  // what's currently shown — the .ics export uses this
  tbody.innerHTML = "";

  if (events.length === 0) {
    noEvEl.style.display = "block";
    updateEventsSelectAllState();
    return;
  }
  noEvEl.style.display = "none";

  events.forEach(ev => {
    const { mainRow, detailRow } = renderEventRow(ev);
    tbody.appendChild(mainRow);
    tbody.appendChild(detailRow);
  });
  updateEventsSelectAllState();
}

function toggleAllEventsSelected(e) {
  const checked = e.target.checked;
  lastEvents.forEach(ev => {
    if (checked) selectedEventKeys.add(ev._evKey);
    else selectedEventKeys.delete(ev._evKey);
  });
  document.querySelectorAll(".ev-row-check").forEach(cb => { cb.checked = checked; });
}

function updateEventsSelectAllState() {
  const selectAll = document.getElementById("ev-select-all");
  if (!selectAll) return;
  const visibleKeys = lastEvents.map(ev => ev._evKey);
  const selectedVisible = visibleKeys.filter(k => selectedEventKeys.has(k));
  selectAll.checked = visibleKeys.length > 0 && selectedVisible.length === visibleKeys.length;
  selectAll.indeterminate = selectedVisible.length > 0 && selectedVisible.length < visibleKeys.length;
}

// ── Export events to an .ics calendar file ────────────────────────────────────
function _icsEscape(s) {
  return String(s || "")
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r?\n/g, "\\n");
}

function _icsDate(dateStr, timeStr) {
  // dateStr is ISO "YYYY-MM-DD". timeStr may be "HH:MM" (freeform, optional).
  const ymd = (dateStr || "").replace(/-/g, "");
  if (!ymd || ymd.length !== 8) return null;
  const m = /^(\d{1,2}):(\d{2})/.exec(timeStr || "");
  if (m) {
    const hh = m[1].padStart(2, "0");
    return { value: `${ymd}T${hh}${m[2]}00`, allDay: false };
  }
  return { value: ymd, allDay: true };
}

function buildIcs(events) {
  const now = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//SumPoint//Events//RU",
    "CALSCALE:GREGORIAN",
  ];
  let count = 0;
  events.forEach((ev, i) => {
    const dt = _icsDate(ev.date, ev.time);
    if (!dt) return;  // skip events without a usable date
    count++;
    const descParts = [];
    if (ev.location) descParts.push(t("events.icsLocation") + ev.location);
    if (ev.channel_title) descParts.push(t("events.icsChannel") + ev.channel_title);
    if ((ev.speakers || []).length) descParts.push(t("events.icsSpeakers") + ev.speakers.join(", "));
    if (ev.link) descParts.push(ev.link);
    lines.push("BEGIN:VEVENT");
    lines.push(`UID:sumpoint-${Date.now()}-${i}@sumpoint`);
    lines.push(`DTSTAMP:${now}`);
    lines.push(dt.allDay ? `DTSTART;VALUE=DATE:${dt.value}` : `DTSTART:${dt.value}`);
    lines.push("SUMMARY:" + _icsEscape(ev.name || t("events.icsFallbackName")));
    if (ev.location) lines.push("LOCATION:" + _icsEscape(ev.location));
    if (descParts.length) lines.push("DESCRIPTION:" + _icsEscape(descParts.join("\n")));
    lines.push("END:VEVENT");
  });
  lines.push("END:VCALENDAR");
  return { text: lines.join("\r\n"), count };
}

function exportEventsIcs() {
  if (!lastEvents || lastEvents.length === 0) {
    toast(t("events.noneToExport"), "error");
    return;
  }
  // Export just the checked events if any are checked, otherwise everything currently shown.
  const selected = lastEvents.filter(ev => selectedEventKeys.has(ev._evKey));
  const toExport = selected.length > 0 ? selected : lastEvents;
  const { text, count } = buildIcs(toExport);
  if (count === 0) {
    toast(t("events.noRecognizedDates"), "error");
    return;
  }
  const blob = new Blob([text], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "sumpoint-events.ics";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  toast(t("events.exportedCount", count), "success");
}

function populateTopicsDropdown(events) {
  const sel = document.getElementById("ev-filter-topic");
  const current = sel.value;
  const allTopics = new Set();
  events.forEach(ev => (ev.topics || []).forEach(t => allTopics.add(t)));
  while (sel.options.length > 1) sel.remove(1);
  [...allTopics].sort().forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    sel.appendChild(opt);
  });
  sel.value = current;
}

function renderEventRow(ev) {
  const dateStr = ev.date
    ? new Date(ev.date + "T00:00:00").toLocaleDateString(localeDate(), { day: "2-digit", month: "2-digit", year: "numeric" })
    : "—";
  const timeStr = ev.time || "";
  const name = ev.name || "—";
  const topics = (ev.topics || []).slice(0, 3).map(tp => `<span class="ev-topic-tag">${escHtml(tp)}</span>`).join(" ");
  const evType = ev.type ? `<span class="ev-type-badge">${escHtml(eventTypeLabel(ev.type))}</span>` : "";
  const location = ev.location ? escHtml(ev.location) : "";
  const speakers = (ev.speakers || []).join(", ");
  const partners = (ev.partners || []).join(", ");
  const mentions = ev.mentions || 1;
  const safeEvLink = sanitizeUrl(ev.link);

  const mainRow = document.createElement("tr");
  mainRow.className = "data-row";
  mainRow.innerHTML = `
    <td class="cell-evcheck"><input type="checkbox" class="ev-row-check" ${selectedEventKeys.has(ev._evKey) ? "checked" : ""} /></td>
    <td class="cell-evdate">${dateStr}${timeStr ? `<br><span class="ev-time">${timeStr}</span>` : ""}</td>
    <td class="cell-evname">
      <span class="ev-expand-icon">&#9660;</span>
      ${favStarHtml(ev.is_favorite)}
      ${safeEvLink ? `<a class="ev-name-link" href="${escHtml(safeEvLink)}" target="_blank" rel="noopener">${escHtml(name)}</a>` : escHtml(name)}
    </td>
    <td class="cell-evtopics">${topics}</td>
    <td>${evType}</td>
    <td class="cell-evlocation" title="${escHtml(ev.location || "")}">${location}</td>
    <td class="cell-evspeakers" title="${escHtml(speakers)}">${escHtml(speakers.slice(0, 40))}${speakers.length > 40 ? "…" : ""}</td>
    <td class="cell-evpartners" title="${escHtml(partners)}">${escHtml(partners.slice(0, 40))}${partners.length > 40 ? "…" : ""}</td>
    <td class="cell-evmentions">${mentions}</td>
  `;

  const checkCell = mainRow.querySelector(".cell-evcheck");
  checkCell.addEventListener("click", e => e.stopPropagation());

  if (ev.post_id != null && ev.event_index != null) {
    wireFavStar(mainRow, ev.post_id, ev.event_index, ev.is_favorite, next => { ev.is_favorite = next; });
  }
  mainRow.querySelector(".ev-row-check").addEventListener("change", e => {
    if (e.target.checked) selectedEventKeys.add(ev._evKey);
    else selectedEventKeys.delete(ev._evKey);
    updateEventsSelectAllState();
  });

  const detailRow = document.createElement("tr");
  detailRow.className = "detail-row";
  const channelInfo = ev.channel_title ? `<b>${escHtml(ev.channel_title)}</b>` : "";
  const allTopics = (ev.topics || []).map(tp => `<span class="ev-topic-tag">${escHtml(tp)}</span>`).join(" ");
  const fullSpeakers = (ev.speakers || []).length > 0
    ? `<div class="detail-label">${escHtml(t("events.detailSpeakers"))}</div><div>${escHtml((ev.speakers || []).join(", "))}</div>` : "";
  const fullPartners = (ev.partners || []).length > 0
    ? `<div class="detail-label">${escHtml(t("events.detailPartners"))}</div><div>${escHtml((ev.partners || []).join(", "))}</div>` : "";
  const linkBlock = safeEvLink
    ? `<a class="detail-link" href="${escHtml(safeEvLink)}" target="_blank" rel="noopener">${escHtml(t("events.readMore"))}</a>` : "";

  detailRow.innerHTML = `<td colspan="9"><div class="detail-inner ev-detail-inner">
    <div style="display:flex;gap:24px;flex-wrap:wrap">
      ${channelInfo ? `<div><div class="detail-label">${escHtml(t("events.detailChannel"))}</div><div>${channelInfo}</div></div>` : ""}
      ${ev.location ? `<div><div class="detail-label">${escHtml(t("events.detailLocation"))}</div><div>${escHtml(ev.location)}</div></div>` : ""}
      ${ev.date ? `<div><div class="detail-label">${escHtml(t("events.detailDateTime"))}</div><div>${dateStr}${timeStr ? " " + timeStr : ""}</div></div>` : ""}
    </div>
    ${allTopics ? `<div><div class="detail-label">${escHtml(t("events.detailTopics"))}</div><div style="display:flex;gap:4px;flex-wrap:wrap">${allTopics}</div></div>` : ""}
    ${fullSpeakers}
    ${fullPartners}
    ${linkBlock}
  </div></td>`;

  mainRow.addEventListener("click", () => {
    const open = detailRow.classList.contains("visible");
    mainRow.querySelector(".ev-expand-icon").innerHTML = open ? "&#9660;" : "&#9650;";
    mainRow.classList.toggle("expanded", !open);
    detailRow.classList.toggle("visible", !open);
  });

  return { mainRow, detailRow };
}

// ── Channels ──────────────────────────────────────────────────────────────────

function _fmtAgo(iso) {
  if (!iso) return t("time.never");
  const then = new Date(iso).getTime();
  if (isNaN(then)) return "—";
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return t("time.justNow");
  if (mins < 60) return t("time.minAgo", mins);
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return t("time.hoursAgo", hrs);
  const days = Math.floor(hrs / 24);
  return t("time.daysAgo", days);
}

function _healthState(ch) {
  // err > stale (>24h since last fetch) > empty (never produced posts) > ok
  if (ch.last_error) return "err";
  if (!ch.last_fetched_at) return "empty";
  const ageH = (Date.now() - new Date(ch.last_fetched_at).getTime()) / 3600000;
  if (ageH > 24) return "stale";
  if (ch.post_count === 0) return "empty";
  return "ok";
}

async function loadChannels() {
  const list = document.getElementById("channels-list");
  if (!list) return;
  try {
    const data = await apiFetch("/stats/channel-health");
    list.innerHTML = "";
    if (!data || data.length === 0) {
      list.innerHTML = `<li style='color:var(--muted);font-size:13px;padding:10px 0;'>${escHtml(t("channels.empty"))}</li>`;
      return;
    }
    data.forEach(ch => {
      const state = _healthState(ch);
      const li = document.createElement("li");
      li.className = "channel-item health";
      const errBlock = ch.last_error
        ? `<div class="channel-health-err" title="${escHtml(ch.last_error)}">⚠ ${escHtml(ch.last_error)}</div>`
        : "";
      const offBadge = ch.is_active === false
        ? `<span class="ch-off-badge">${escHtml(t("channels.off"))}</span>` : "";
      const toggleLabel = ch.is_active === false ? t("channels.enable") : t("channels.disable");
      const toggleBtn = `<button class="btn-ghost-sm ch-toggle" data-action="toggle-channel" data-id="${ch.channel_id}">${escHtml(toggleLabel)}</button>`;
      li.innerHTML = `
        <div class="channel-health-top">
          <span class="ch-dot ${state}" title="${state}"></span>
          <span class="channel-item-name">${escHtml(ch.title || ch.username || String(ch.channel_id))}</span>
          ${offBadge}
          ${toggleBtn}
          <button class="channel-remove" data-action="remove-channel" data-id="${ch.channel_id}">✕</button>
        </div>
        <div class="channel-health-meta">
          <span>${escHtml(t("channels.postsLabel"))}<b>${ch.post_count}</b></span>
          <span>${escHtml(t("channels.unreadLabel"))}<b>${ch.unread_count}</b></span>
          <span>${escHtml(t("channels.fetchLabel"))}<b>${_fmtAgo(ch.last_fetched_at)}</b></span>
        </div>
        ${errBlock}
      `;
      list.appendChild(li);
    });
  } catch (e) {
    console.error("Channels error:", e);
  }
}

async function addChannel() {
  const input = document.getElementById("channel-input");
  const val = input.value.trim();
  if (!val) return;
  const isNumeric = /^-?\d+$/.test(val);
  const clean = val.replace(/^@/, "");
  const body = isNumeric
    ? { telegram_id: parseInt(val), username: null, title: val }
    : { telegram_id: 0, username: clean, title: clean };
  try {
    await apiFetch("/channels/", { method: "POST", body: JSON.stringify(body) });
    input.value = "";
    loadChannels();
    loadChannelsDropdown();
  } catch (e) {
    toast(t("channels.errAdd") + e.message, "error");
  }
}

async function toggleChannel(id) {
  try {
    await apiFetch(`/channels/${id}/toggle`, { method: "POST" });
    loadChannels();
    loadChannelsDropdown();
  } catch (e) {
    toast(t("channels.errToggle") + e.message, "error");
  }
}

async function removeChannel(id) {
  try {
    const resp = await fetch(`${API}/channels/${id}`, { method: "DELETE", credentials: "include", headers: authHeaders() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    loadChannels();
    loadChannelsDropdown();
  } catch (e) {
    toast(t("channels.errRemove") + e.message, "error");
  }
}

async function importChannels() {
  const btn = document.getElementById("import-btn");
  btn.disabled = true;
  btn.textContent = t("channels.importing");
  try {
    const data = await apiFetch("/channels/import", { method: "POST" });
    await loadChannels();
    await loadChannelsDropdown();
    btn.textContent = t("channels.importedCount", data.imported, data.total);
    setTimeout(() => { btn.textContent = t("channels.import"); btn.disabled = false; }, 3000);
  } catch (e) {
    toast(t("channels.errImport") + e.message, "error");
    btn.textContent = t("channels.import");
    btn.disabled = false;
  }
}

async function syncChannels() {
  const btn = document.getElementById("sync-btn");
  btn.disabled = true;
  btn.textContent = t("channels.syncing");
  try {
    await apiFetch("/channels/sync", { method: "POST" });
    setTimeout(() => { loadFeed(); loadChannels(); }, 3000);
  } catch (e) {
    toast(t("channels.errSync") + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = t("channels.sync");
  }
}

// ── Digest ────────────────────────────────────────────────────────────────────

async function generateDigest() {
  const btn = document.getElementById("gen-digest-btn");
  const box = document.getElementById("digest-box");
  btn.disabled = true;
  btn.textContent = t("digest.generating");
  box.style.display = "none";
  try {
    const data = await apiFetch("/digest/?hours=24");
    box.textContent = data.digest_markdown || t("digest.empty");
    box.style.display = "block";
  } catch (e) {
    box.textContent = t("digest.error") + e.message;
    box.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = t("digest.generate");
  }
}

// ── Schedule ──────────────────────────────────────────────────────────────────

function _typeLabel(v) {
  return { topics: t("schedType.topics"), events: t("schedType.events"), collect: t("schedType.collect") }[v] || v;
}

async function loadSchedule() {
  const tbody = document.getElementById("sched-tbody");
  const loader = document.getElementById("sched-loader");
  const empty = document.getElementById("sched-empty");
  tbody.innerHTML = "";
  loader.style.display = "block";
  empty.style.display = "none";

  try {
    const data = await apiFetch("/schedule/");
    loader.style.display = "none";
    lastSchedules = data || [];
    if (!data || data.length === 0) { empty.style.display = "block"; return; }
    data.forEach(s => tbody.appendChild(renderSchedRow(s)));
  } catch (e) {
    loader.style.display = "none";
    tbody.innerHTML = `<tr><td colspan="7" class="table-message">${escHtml(t("schedule.error"))}${escHtml(e.message)}</td></tr>`;
  }
}

function renderSchedRow(s) {
  const tr = document.createElement("tr");
  const typeLabel = _typeLabel(s.schedule_type);
  const topicsLabel = (s.categories && s.categories.length > 0) ? s.categories.length : t("schedule.all");
  const lastRun = s.last_run_at
    ? new Date(s.last_run_at).toLocaleString(localeDate(), { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : "—";

  tr.innerHTML = `
    <td class="sched-name">${escHtml(s.name)}</td>
    <td><span class="type-badge ${s.schedule_type}">${escHtml(typeLabel)}</span></td>
    <td class="cron-text">${escHtml(s.cron_expr)}</td>
    <td class="last-run">${topicsLabel}</td>
    <td>
      <button class="status-btn ${s.status}" data-action="toggle-schedule" data-id="${s.id}">
        ${s.status === "active" ? escHtml(t("schedule.active")) : escHtml(t("schedule.paused"))}
      </button>
    </td>
    <td class="last-run">${lastRun}</td>
    <td>
      <button class="row-edit-btn" data-action="edit-schedule" data-id="${s.id}" title="${escHtml(t("schedule.edit"))}">✎</button>
      <button class="row-del-btn" data-action="delete-schedule" data-id="${s.id}" title="Delete">✕</button>
    </td>
  `;
  return tr;
}

async function toggleSchedule(id, btn) {
  try {
    const data = await apiFetch(`/schedule/${id}/toggle`, { method: "POST" });
    if (!data) return;
    btn.className = `status-btn ${data.status}`;
    btn.textContent = data.status === "active" ? t("schedule.active") : t("schedule.paused");
  } catch (e) {
    toast(t("schedule.error") + e.message, "error");
  }
}

async function deleteSchedule(id) {
  if (!confirm(t("schedule.deleteConfirm"))) return;
  try {
    const resp = await fetch(`${API}/schedule/${id}`, { method: "DELETE", credentials: "include", headers: authHeaders() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    loadSchedule();
  } catch (e) {
    toast(t("schedule.error") + e.message, "error");
  }
}

// Modal

function openSchedModal(editId = null) {
  const sched = editId != null ? lastSchedules.find(s => s.id === editId) : null;
  schedEditId = sched ? sched.id : null;

  document.getElementById("sched-modal").style.display = "flex";
  document.getElementById("modal-sched-title").textContent = t(sched ? "modal.schedule.editTitle" : "modal.schedule.title");
  document.getElementById("sched-create-btn").textContent = t(sched ? "modal.save" : "modal.create");

  document.getElementById("m-name").value = sched ? sched.name : "";

  const cronPresetSel = document.getElementById("m-cron-preset");
  const cronExpr = sched ? sched.cron_expr : "0 9 * * *";
  const isKnownPreset = Array.from(cronPresetSel.options).some(o => o.value === cronExpr);
  cronPresetSel.value = isKnownPreset ? cronExpr : "custom";
  document.getElementById("m-cron-custom").style.display = isKnownPreset ? "none" : "block";
  document.getElementById("m-cron-custom").value = isKnownPreset ? "" : cronExpr;

  const type = sched ? sched.schedule_type : "topics";
  document.querySelectorAll(".type-btn").forEach(b => b.classList.toggle("active", b.dataset.type === type));
  document.getElementById("m-topics-section").style.display = type === "topics" ? "flex" : "none";

  const hours = sched ? String(sched.hours_back) : "24";
  const hoursRadio = document.querySelector(`input[name='m-hours'][value='${hours}']`);
  (hoursRadio || document.querySelector("input[name='m-hours'][value='24']")).checked = true;

  if (sched && sched.model) document.getElementById("m-model").value = sched.model;

  const activeCats = new Set(sched && sched.categories ? sched.categories : []);
  document.querySelectorAll("#m-categories input").forEach(cb => { cb.checked = activeCats.has(cb.value); });
}

function closeSchedModal(e) {
  if (!e || e.target === document.getElementById("sched-modal")) {
    document.getElementById("sched-modal").style.display = "none";
    schedEditId = null;
  }
}

function selectType(btn) {
  document.querySelectorAll(".type-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  const isTopics = btn.dataset.type === "topics";
  document.getElementById("m-topics-section").style.display = isTopics ? "flex" : "none";
}

function onPresetChange(sel) {
  const custom = document.getElementById("m-cron-custom");
  custom.style.display = sel.value === "custom" ? "block" : "none";
}

async function saveSchedule() {
  const name = document.getElementById("m-name").value.trim();
  if (!name) { toast(t("schedule.nameRequired"), "error"); return; }

  const schedule_type = document.querySelector(".type-btn.active")?.dataset.type || "topics";

  const presetSel = document.getElementById("m-cron-preset");
  const cron_expr = presetSel.value === "custom"
    ? document.getElementById("m-cron-custom").value.trim()
    : presetSel.value;
  if (!cron_expr) { toast(t("schedule.cronRequired"), "error"); return; }

  const hoursRadio = document.querySelector("input[name='m-hours']:checked");
  const hours_back = hoursRadio ? parseInt(hoursRadio.value) : 24;
  const model = document.getElementById("m-model").value;
  const checkedCats = Array.from(document.querySelectorAll("#m-categories input:checked")).map(cb => cb.value);

  const body = JSON.stringify({
    name, schedule_type, cron_expr, hours_back, model,
    categories: checkedCats.length > 0 ? checkedCats : null,
  });

  try {
    if (schedEditId != null) {
      await apiFetch(`/schedule/${schedEditId}`, { method: "PUT", body });
    } else {
      await apiFetch("/schedule/", { method: "POST", body });
    }
    closeSchedModal();
    loadSchedule();
  } catch (e) {
    toast(t("schedule.createError") + e.message, "error");
  }
}
