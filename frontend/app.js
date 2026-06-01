/* ── SumPoint frontend ───────────────────────────────────────────────────────── */

const API = "/api/v1";
let token = localStorage.getItem("sp_token") || null;
let isMiniApp = !!(window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData);

let filters = { dateFrom: "", dateTo: "", category: "", channelId: "" };

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

// ── Boot ──────────────────────────────────────────────────────────────────────

async function boot() {
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

  document.getElementById("gen-digest-btn").addEventListener("click", generateDigest);
  document.getElementById("add-channel-btn").addEventListener("click", addChannel);
  document.getElementById("channel-input").addEventListener("keydown", e => {
    if (e.key === "Enter") addChannel();
  });
  document.getElementById("import-btn").addEventListener("click", importChannels);
  document.getElementById("sync-btn").addEventListener("click", syncChannels);
});

// ── Show app ──────────────────────────────────────────────────────────────────

function showApp() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app").style.display = "flex";
  loadChannelsDropdown();
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
    alert("Ошибка входа: " + e.message);
  }
}

// ── Feed (Posts Table) ────────────────────────────────────────────────────────

async function loadFeed(overrideRows = null) {
  const tbody = document.getElementById("posts-tbody");
  const loader = document.getElementById("feed-loader");
  const noPostsEl = document.getElementById("no-posts");
  tbody.innerHTML = "";
  loader.style.display = "block";
  noPostsEl.style.display = "none";

  try {
    let data = overrideRows;
    if (!data) {
      let url = "/posts/?limit=80";
      if (filters.category) url += `&category=${encodeURIComponent(filters.category)}`;
      if (filters.channelId) url += `&channel_id=${filters.channelId}`;
      if (filters.dateFrom) url += `&date_from=${filters.dateFrom}`;
      if (filters.dateTo) url += `&date_to=${filters.dateTo}`;
      data = await apiFetch(url);
    }
    loader.style.display = "none";
    if (!data || data.length === 0) {
      noPostsEl.style.display = "block";
      return;
    }
    data.forEach(post => {
      const { mainRow, detailRow } = renderPostRow(post);
      tbody.appendChild(mainRow);
      tbody.appendChild(detailRow);
    });
  } catch (e) {
    loader.style.display = "none";
    tbody.innerHTML = `<tr><td colspan="5" class="table-message">Ошибка загрузки: ${e.message}</td></tr>`;
  }
}

function renderPostRow(post) {
  const date = new Date(post.published_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
  const channelName = (post.channel_title || post.channel_username || "—");
  const channelShort = channelName.length > 24 ? channelName.slice(0, 22) + "…" : channelName;
  const rawText = (post.text || "").replace(/\*\*/g, "").replace(/\n/g, " ").trim();
  const preview = rawText.length > 130 ? rawText.slice(0, 128) + "…" : rawText;

  const hasSummary = !!post.summary;
  const hasEvents = post.events && (Array.isArray(post.events) ? post.events.length > 0 : Object.keys(post.events).length > 0);
  const dot1 = hasSummary ? "dot-green" : "dot-gray";
  const dot2 = hasEvents ? "dot-orange" : "dot-gray";

  const tgLink = post.channel_username
    ? `https://t.me/${post.channel_username}/${post.telegram_message_id}`
    : null;

  const mainRow = document.createElement("tr");
  mainRow.className = "data-row";
  mainRow.innerHTML = `
    <td class="cell-channel" title="${escHtml(channelName)}">${escHtml(channelShort)}</td>
    <td><div class="cell-dots"><div class="dot ${dot1}"></div><div class="dot ${dot2}"></div></div></td>
    <td class="cell-post" title="${escHtml(rawText.slice(0, 300))}">${escHtml(preview)}</td>
    <td class="cell-topics">${post.category ? `<span class="topic-tag">${escHtml(post.category)}</span>` : ""}</td>
    <td class="cell-date">${date}</td>
  `;

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
  const linkBlock = tgLink ? `<a class="detail-link" href="${tgLink}" target="_blank" rel="noopener">→ Открыть в Telegram</a>` : "";

  detailRow.innerHTML = `<td colspan="5"><div class="detail-inner">${summaryBlock}${originalBlock}${linkBlock}</div></td>`;

  mainRow.addEventListener("click", () => {
    const open = detailRow.classList.contains("visible");
    mainRow.classList.toggle("expanded", !open);
    detailRow.classList.toggle("visible", !open);
  });

  return { mainRow, detailRow };
}

function escHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Search ────────────────────────────────────────────────────────────────────

async function runSearch() {
  const q = document.getElementById("search-input").value.trim();
  if (!q) { loadFeed(); return; }
  try {
    const results = await apiFetch(`/posts/search?q=${encodeURIComponent(q)}&limit=80`);
    loadFeed(results);
  } catch (e) {
    alert("Ошибка поиска: " + e.message);
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

  const mainRow = document.createElement("tr");
  mainRow.className = "data-row";
  mainRow.innerHTML = `
    <td class="cell-evdate">${dateStr}${timeStr ? `<br><span class="ev-time">${timeStr}</span>` : ""}</td>
    <td class="cell-evname">
      <span class="ev-expand-icon">&#9660;</span>
      ${ev.link ? `<a class="ev-name-link" href="${ev.link}" target="_blank" rel="noopener">${escHtml(name)}</a>` : escHtml(name)}
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
  const linkBlock = ev.link
    ? `<a class="detail-link" href="${ev.link}" target="_blank" rel="noopener">→ Подробнее</a>` : "";

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

async function loadChannels() {
  try {
    const data = await apiFetch("/channels/");
    const list = document.getElementById("channels-list");
    list.innerHTML = "";
    if (!data || data.length === 0) {
      list.innerHTML = "<li style='color:var(--muted);font-size:13px;padding:10px 0;'>Каналов нет</li>";
      return;
    }
    data.forEach(ch => {
      const li = document.createElement("li");
      li.className = "channel-item";
      li.innerHTML = `
        <span class="channel-item-name">${escHtml(ch.title || ch.username || String(ch.telegram_id))}</span>
        <button class="channel-remove" onclick="removeChannel(${ch.id})">✕</button>
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
    alert("Ошибка добавления: " + e.message);
  }
}

async function removeChannel(id) {
  try {
    await fetch(`${API}/channels/${id}`, { method: "DELETE", headers: authHeaders() });
    loadChannels();
    loadChannelsDropdown();
  } catch (e) {
    alert("Ошибка удаления: " + e.message);
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
    alert("Ошибка импорта: " + e.message);
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
    alert("Ошибка: " + e.message);
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
    alert("Ошибка: " + e.message);
  }
}

async function deleteSchedule(id) {
  if (!confirm("Удалить расписание?")) return;
  try {
    await fetch(`${API}/schedule/${id}`, { method: "DELETE", headers: authHeaders() });
    loadSchedule();
  } catch (e) {
    alert("Ошибка: " + e.message);
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
  if (!name) { alert("Укажите название"); return; }

  const schedule_type = document.querySelector(".type-btn.active")?.dataset.type || "topics";

  const presetSel = document.getElementById("m-cron-preset");
  const cron_expr = presetSel.value === "custom"
    ? document.getElementById("m-cron-custom").value.trim()
    : presetSel.value;
  if (!cron_expr) { alert("Укажите расписание"); return; }

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
    alert("Ошибка создания: " + e.message);
  }
}
