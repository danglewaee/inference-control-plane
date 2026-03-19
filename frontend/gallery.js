const galleryRunButton = document.getElementById("gallery-run");
const galleryStatus = document.getElementById("gallery-status");
const galleryHealth = document.getElementById("gallery-health");
const galleryResponseTitle = document.getElementById("gallery-response-title");
const galleryResponseMeta = document.getElementById("gallery-response-meta");
const galleryResponseBody = document.getElementById("gallery-response-body");

const API = {
  health: "/health",
  infer: "/infer",
};

const SAMPLE_RUNS = [
  {
    title: "Fallback routing",
    input: "Answer in 2 short sentences: why does fallback routing matter for a production AI support assistant?",
  },
  {
    title: "Canary rollout",
    input: "Answer in 2 short sentences: how does canary rollout protect users when a new local model is introduced?",
  },
  {
    title: "Latency vs cost",
    input: "Answer in 2 short sentences: what is the tradeoff between latency and cost in a self-hosted LLM stack?",
  },
];

let sampleIndex = 0;

function setGalleryStatus(message) {
  galleryStatus.textContent = message;
}

function setGalleryHealth(ok, label) {
  galleryHealth.textContent = label;
  galleryHealth.className = `badge ${ok ? "badge-healthy" : "badge-warning"}`;
}

function makeMetaChip(label, variant = "") {
  const chip = document.createElement("span");
  chip.className = `meta-chip ${variant}`.trim();
  chip.textContent = label;
  return chip;
}

function nextSample() {
  const sample = SAMPLE_RUNS[sampleIndex % SAMPLE_RUNS.length];
  sampleIndex += 1;
  return sample;
}

function renderGalleryResponse(result, sample) {
  galleryResponseTitle.textContent = sample.title;
  galleryResponseMeta.innerHTML = "";
  galleryResponseMeta.append(
    makeMetaChip(`${result.latency_ms} ms`),
    makeMetaChip(result.fallback_used ? "fallback path" : "primary path", result.fallback_used ? "flag-warn" : "flag-good"),
    makeMetaChip(result.queued ? "queued" : "direct"),
  );
  galleryResponseBody.textContent = result.result || result.reason || "No response payload returned.";
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed for ${url}`);
  }
  return response.json();
}

async function refreshGalleryHealth() {
  const health = await fetchJson(API.health);
  setGalleryHealth(health.status === "ok", health.status === "ok" ? "Healthy" : "Degraded");
}

async function runGallerySample({ auto = false } = {}) {
  const sample = nextSample();
  galleryRunButton.disabled = true;
  galleryResponseTitle.textContent = sample.title;
  setGalleryStatus(auto ? "Capturing live sample..." : "Refreshing sample...");

  try {
    const result = await fetchJson(API.infer, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input: sample.input,
        priority: "medium",
        latency_budget_ms: 2200,
        policy: "slo_aware",
        max_tokens: 56,
      }),
    });

    renderGalleryResponse(result, sample);
    await refreshGalleryHealth();
    setGalleryStatus(`${result.latency_ms} ms • ${result.fallback_used ? "fallback path" : "primary path"}`);
  } catch (error) {
    galleryResponseMeta.innerHTML = "";
    galleryResponseBody.textContent = error.message;
    setGalleryStatus("Sample failed");
    try {
      await refreshGalleryHealth();
    } catch {
      setGalleryHealth(false, "Offline");
    }
  } finally {
    galleryRunButton.disabled = false;
  }
}

galleryRunButton.addEventListener("click", () => runGallerySample());

(async function initGallery() {
  try {
    await refreshGalleryHealth();
  } catch (error) {
    setGalleryHealth(false, "Offline");
    setGalleryStatus(`State load failed: ${error.message}`);
  }

  await runGallerySample({ auto: true });
})();
