const metricsHealthBadge = document.getElementById("metrics-health-badge");
const metricsRefreshButton = document.getElementById("metrics-refresh-button");
const metricsRequestsTotal = document.getElementById("metrics-requests-total");
const metricsFallbackTotal = document.getElementById("metrics-fallback-total");
const metricsRejectedTotal = document.getElementById("metrics-rejected-total");
const metricsRollbackTotal = document.getElementById("metrics-rollback-total");
const metricsLoadShedTotal = document.getElementById("metrics-load-shed-total");
const metricsColdStartTotal = document.getElementById("metrics-cold-start-total");
const metricsAutoscaleUpTotal = document.getElementById("metrics-autoscale-up-total");
const metricsAutoscaleDownTotal = document.getElementById("metrics-autoscale-down-total");
const metricsEvictionTotal = document.getElementById("metrics-eviction-total");
const metricsLoadedTotal = document.getElementById("metrics-loaded-total");
const metricsRolloutSummary = document.getElementById("metrics-rollout-summary");
const metricsHistoryList = document.getElementById("metrics-history-list");

const API = {
  health: "/health",
  history: "/history?limit=10",
  summary: "/metrics/summary",
};

function setHealthBadge(ok, label) {
  metricsHealthBadge.textContent = label;
  metricsHealthBadge.className = `badge ${ok ? "badge-healthy" : "badge-warning"}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed for ${url}`);
  }
  return response.json();
}

function renderHistory(history) {
  metricsHistoryList.innerHTML = "";
  if (!history.length) {
    metricsHistoryList.innerHTML = '<p class="empty-state">No requests recorded yet.</p>';
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
    metricsHistoryList.append(card);
  }
}

function renderRollout(rollout) {
  if (!rollout || !rollout.canary || !rollout.baseline) {
    metricsRolloutSummary.textContent = "No rollout running.";
    return;
  }
  metricsRolloutSummary.textContent = `${rollout.traffic_percent}% traffic from ${rollout.baseline} to ${rollout.canary}.`;
}

async function refreshMetricsPage() {
  try {
    const [health, summary, history] = await Promise.all([
      fetchJson(API.health),
      fetchJson(API.summary),
      fetchJson(API.history),
    ]);

    setHealthBadge(health.status === "ok", health.status === "ok" ? "System healthy" : "System degraded");
    metricsRequestsTotal.textContent = summary.requests_total;
    metricsFallbackTotal.textContent = summary.fallback_total;
    metricsRejectedTotal.textContent = summary.rejected_total;
    metricsRollbackTotal.textContent = summary.canary_rollbacks_total;
    metricsLoadShedTotal.textContent = summary.load_shed_total;
    metricsColdStartTotal.textContent = summary.cold_start_total;
    metricsAutoscaleUpTotal.textContent = summary.autoscale_up_total;
    metricsAutoscaleDownTotal.textContent = summary.autoscale_down_total;
    metricsEvictionTotal.textContent = summary.eviction_total;
    metricsLoadedTotal.textContent = summary.loaded_backends_total;
    renderRollout(summary.rollout);
    renderHistory(history);
  } catch (error) {
    setHealthBadge(false, "Health check failed");
    metricsRolloutSummary.textContent = `Could not refresh metrics: ${error.message}`;
    metricsHistoryList.innerHTML = '<p class="empty-state">Metrics refresh failed.</p>';
  }
}

metricsRefreshButton.addEventListener("click", refreshMetricsPage);

refreshMetricsPage();
window.setInterval(refreshMetricsPage, 15000);
