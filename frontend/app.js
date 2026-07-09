/* ── SumPoint frontend ───────────────────────────────────────────────────────── */

const API = "/api/v1";
let token = localStorage.getItem("sp_token") || null;
let isMiniApp = !!(window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData);

let filters = { dateFrom: "", dateTo: "", category: "", channelId: "", unreadOnly: false };
let density = localStorage.getItem("sp_density") || "medium";
let lastPosts = [];
let lastEvents = [];

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
  btn.textContent = currentTheme() === "dark" ? "☀️ Светлая тема" : "🌙 Тёмная тема";
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

// ── Row density (Кратко / Средне / Расширенно) ───────────────────────────────
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

function setToken(t) {
  token = t;
  localStorage.setItem("sp_token", t);
}

function clearToken() {
  token = null;
  localStorage.removeItem("sp_token");
}

function authHeaders() {
  return { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" };
}

async function apiFetch(path, opts = {}) {
  const resp = await fetch(API + path, { ...opts, headers: { ...authHeaders(), ...(opts.headers || {}) } });
  if (resp.status === 401) { logout(); return null; }
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

// ── Mini App auto-login ──────────────────────────────────────────────────────

async function tryMiniAppLogin() {
  if (!isMiniApp) return false;
  try {
    const resp = await fetch(`${API}/auth/telegram/miniapp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: window.Telegram.WebApp.initData }),
    });
    if (!resp.ok) {
      console.error("MiniApp auth failed:", await resp.text());
      return false;
    }
    const { access_token } = await resp.json();
    setToken(access_token);
    return true;
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
  
  // Clean URL
  window.history.replaceState({}, "", "/");
  
  try {
    const resp = await fetch(`${API}/auth/telegram/magic-link/verify?token=${encodeURIComponent(magicToken)}`);
    if (!resp.ok) {
      const err = await resp.json();
      toast(err.detail || "Ссылка недействительна", "error");
      return false;
    }
    const { access_token } = await resp.json();
    setToken(access_token);
    return true;
  } catch (e) {
    toast("Ошибка входа: " + e.message, "error");
    return false;
  }
}

async function requestMagicLink() {
  const input = document.getElementById("magic-username");
  const btn = document.getElementById("magic-btn");
  const status = document.getElementById("magic-status");
  const username = input.value.trim();
  
  if (!username) {
    status.textContent = "Введите ваш Telegram @username";
    return;
  }
  
  btn.disabled = true;
  btn.textContent = "Отправка...";
  status.textContent = "";
  
  try {
    const resp = await fetch(`${API}/auth/telegram/magic-link/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      status.textContent = data.detail || "Ошибка";
      status.className = "magic-status error";
    } else {
      status.textContent = data.message;
      status.className = "magic-status success";
    }
  } catch (e) {
    status.textContent = "Ошибка сети";
    status.className = "magic-status error";
  } finally {
    btn.disabled = false;
    btn.textContent = "Получить ссылку";
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

async function boot() {
  // Magic Link from URL
  const params = new URLSearchParams(window.location.search);
  if (params.get("token")) {
    const ok = await tryMagicLinkVerify();
    if (ok) {
      showApp();
      return;
    }
  }
  
  // Mini App: auto-login via initData
  if (isMiniApp) {
    const ok = await tryMiniAppLogin();
    if (ok) {
      showApp();
      return;
    }
    // Fall through to widget if MiniApp auth fails
  }

  if (token) {
    showApp();
  } else {
    document.getElementById("login-screen").style.display = "flex";
  }
}

document.addEventListener("DOMContentLoaded", () => {
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
  document.getElementById("search-btn").addEventListener("click", runSearch);
  document.getElementById("search-input").addEventListener("keydown", e => {
    if (e.key === "Enter") runSearch();
  });

  // Events page filters
  document.getElementById("ev-date-from").addEventListener("change", loadEvents);
  document.getElementById("ev-date-to").addEventListener("change", loadEvents);
  document.getElementById("ev-filter-topic").addEventListener("change", loadEvents);
  document.getElementById("ev-filter-type").addEventListener("change", loadEvents);
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

  // Theme toggle
  applyThemeButton();
  document.getElementById("theme-btn").addEventListener("click", toggleTheme);

  const statsDays = document.getElementById("stats-days");
  if (statsDays) statsDays.addEventListener("change", loadStats);

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
        container.appendChild(script);
      }
    }
  } catch {
    // Non-critical — login screen still works via Magic Link without bot link.
  }
}

// ── Show app ──────────────────────────────────────────────────────────────────

function showApp() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app").style.display = "flex";
  loadChannelsDropdown();
  refreshUnreadCount();
  navigate("posts");
}

function logout() {
  clearToken();
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
  else if (page === "events") loadEvents();
  else if (page === "stats") loadStats();
  else if (page === "channels") loadChannels();
  else if (page === "schedule") loadSchedule();
}

// ── Telegram login ────────────────────────────────────────────────────────────

async function onTelegramAuth(data) {
  try {
    const resp = await fetch(`${API}/auth/telegram`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!resp.ok) throw new Error("Auth failed");
    const { access_token } = await resp.json();
    setToken(access_token);
    location.reload();
  } catch (e) {
    toast("Ошибка входа: " + e.message, "error");
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

function showSkeletons(n = 6) {
  const tbody = document.getElementById("posts-tbody");
  const widths = ["70%", "90%", "60%", "80%", "75%", "85%"];
  tbody.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const tr = document.createElement("tr");
    tr.className = "skeleton-row";
    tr.innerHTML = `
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
    tbody.innerHTML = `<tr><td colspan="5" class="table-message">Ошибка загрузки: ${escHtml(e.message)}</td></tr>`;
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
    toast("Не удалось загрузить ещё: " + e.message, "error");
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
}

function renderPostRow(post) {
  const date = new Date(post.published_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
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
    ? `<span class="dup-badge" data-cluster="${post.cluster_id}" title="Эта новость в ${post.cluster_size} каналах — показать источники">⧉ ${post.cluster_size} каналах</span>`
    : "";

  const mainRow = document.createElement("tr");
  mainRow.className = "data-row" + (post.is_read ? " is-read" : "");
  mainRow.innerHTML = `
    <td class="cell-channel" title="${escHtml(channelName)}">${escHtml(channelShort)}</td>
    <td><div class="cell-dots"><div class="dot ${dot1}"></div><div class="dot ${dot2}"></div></div></td>
    <td class="cell-post" title="${escHtml(rawText.slice(0, 300))}">${escHtml(preview)}</td>
    <td class="cell-topics">${post.category ? `<span class="topic-tag">${escHtml(post.category)}</span>` : ""}${dupBadge}</td>
    <td class="cell-date">${simBadge} ${date}</td>
  `;

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
      <div class="detail-label">Краткое содержание</div>
      <div class="detail-summary">${escHtml(post.summary)}</div>
    </div>` : "";
  const originalBlock = originalSafe ? `
    <div>
      <div class="detail-label">Оригинальный текст</div>
      <div class="detail-original">${originalSafe}</div>
    </div>` : "";
  const safeTgLink = sanitizeUrl(tgLink);
  const linkBlock = safeTgLink ? `<a class="detail-link" href="${escHtml(safeTgLink)}" target="_blank" rel="noopener">→ Открыть в Telegram</a>` : "";

  detailRow.innerHTML = `<td colspan="5"><div class="detail-inner">${summaryBlock}${originalBlock}${linkBlock}</div></td>`;

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
  body.innerHTML = "<div class='table-message'>Загрузка…</div>";
  modal.style.display = "flex";
  try {
    const rows = await apiFetch(`/posts/cluster/${clusterId}`);
    if (!rows || !rows.length) {
      body.innerHTML = "<div class='table-message'>Источники не найдены.</div>";
      return;
    }
    body.innerHTML = rows.map(r => {
      const name = escHtml(r.channel_title || r.channel_username || "—");
      const date = new Date(r.published_at).toLocaleString("ru-RU",
        { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
      const link = r.channel_username
        ? sanitizeUrl(`https://t.me/${r.channel_username}/${r.telegram_message_id}`)
        : null;
      const openLink = link
        ? `<a class="cluster-src-link" href="${escHtml(link)}" target="_blank" rel="noopener">→ Открыть</a>`
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
    body.innerHTML = "<div class='table-message'>Ошибка загрузки источников.</div>";
    toast("Не удалось загрузить источники: " + e.message, "error");
  }
}

function closeClusterModal(e) {
  if (e && e.target && e.target.id !== "cluster-modal" && e.target.id !== "cluster-modal-close") return;
  const modal = document.getElementById("cluster-modal");
  if (modal) modal.style.display = "none";
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
    toast(`Отмечено прочитанным: ${res ? res.marked : 0}`, "success");
    await refreshUnreadCount();
    loadFeed();
  } catch (e) {
    toast("Не удалось: " + e.message, "error");
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
    toast("Ошибка поиска: " + e.message, "error");
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
    toast("Не удалось загрузить статистику: " + e.message, "error");
  }
}

function renderStatCards(t) {
  const el = document.getElementById("stats-cards");
  if (!el || !t) return;
  const cards = [
    { label: "Постов", value: t.posts, accent: false },
    { label: "Непрочитано", value: t.unread, accent: true },
    { label: "С событиями", value: t.events, accent: false },
    { label: "Каналов", value: t.channels, accent: false },
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
  if (!days || !days.length) { el.innerHTML = "<span style='color:var(--muted);font-size:13px'>Нет данных</span>"; return; }
  const max = Math.max(1, ...days.map(d => d.count));
  el.innerHTML = days.map(d => {
    const pct = (d.count / max) * 100;
    const label = new Date(d.date + "T00:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
    return `<div class="day-bar" title="${label}: ${d.count}">
      <div class="day-tip">${label}: ${d.count}</div>
      <div class="day-fill" style="height:${pct}%"></div>
    </div>`;
  }).join("");
}

function renderBarList(elId, rows, nameFn) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!rows || !rows.length) { el.innerHTML = "<span style='color:var(--muted);font-size:13px'>Нет данных</span>"; return; }
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

// ── Events ────────────────────────────────────────────────────────────────────

function resetEventFilters() {
  document.getElementById("ev-date-from").value = "";
  document.getElementById("ev-date-to").value = "";
  document.getElementById("ev-filter-topic").value = "";
  document.getElementById("ev-filter-type").value = "";
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

    lastEvents = events;  // what's currently shown — the .ics export uses this

    if (events.length === 0) {
      noEvEl.style.display = "block";
      return;
    }

    // Populate topic dropdown from loaded events (first load only)
    populateTopicsDropdown(data.events || []);

    events.forEach(ev => {
      const { mainRow, detailRow } = renderEventRow(ev);
      tbody.appendChild(mainRow);
      tbody.appendChild(detailRow);
    });
  } catch (e) {
    loader.style.display = "none";
    tbody.innerHTML = `<tr><td colspan="8" class="table-message">Ошибка загрузки: ${e.message}</td></tr>`;
  }
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
    if (ev.location) descParts.push("Место: " + ev.location);
    if (ev.channel_title) descParts.push("Канал: " + ev.channel_title);
    if ((ev.speakers || []).length) descParts.push("Спикеры: " + ev.speakers.join(", "));
    if (ev.link) descParts.push(ev.link);
    lines.push("BEGIN:VEVENT");
    lines.push(`UID:sumpoint-${Date.now()}-${i}@sumpoint`);
    lines.push(`DTSTAMP:${now}`);
    lines.push(dt.allDay ? `DTSTART;VALUE=DATE:${dt.value}` : `DTSTART:${dt.value}`);
    lines.push("SUMMARY:" + _icsEscape(ev.name || "Событие"));
    if (ev.location) lines.push("LOCATION:" + _icsEscape(ev.location));
    if (descParts.length) lines.push("DESCRIPTION:" + _icsEscape(descParts.join("\n")));
    lines.push("END:VEVENT");
  });
  lines.push("END:VCALENDAR");
  return { text: lines.join("\r\n"), count };
}

function exportEventsIcs() {
  if (!lastEvents || lastEvents.length === 0) {
    toast("Нет событий для экспорта", "error");
    return;
  }
  const { text, count } = buildIcs(lastEvents);
  if (count === 0) {
    toast("У событий нет распознанных дат", "error");
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
  toast(`Экспортировано событий: ${count}`, "success");
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
    ? new Date(ev.date + "T00:00:00").toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" })
    : "—";
  const timeStr = ev.time || "";
  const name = ev.name || "—";
  const topics = (ev.topics || []).slice(0, 3).map(t => `<span class="ev-topic-tag">${escHtml(t)}</span>`).join(" ");
  const evType = ev.type ? `<span class="ev-type-badge">${escHtml(ev.type)}</span>` : "";
  const location = ev.location ? escHtml(ev.location) : "";
  const speakers = (ev.speakers || []).join(", ");
  const partners = (ev.partners || []).join(", ");
  const mentions = ev.mentions || 1;
  const safeEvLink = sanitizeUrl(ev.link);

  const mainRow = document.createElement("tr");
  mainRow.className = "data-row";
  mainRow.innerHTML = `
    <td class="cell-evdate">${dateStr}${timeStr ? `<br><span class="ev-time">${timeStr}</span>` : ""}</td>
    <td class="cell-evname">
      <span class="ev-expand-icon">&#9660;</span>
      ${safeEvLink ? `<a class="ev-name-link" href="${escHtml(safeEvLink)}" target="_blank" rel="noopener">${escHtml(name)}</a>` : escHtml(name)}
    </td>
    <td class="cell-evtopics">${topics}</td>
    <td>${evType}</td>
    <td class="cell-evlocation" title="${escHtml(ev.location || "")}">${location}</td>
    <td class="cell-evspeakers" title="${escHtml(speakers)}">${escHtml(speakers.slice(0, 40))}${speakers.length > 40 ? "…" : ""}</td>
    <td class="cell-evpartners" title="${escHtml(partners)}">${escHtml(partners.slice(0, 40))}${partners.length > 40 ? "…" : ""}</td>
    <td class="cell-evmentions">${mentions}</td>
  `;

  const detailRow = document.createElement("tr");
  detailRow.className = "detail-row";
  const channelInfo = ev.channel_title ? `<b>${escHtml(ev.channel_title)}</b>` : "";
  const allTopics = (ev.topics || []).map(t => `<span class="ev-topic-tag">${escHtml(t)}</span>`).join(" ");
  const fullSpeakers = (ev.speakers || []).length > 0
    ? `<div class="detail-label">Спикеры</div><div>${escHtml((ev.speakers || []).join(", "))}</div>` : "";
  const fullPartners = (ev.partners || []).length > 0
    ? `<div class="detail-label">Партнёры</div><div>${escHtml((ev.partners || []).join(", "))}</div>` : "";
  const linkBlock = safeEvLink
    ? `<a class="detail-link" href="${escHtml(safeEvLink)}" target="_blank" rel="noopener">→ Подробнее</a>` : "";

  detailRow.innerHTML = `<td colspan="8"><div class="detail-inner ev-detail-inner">
    <div style="display:flex;gap:24px;flex-wrap:wrap">
      ${channelInfo ? `<div><div class="detail-label">Канал</div><div>${channelInfo}</div></div>` : ""}
      ${ev.location ? `<div><div class="detail-label">Место</div><div>${escHtml(ev.location)}</div></div>` : ""}
      ${ev.date ? `<div><div class="detail-label">Дата и время</div><div>${dateStr}${timeStr ? " " + timeStr : ""}</div></div>` : ""}
    </div>
    ${allTopics ? `<div><div class="detail-label">Темы</div><div style="display:flex;gap:4px;flex-wrap:wrap">${allTopics}</div></div>` : ""}
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
  if (!iso) return "никогда";
  const then = new Date(iso).getTime();
  if (isNaN(then)) return "—";
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "только что";
  if (mins < 60) return `${mins} мин назад`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} ч назад`;
  const days = Math.floor(hrs / 24);
  return `${days} дн назад`;
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
      list.innerHTML = "<li style='color:var(--muted);font-size:13px;padding:10px 0;'>Каналов нет</li>";
      return;
    }
    data.forEach(ch => {
      const state = _healthState(ch);
      const li = document.createElement("li");
      li.className = "channel-item health";
      const errBlock = ch.last_error
        ? `<div class="channel-health-err" title="${escHtml(ch.last_error)}">⚠ ${escHtml(ch.last_error)}</div>`
        : "";
      li.innerHTML = `
        <div class="channel-health-top">
          <span class="ch-dot ${state}" title="${state}"></span>
          <span class="channel-item-name">${escHtml(ch.title || ch.username || String(ch.channel_id))}</span>
          <button class="channel-remove" onclick="removeChannel(${ch.channel_id})">✕</button>
        </div>
        <div class="channel-health-meta">
          <span>Постов: <b>${ch.post_count}</b></span>
          <span>Непрочитано: <b>${ch.unread_count}</b></span>
          <span>Сбор: <b>${_fmtAgo(ch.last_fetched_at)}</b></span>
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
    toast("Ошибка добавления: " + e.message, "error");
  }
}

async function removeChannel(id) {
  try {
    const resp = await fetch(`${API}/channels/${id}`, { method: "DELETE", headers: authHeaders() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    loadChannels();
    loadChannelsDropdown();
  } catch (e) {
    toast("Ошибка удаления: " + e.message, "error");
  }
}

async function importChannels() {
  const btn = document.getElementById("import-btn");
  btn.disabled = true;
  btn.textContent = "Импортирую…";
  try {
    const data = await apiFetch("/channels/import", { method: "POST" });
    await loadChannels();
    await loadChannelsDropdown();
    btn.textContent = `Добавлено ${data.imported} из ${data.total}`;
    setTimeout(() => { btn.textContent = "Импортировать мои каналы"; btn.disabled = false; }, 3000);
  } catch (e) {
    toast("Ошибка импорта: " + e.message, "error");
    btn.textContent = "Импортировать мои каналы";
    btn.disabled = false;
  }
}

async function syncChannels() {
  const btn = document.getElementById("sync-btn");
  btn.disabled = true;
  btn.textContent = "Синхронизация…";
  try {
    await apiFetch("/channels/sync", { method: "POST" });
    setTimeout(() => { loadFeed(); loadChannels(); }, 3000);
  } catch (e) {
    toast("Ошибка: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Синхронизировать";
  }
}

// ── Digest ────────────────────────────────────────────────────────────────────

async function generateDigest() {
  const btn = document.getElementById("gen-digest-btn");
  const box = document.getElementById("digest-box");
  btn.disabled = true;
  btn.textContent = "Генерирую…";
  box.style.display = "none";
  try {
    const data = await apiFetch("/digest/?hours=24");
    box.textContent = data.digest_markdown || "Нет новых постов.";
    box.style.display = "block";
  } catch (e) {
    box.textContent = "Ошибка: " + e.message;
    box.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "Сгенерировать сводку";
  }
}

// ── Schedule ──────────────────────────────────────────────────────────────────

const _TYPE_LABELS = { topics: "Темы", events: "События", collect: "Сбор" };

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
    if (!data || data.length === 0) { empty.style.display = "block"; return; }
    data.forEach(s => tbody.appendChild(renderSchedRow(s)));
  } catch (e) {
    loader.style.display = "none";
    tbody.innerHTML = `<tr><td colspan="7" class="table-message">Ошибка: ${e.message}</td></tr>`;
  }
}

function renderSchedRow(s) {
  const tr = document.createElement("tr");
  const typeLabel = _TYPE_LABELS[s.schedule_type] || s.schedule_type;
  const topicsLabel = (s.categories && s.categories.length > 0) ? s.categories.length : "все";
  const lastRun = s.last_run_at
    ? new Date(s.last_run_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : "—";

  tr.innerHTML = `
    <td class="sched-name">${escHtml(s.name)}</td>
    <td><span class="type-badge ${s.schedule_type}">${typeLabel}</span></td>
    <td class="cron-text">${escHtml(s.cron_expr)}</td>
    <td class="last-run">${topicsLabel}</td>
    <td>
      <button class="status-btn ${s.status}" onclick="toggleSchedule(${s.id}, this)">
        ${s.status === "active" ? "Активно" : "Пауза"}
      </button>
    </td>
    <td class="last-run">${lastRun}</td>
    <td>
      <button class="row-del-btn" onclick="deleteSchedule(${s.id})" title="Удалить">✕</button>
    </td>
  `;
  return tr;
}

async function toggleSchedule(id, btn) {
  try {
    const data = await apiFetch(`/schedule/${id}/toggle`, { method: "POST" });
    if (!data) return;
    btn.className = `status-btn ${data.status}`;
    btn.textContent = data.status === "active" ? "Активно" : "Пауза";
  } catch (e) {
    toast("Ошибка: " + e.message, "error");
  }
}

async function deleteSchedule(id) {
  if (!confirm("Удалить расписание?")) return;
  try {
    const resp = await fetch(`${API}/schedule/${id}`, { method: "DELETE", headers: authHeaders() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    loadSchedule();
  } catch (e) {
    toast("Ошибка: " + e.message, "error");
  }
}

// Modal

function openSchedModal() {
  document.getElementById("sched-modal").style.display = "flex";
  document.getElementById("m-name").value = "";
  document.getElementById("m-cron-preset").value = "0 9 * * *";
  document.getElementById("m-cron-custom").style.display = "none";
  document.querySelectorAll(".type-btn").forEach(b => b.classList.remove("active"));
  document.querySelector(".type-btn[data-type='topics']").classList.add("active");
  document.getElementById("m-topics-section").style.display = "flex";
  document.querySelectorAll("#m-categories input").forEach(cb => { cb.checked = false; });
  document.querySelector("input[name='m-hours'][value='24']").checked = true;
}

function closeSchedModal(e) {
  if (!e || e.target === document.getElementById("sched-modal")) {
    document.getElementById("sched-modal").style.display = "none";
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

async function createSchedule() {
  const name = document.getElementById("m-name").value.trim();
  if (!name) { toast("Укажите название", "error"); return; }

  const schedule_type = document.querySelector(".type-btn.active")?.dataset.type || "topics";

  const presetSel = document.getElementById("m-cron-preset");
  const cron_expr = presetSel.value === "custom"
    ? document.getElementById("m-cron-custom").value.trim()
    : presetSel.value;
  if (!cron_expr) { toast("Укажите расписание", "error"); return; }

  const hoursRadio = document.querySelector("input[name='m-hours']:checked");
  const hours_back = hoursRadio ? parseInt(hoursRadio.value) : 24;
  const model = document.getElementById("m-model").value;
  const checkedCats = Array.from(document.querySelectorAll("#m-categories input:checked")).map(cb => cb.value);

  try {
    await apiFetch("/schedule/", {
      method: "POST",
      body: JSON.stringify({
        name, schedule_type, cron_expr, hours_back, model,
        categories: checkedCats.length > 0 ? checkedCats : null,
      }),
    });
    closeSchedModal();
    loadSchedule();
  } catch (e) {
    toast("Ошибка создания: " + e.message, "error");
  }
}
