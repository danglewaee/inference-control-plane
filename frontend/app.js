const form = document.getElementById("infer-form");
const promptInput = document.getElementById("prompt-input");
const prioritySelect = document.getElementById("priority-select");
const policySelect = document.getElementById("policy-select");
const backendSelect = document.getElementById("backend-select");
const latencyInput = document.getElementById("latency-input");
const tokensInput = document.getElementById("tokens-input");
const submitButton = document.getElementById("submit-button");
const requestStatus = document.getElementById("request-status");
const responseTitle = document.getElementById("response-title");
const responseMeta = document.getElementById("response-meta");
const responseBody = document.getElementById("response-body");
const healthBadge = document.getElementById("health-badge");
const requestsTotal = document.getElementById("requests-total");
const fallbackTotal = document.getElementById("fallback-total");
const rejectedTotal = document.getElementById("rejected-total");
const rollbackTotal = document.getElementById("rollback-total");
const backendCount = document.getElementById("backend-count");
const backendList = document.getElementById("backend-list");
const historyList = document.getElementById("history-list");
const refreshButton = document.getElementById("refresh-button");

const presetButtons = Array.from(document.querySelectorAll(".preset-chip"));

const API = {
  health: "/health",
  infer: "/infer",
  backends: "/backends",
  history: "/history?limit=6",
  summary: "/metrics/summary",
};

function setStatus(message) {
  requestStatus.textContent = message;
}

function setHealthBadge(ok, label) {
  healthBadge.textContent = label;
  healthBadge.className = `badge ${ok ? "badge-healthy" : "badge-warning"}`;
}

function makeMetaChip(label, variant = "") {
  const chip = document.createElement("span");
  chip.className = `meta-chip ${variant}`.trim();
  chip.textContent = label;
  return chip;
}

function renderResponse(result) {
  responseTitle.textContent = result.rejected ? "Request was rejected" : "Request completed";
  responseMeta.innerHTML = "";
  responseMeta.append(
    makeMetaChip(`backend: ${result.backend || "n/a"}`),
    makeMetaChip(`latency: ${result.latency_ms} ms`),
    makeMetaChip(result.fallback_used ? "fallback used" : "primary path", result.fallback_used ? "flag-warn" : "flag-good"),
    makeMetaChip(result.queued ? "queued" : "not queued"),
  );
  responseBody.textContent = result.result || result.reason || "No response payload returned.";
}

function renderBackendList(backends) {
  const selectedBackend = backendSelect.value;
  backendCount.textContent = `${backends.length} live`;
  backendList.innerHTML = "";
  if (!backends.length) {
    backendList.innerHTML = '<p class="empty-state">No backends available yet.</p>';
    return;
  }

  const options = ['<option value="">Automatic</option>'];

  for (const backend of backends) {
    options.push(`<option value="${backend.name}">${backend.name}</option>`);

    const card = document.createElement("article");
    card.className = "backend-card";
    const healthClass = backend.healthy ? "stat-good" : "stat-warn";
    card.innerHTML = `
      <div class="backend-top">
        <div>
          <p class="backend-name">${backend.name}</p>
          <p class="backend-model">${backend.model_name}</p>
        </div>
        <span class="flag-pill ${healthClass}">${backend.healthy ? "healthy" : "degraded"}</span>
      </div>
      <div class="backend-stats">
        <span class="stat-pill">p95 ${backend.p95_latency_ms} ms</span>
        <span class="stat-pill">queue ${backend.queue_depth}</span>
        <span class="stat-pill">inflight ${backend.inflight}/${backend.max_concurrency}</span>
        <span class="stat-pill">error ${Math.round(backend.error_rate * 100)}%</span>
        <span class="stat-pill">cost ${backend.cost_weight}</span>
      </div>
    `;
    backendList.append(card);
  }

  backendSelect.innerHTML = options.join("");
  if (selectedBackend && backends.some((backend) => backend.name === selectedBackend)) {
    backendSelect.value = selectedBackend;
  }
}

function renderHistory(history) {
  historyList.innerHTML = "";
  if (!history.length) {
    historyList.innerHTML = '<p class="empty-state">No requests recorded yet.</p>';
    return;
  }

  for (const item of history) {
    const card = document.createElement("article");
    card.className = "history-card";
    card.innerHTML = `
      <div class="history-top">
        <div>
          <p class="history-title">${item.final_backend || item.chosen_backend || "no backend"}</p>
          <p class="history-caption">${item.policy} | ${item.priority} priority | ${item.latency_ms} ms</p>
        </div>
        <span class="flag-pill ${item.rejected ? "flag-warn" : "flag-good"}">${item.status}</span>
      </div>
      <div class="history-flags">
        <span class="flag-pill">${item.fallback_used ? "fallback" : "primary"}</span>
        <span class="flag-pill">${item.queued ? "queued" : "direct"}</span>
        <span class="flag-pill">${item.reason || "ok"}</span>
      </div>
      <p class="history-caption">${item.input_excerpt}</p>
    `;
    historyList.append(card);
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed for ${url}`);
  }
  return response.json();
}

async function refreshDashboard() {
  try {
    const [health, backends, summary, history] = await Promise.all([
      fetchJson(API.health),
      fetchJson(API.backends),
      fetchJson(API.summary),
      fetchJson(API.history),
    ]);

    setHealthBadge(health.status === "ok", health.status === "ok" ? "System healthy" : "System degraded");
    requestsTotal.textContent = summary.requests_total;
    fallbackTotal.textContent = summary.fallback_total;
    rejectedTotal.textContent = summary.rejected_total;
    rollbackTotal.textContent = summary.canary_rollbacks_total;
    renderBackendList(backends);
    renderHistory(history);
  } catch (error) {
    setHealthBadge(false, "Health check failed");
    setStatus(`Could not refresh system data: ${error.message}`);
  }
}

async function submitInference(event) {
  event.preventDefault();
  submitButton.disabled = true;
  setStatus("Sending request to the control plane...");

  const payload = {
    input: promptInput.value.trim(),
    priority: prioritySelect.value,
    latency_budget_ms: Number(latencyInput.value),
  };
  const maxTokens = Number(tokensInput.value);
  if (Number.isFinite(maxTokens) && maxTokens > 0) {
    payload.max_tokens = maxTokens;
  }

  if (policySelect.value) {
    payload.policy = policySelect.value;
  }
  if (backendSelect.value) {
    payload.preferred_backend = backendSelect.value;
  }

  try {
    const result = await fetchJson(API.infer, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderResponse(result);
    setStatus(`Request ${result.request_id} completed.`);
    await refreshDashboard();
  } catch (error) {
    responseTitle.textContent = "Request failed";
    responseMeta.innerHTML = "";
    responseBody.textContent = error.message;
    setStatus("The request failed before a usable response came back.");
  } finally {
    submitButton.disabled = false;
  }
}

form.addEventListener("submit", submitInference);
refreshButton.addEventListener("click", refreshDashboard);

for (const button of presetButtons) {
  button.addEventListener("click", () => {
    promptInput.value = button.dataset.prompt || "";
    promptInput.focus();
  });
}

refreshDashboard();
window.setInterval(refreshDashboard, 15000);

if (!promptInput.value && presetButtons.length > 0) {
  promptInput.value = presetButtons[0].dataset.prompt || "";
}
