const backendsHealthBadge = document.getElementById("backends-health-badge");
const backendsRefreshButton = document.getElementById("backends-refresh-button");
const backendsOnlineTotal = document.getElementById("backends-online-total");
const backendsHealthyTotal = document.getElementById("backends-healthy-total");
const backendsDegradedTotal = document.getElementById("backends-degraded-total");
const backendsQueuePeak = document.getElementById("backends-queue-peak");
const backendsLoadedTotal = document.getElementById("backends-loaded-total");
const backendsAutoscaleTotal = document.getElementById("backends-autoscale-total");
const backendsList = document.getElementById("backends-list");

const API = {
  health: "/health",
  backends: "/backends",
};

function setHealthBadge(ok, label) {
  backendsHealthBadge.textContent = label;
  backendsHealthBadge.className = `badge ${ok ? "badge-healthy" : "badge-warning"}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed for ${url}`);
  }
  return response.json();
}

function renderBackends(backends) {
  const healthyCount = backends.filter((backend) => backend.healthy).length;
  const degradedCount = backends.length - healthyCount;
  const queuePeak = backends.reduce((maxQueue, backend) => Math.max(maxQueue, backend.queue_depth), 0);
  const loadedCount = backends.filter((backend) => backend.residency_state !== "unloaded").length;
  const autoscaleEvents = backends.reduce((count, backend) => count + backend.autoscale_up_events + backend.autoscale_down_events, 0);

  backendsOnlineTotal.textContent = backends.length;
  backendsHealthyTotal.textContent = healthyCount;
  backendsDegradedTotal.textContent = degradedCount;
  backendsQueuePeak.textContent = queuePeak;
  backendsLoadedTotal.textContent = loadedCount;
  backendsAutoscaleTotal.textContent = autoscaleEvents;

  backendsList.innerHTML = "";
  if (!backends.length) {
    backendsList.innerHTML = '<p class="empty-state">No backend state available.</p>';
    return;
  }

  for (const backend of backends) {
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
        <span class="stat-pill">${backend.residency_state}</span>
        <span class="stat-pill">p95 ${backend.p95_latency_ms} ms</span>
        <span class="stat-pill">ewma ${backend.ewma_latency_ms} ms</span>
        <span class="stat-pill">wait ${backend.estimated_wait_ms} ms</span>
        <span class="stat-pill">outstanding ${backend.outstanding_requests}</span>
        <span class="stat-pill">queue ${backend.queue_depth}</span>
        <span class="stat-pill">capacity ${backend.base_concurrency}->${backend.max_concurrency}/${backend.max_concurrency_limit}</span>
        <span class="stat-pill">inflight ${backend.inflight}/${backend.max_concurrency}</span>
        <span class="stat-pill">queue cap ${backend.max_queue_depth}</span>
        <span class="stat-pill">cold starts ${backend.cold_starts}</span>
        <span class="stat-pill">shed ${backend.shed_events}</span>
        <span class="stat-pill">up ${backend.autoscale_up_events}</span>
        <span class="stat-pill">down ${backend.autoscale_down_events}</span>
        <span class="stat-pill">evict ${backend.evictions}</span>
        <span class="stat-pill">error ${Math.round(backend.error_rate * 100)}%</span>
        <span class="stat-pill">cost ${backend.cost_weight}</span>
      </div>
    `;
    backendsList.append(card);
  }
}

async function refreshBackendsPage() {
  try {
    const [health, backends] = await Promise.all([
      fetchJson(API.health),
      fetchJson(API.backends),
    ]);

    setHealthBadge(health.status === "ok", health.status === "ok" ? "System healthy" : "System degraded");
    renderBackends(backends);
  } catch (error) {
    setHealthBadge(false, "Health check failed");
    backendsList.innerHTML = `<p class="empty-state">Could not refresh backends: ${error.message}</p>`;
  }
}

backendsRefreshButton.addEventListener("click", refreshBackendsPage);

refreshBackendsPage();
window.setInterval(refreshBackendsPage, 15000);
