const form = document.getElementById("infer-form");
const promptInput = document.getElementById("prompt-input");
const prioritySelect = document.getElementById("priority-select");
const policySelect = document.getElementById("policy-select");
const latencyInput = document.getElementById("latency-input");
const tokensInput = document.getElementById("tokens-input");
const submitButton = document.getElementById("submit-button");
const requestStatus = document.getElementById("request-status");
const responseTitle = document.getElementById("response-title");
const responseMeta = document.getElementById("response-meta");
const responseBody = document.getElementById("response-body");
const healthBadge = document.getElementById("health-badge");

const presetButtons = Array.from(document.querySelectorAll(".preset-chip"));

const API = {
  health: "/health",
  infer: "/infer",
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
    makeMetaChip(`${result.latency_ms} ms`),
    makeMetaChip(result.fallback_used ? "fallback path" : "primary path", result.fallback_used ? "flag-warn" : "flag-good"),
    makeMetaChip(result.queued ? "queued" : "direct"),
  );
  responseBody.textContent = result.result || result.reason || "No response payload returned.";
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed for ${url}`);
  }
  return response.json();
}

async function refreshHealth() {
  try {
    const health = await fetchJson(API.health);
    setHealthBadge(health.status === "ok", health.status === "ok" ? "System healthy" : "System degraded");
  } catch (error) {
    setHealthBadge(false, "Health check failed");
    setStatus(`Could not refresh system health: ${error.message}`);
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

  try {
    const result = await fetchJson(API.infer, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderResponse(result);
    setStatus(`Request ${result.request_id} completed.`);
    await refreshHealth();
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

for (const button of presetButtons) {
  button.addEventListener("click", () => {
    promptInput.value = button.dataset.prompt || "";
    promptInput.focus();
  });
}

refreshHealth();
window.setInterval(refreshHealth, 15000);

if (!promptInput.value && presetButtons.length > 0) {
  promptInput.value = presetButtons[0].dataset.prompt || "";
}
