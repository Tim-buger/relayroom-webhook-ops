const state = { events: [], filter: "all", selectedId: null, timer: null };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTime(value) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat("en", {
    month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function statusLabel(status) {
  return status.replace("_", " ");
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.clearTimeout(toast.timeout);
  toast.timeout = window.setTimeout(() => node.classList.remove("show"), 2500);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function renderCounts() {
  const counts = { all: state.events.length, retrying: 0, dead_letter: 0, delivered: 0 };
  state.events.forEach((event) => {
    if (counts[event.status] !== undefined) counts[event.status] += 1;
  });
  Object.entries(counts).forEach(([name, count]) => {
    $(`#count-${name}`).textContent = String(count).padStart(2, "0");
  });
}

function lastAttempt(event) {
  return event.attempts[event.attempts.length - 1];
}

function renderRows() {
  const visible = state.filter === "all"
    ? state.events
    : state.events.filter((event) => event.status === state.filter);
  const rows = $("#event-rows");
  rows.innerHTML = visible.map((event) => {
    const attempt = lastAttempt(event);
    const response = attempt?.status_code ? `HTTP ${attempt.status_code}` : (attempt?.error || "Waiting");
    return `<tr data-id="${event.id}" class="${event.id === state.selectedId ? "selected" : ""}">
      <td><span class="event-time">${formatTime(event.received_at)}</span></td>
      <td><span class="event-name">${escapeHtml(event.event_type)}</span><code class="event-id">${escapeHtml(event.provider_event_id)}</code></td>
      <td><span class="status status-${event.status}">${statusLabel(event.status)}</span></td>
      <td><span class="attempt-count">${event.attempt_count}</span></td>
      <td><span class="response-code ${attempt ? "" : "muted"}">${escapeHtml(response)}</span></td>
    </tr>`;
  }).join("");
  $("#empty-state").hidden = visible.length > 0;
  rows.querySelectorAll("tr").forEach((row) => row.addEventListener("click", () => selectEvent(row.dataset.id)));
}

function renderInspector(event) {
  if (!event) {
    $("#inspector-empty").hidden = false;
    $("#inspector-content").hidden = true;
    return;
  }
  $("#inspector-empty").hidden = true;
  $("#inspector-content").hidden = false;
  $("#detail-type").textContent = event.event_type;
  $("#detail-id").textContent = event.provider_event_id;
  $("#detail-received").textContent = formatDateTime(event.received_at);
  $("#detail-attempts").textContent = event.attempt_count;
  $("#detail-payload").textContent = JSON.stringify(event.payload, null, 2);
  const badge = $("#detail-status");
  badge.className = `status status-${event.status}`;
  badge.textContent = statusLabel(event.status);
  $("#recovery").hidden = event.status !== "dead_letter";
  $("#attempt-timeline").innerHTML = event.attempts.length
    ? event.attempts.map((attempt) => `<li>
        <strong>Attempt ${attempt.attempt_number} · ${attempt.status_code ? `HTTP ${attempt.status_code}` : "No response"}</strong>
        <span>${formatDateTime(attempt.started_at)} · ${attempt.duration_ms} ms${attempt.error ? ` · ${escapeHtml(attempt.error)}` : ""}</span>
      </li>`).join("")
    : '<li><strong>Queued for delivery</strong><span>The worker has not started an attempt yet.</span></li>';
}

function selectEvent(id) {
  state.selectedId = id;
  renderRows();
  renderInspector(state.events.find((event) => event.id === id));
}

async function loadEvents({ quiet = false } = {}) {
  try {
    state.events = await api("/api/v1/events?limit=100");
    renderCounts();
    renderRows();
    if (state.selectedId) renderInspector(state.events.find((event) => event.id === state.selectedId));
    $("#last-updated").textContent = `Updated ${formatTime(new Date())} · auto-refresh on`;
  } catch (error) {
    $("#last-updated").textContent = "Connection unavailable";
    if (!quiet) toast(error.message);
  }
}

async function loadMode() {
  try {
    const result = await api("/api/v1/demo/destination");
    $("#destination-mode").value = result.mode;
  } catch (error) {
    toast(error.message);
  }
}

$$('[data-filter]').forEach((button) => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  $$("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
  renderRows();
}));

$("#destination-mode").addEventListener("change", async (event) => {
  try {
    await api("/api/v1/demo/destination", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: event.target.value }),
    });
    toast(`Destination set to ${event.target.options[event.target.selectedIndex].text}`);
  } catch (error) {
    toast(error.message);
  }
});

$("#send-event").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const created = await api("/api/v1/demo/events", { method: "POST" });
    state.selectedId = created.event_id;
    toast("Test event accepted and queued");
    await loadEvents();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});

$("#refresh").addEventListener("click", () => loadEvents());
$("#copy-payload").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("#detail-payload").textContent);
  toast("Payload copied");
});
$("#replay-event").addEventListener("click", async () => {
  try {
    await api(`/api/v1/events/${state.selectedId}/replay`, { method: "POST" });
    toast("Replay queued");
    await loadEvents();
  } catch (error) {
    toast(error.message);
  }
});

Promise.all([loadMode(), loadEvents()]);
state.timer = window.setInterval(() => loadEvents({ quiet: true }), 4000);
