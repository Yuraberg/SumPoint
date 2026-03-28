/* ── SumPoint frontend app ─────────────────────────────────────────────────── */

const API = "/api/v1";
let token = localStorage.getItem("sp_token") || null;
let currentCategory = "";

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

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  if (token) {
    showApp();
  } else {
    document.getElementById("login-screen").style.display = "flex";
  }

  document.getElementById("logout-btn").addEventListener("click", logout);
  document.getElementById("search-btn").addEventListener("click", runSearch);
  document.getElementById("search-input").addEventListener("keydown", e => {
    if (e.key === "Enter") runSearch();
  });
  document.getElementById("gen-digest-btn").addEventListener("click", generateDigest);

  // Category pills
  document.querySelectorAll(".pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      currentCategory = pill.dataset.cat;
      loadFeed();
    });
  });

  // Collapsible prompt editor
  document.querySelector(".collapsible-toggle")?.addEventListener("click", () => {
    const body = document.querySelector(".collapsible-body");
    body.style.display = body.style.display === "none" ? "block" : "none";
  });
});

// ── Show/hide screens ─────────────────────────────────────────────────────────

function showApp() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app").style.display = "block";
  document.getElementById("logout-btn").style.display = "inline-flex";
  loadFeed();
  loadEvents();
}

function logout() {
  clearToken();
  location.reload();
}

// ── Telegram login callback (called by the widget) ────────────────────────────

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
    document.getElementById("user-name").textContent = data.first_name || "";
    showApp();
  } catch (e) {
    alert("Ошибка входа: " + e.message);
  }
}

// ── Feed ──────────────────────────────────────────────────────────────────────

async function loadFeed(posts = null) {
  const feed = document.getElementById("feed");
  const loader = document.getElementById("feed-loader");
  feed.innerHTML = "";
  loader.style.display = "block";

  try {
    let url = "/posts/?limit=30";
    if (currentCategory) url += `&category=${encodeURIComponent(currentCategory)}`;
    const data = posts || (await apiFetch(url));
    loader.style.display = "none";
    if (!data || data.length === 0) {
      feed.innerHTML = '<p class="loader">Нет постов. Добавьте каналы и нажмите «Синхронизировать».</p>';
      return;
    }
    data.forEach(post => feed.appendChild(renderPost(post)));
  } catch (e) {
    loader.style.display = "none";
    feed.innerHTML = `<p class="loader">Ошибка загрузки: ${e.message}</p>`;
  }
}

function renderPost(post) {
  const el = document.createElement("div");
  el.className = "post-card";
  const date = new Date(post.published_at).toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  el.innerHTML = `
    <div class="post-meta">
      <span class="post-category">${post.category || "?"}</span>
      <span>${date}</span>
    </div>
    <p class="post-summary">${post.summary || post.text?.slice(0, 200) || ""}</p>
  `;
  return el;
}

// ── Search ────────────────────────────────────────────────────────────────────

async function runSearch() {
  const q = document.getElementById("search-input").value.trim();
  if (!q) { loadFeed(); return; }
  try {
    const results = await apiFetch(`/posts/search?q=${encodeURIComponent(q)}&limit=20`);
    loadFeed(results);
  } catch (e) {
    alert("Ошибка поиска: " + e.message);
  }
}

// ── Events ────────────────────────────────────────────────────────────────────

async function loadEvents() {
  try {
    const data = await apiFetch("/digest/events?days_ahead=7");
    const list = document.getElementById("events-list");
    list.innerHTML = "";
    if (!data || !data.events || data.events.length === 0) {
      list.innerHTML = "<li class='loader' style='padding:0;font-size:13px;color:var(--muted)'>Нет событий</li>";
      return;
    }
    data.events.forEach(ev => {
      const li = document.createElement("li");
      li.className = "event-item";
      li.innerHTML = `
        <div class="ev-date">${ev.date || "Дата не указана"} ${ev.time || ""}</div>
        <div class="ev-name">${ev.name || "Событие"}${ev.link ? ` <a href="${ev.link}" target="_blank">→</a>` : ""}</div>
      `;
      list.appendChild(li);
    });
  } catch (e) {
    console.error("Events error:", e);
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
    btn.textContent = "Сгенерировать сейчас";
  }
}
