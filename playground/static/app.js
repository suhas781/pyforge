const modules = {
  retry: {number:"01",name:"Retry Engine",kicker:"RESILIENCE / RETRY POLICY",description:"Trigger controlled failures and watch bounded exponential backoff recover.",title:"Retry with recovery",copy:"This scenario fails twice with TimeoutError, records retry delays without sleeping, then succeeds on the third attempt.",code:"RetryPolicy(max_attempts=4, initial_delay=0.2)\nretry_on=(TimeoutError,)\nsleep=RecordingSleeper()"},
  logging: {number:"02",name:"JSON Logging",kicker:"TELEMETRY / STRUCTURED LOGS",description:"Inspect a real JSON log record with contextual fields and sensitive-value redaction.",title:"Emit a structured log",copy:"A logger created with get_logger writes through JsonFormatter. The demo includes a deliberately sensitive api_key field to demonstrate redaction.",code:"get_logger('pyforge.playground',\n  context=LogContext(request_id=...,\n  operation=..., component=..., attempt=2))\nJsonFormatter()"},
  config: {number:"03",name:"Environment Configuration",kicker:"CONFIGURATION / TYPED READERS",description:"Read and validate environment-backed strings, booleans, integers and floats.",title:"Parse typed environment values",copy:"Temporary values are set for this run, parsed by PyForge's actual config readers, then restored.",code:"get_env(name, required=True)\nget_env_bool(name, required=True)\nget_env_int(name, minimum=1, maximum=32)\nget_env_float(name, minimum=0.1, maximum=10)"},
  http: {number:"04",name:"HTTP Resilience",kicker:"NETWORK RULES / RETRY ELIGIBILITY",description:"See how HTTP method safety and status codes affect retry decisions.",title:"Evaluate HTTP retry rules",copy:"No network request is sent. The demo asks should_retry_http to evaluate safe and unsafe methods against retryable and non-retryable status codes.",code:"should_retry_http('GET', status_code=503)\nshould_retry_http('POST', status_code=503)\nshould_retry_http('POST', status_code=503,\n  allow_unsafe_method=True)"},
  observe: {number:"05",name:"Retry Observability",kicker:"LIFECYCLE / EVENT STREAM",description:"Inspect scheduled, succeeded and exhausted lifecycle events from the retry engine.",title:"Watch retry lifecycle events",copy:"The observer captures immutable RetryEvent objects while the retry operation recovers. Exception messages are not included.",code:"RetryEventType.SCHEDULED\nRetryEventType.SUCCEEDED\nRetryEventType.EXHAUSTED\nobserver=lambda event: events.append(event)"},
  cache: {number:"06",name:"Memory Cache",kicker:"STORAGE / TTL + LRU",description:"Watch least-recently-used eviction and TTL expiration with a fake monotonic clock.",title:"Exercise cache behavior",copy:"A two-entry cache receives three keys, evicts the least recently used entry, then advances its fake clock to expire a TTL entry instantly.",code:"MemoryCache(max_entries=2, clock=FakeClock())\ncache.set('session:A', value, ttl=5)\nclock.advance(5)"},
  testing: {number:"07",name:"Testing Utilities",kicker:"TEST TOOLING / DETERMINISTIC HELPERS",description:"Explore helpers that make tests deterministic without real waits.",title:"Run deterministic test helpers",copy:"The example increments a counter, scripts a failure followed by success, advances a fake clock and records sleep delays without waiting.",code:"CallCount()\nFailThenReturn(1, 'recovered')\nFakeClock(start=10)\nRecordingSleeper()"}
};
let activeModule = "overview";
const $ = (id) => document.getElementById(id);

function openModule(name) {
  activeModule = name;
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.module === name));
  $("overview").classList.toggle("hidden", name !== "overview");
  $("module-view").classList.toggle("hidden", name === "overview");
  if (name === "overview") {
    $("crumb").textContent = "OVERVIEW";
    $("page-title").innerHTML = 'See what <em>PyForge</em> can do.';
    $("page-subtitle").textContent = "Run real Python examples, inspect results, and explore each engineering primitive.";
    return;
  }
  const item = modules[name];
  $("crumb").textContent = item.name.toUpperCase();
  $("page-title").innerHTML = '<em>' + item.name + '</em>';
  $("page-subtitle").textContent = item.description;
  $("module-kicker").textContent = "MODULE / " + item.number + " · " + item.kicker;
  $("module-title").textContent = item.name;
  $("module-description").textContent = item.description;
  $("scenario-content").innerHTML = '<div class="scenario-body"><h3 class="scenario-title">' + item.title + '</h3><p class="scenario-copy">' + item.copy + '</p><span class="field-label">PYFORGE CALL PATH</span><pre class="scenario-code">' + item.code + '</pre><span class="field-label">EXECUTION MODE</span><div class="fake-input">Local Python · deterministic scenario</div></div>';
  $("output").className = "output-empty";
  $("output").innerHTML = '<div class="empty-symbol">⌁</div><strong>Waiting for execution</strong><p>Run the example to see the actual Python result here.</p>';
}

const RESULT_LABELS = {
  final_result: "Final result",
  total_attempts: "Total attempts",
  retry_delays: "Retry delays",
  lifecycle_events: "Lifecycle events"
};
const EVENT_LABELS = {
  event_type: "Event type",
  attempt: "Attempt number",
  max_attempts: "Maximum attempts",
  delay: "Delay",
  exception_type: "Exception type"
};

function labelFor(key, labels) {
  return (labels && labels[key]) || key;
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isObjectArray(value) {
  return Array.isArray(value) && value.length > 0 && value.every(isRecord);
}

function renderScalar(value) {
  if (value === null) return '<span class="result-null">null</span>';
  return escapeHtml(typeof value === "string" ? value : JSON.stringify(value));
}

function renderJson(value) {
  return '<pre class="result-json">' + escapeHtml(JSON.stringify(value, null, 2)) + "</pre>";
}

function renderTable(rows) {
  const columns = [];
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!columns.includes(key)) columns.push(key);
    });
  });
  const labels = columns.includes("event_type") ? EVENT_LABELS : null;
  const head = columns.map((key) => "<th>" + escapeHtml(labelFor(key, labels)) + "</th>").join("");
  const body = rows.map((row) => {
    const cells = columns.map((key) => {
      if (!Object.prototype.hasOwnProperty.call(row, key)) return "<td></td>";
      const value = row[key];
      if (isRecord(value) || Array.isArray(value)) return "<td>" + renderJson(value) + "</td>";
      return "<td>" + renderScalar(value) + "</td>";
    }).join("");
    return "<tr>" + cells + "</tr>";
  }).join("");
  return '<div class="result-table-wrap"><table class="result-table"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div>";
}

function renderValue(value) {
  if (isObjectArray(value)) return renderTable(value);
  if (isRecord(value)) {
    const fields = Object.keys(value).map((key) => {
      return '<section class="result-field"><h3 class="result-field-label">' + escapeHtml(labelFor(key, RESULT_LABELS)) + '</h3><div class="result-field-body">' + renderValue(value[key]) + "</div></section>";
    }).join("");
    return '<div class="result-fields">' + fields + "</div>";
  }
  if (Array.isArray(value)) return renderJson(value);
  return '<div class="result-field-value">' + renderScalar(value) + "</div>";
}

function renderResult(value) {
  if (isRecord(value)) return renderValue(value);
  return '<div class="result-field">' + renderValue(value) + "</div>";
}

function renderFailure(detail) {
  const lines = [];
  if (detail.status) lines.push("HTTP " + detail.status);
  if (detail.error) lines.push(detail.error);
  if (detail.message) lines.push(detail.message);
  const note = detail.hint ? '<p class="result-note">' + escapeHtml(detail.hint) + "</p>" : "";
  $("output").className = "result-wrap";
  $("output").innerHTML = '<div class="result-status error-status"><span class="status-dot"></span> EXECUTION ERROR</div><pre class="result-json">' + escapeHtml(lines.join("\n")) + "</pre>" + note;
}

async function runDemo() {
  const button = $("run-button");
  button.disabled = true;
  button.innerHTML = "<span>◌</span> Running...";
  $("output").className = "output-empty";
  $("output").innerHTML = '<div class="empty-symbol">◌</div><strong>Executing Python example</strong><p>Calling the installed PyForge package...</p>';
  try {
    let response;
    try {
      response = await fetch("/api/run", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({module: activeModule})
      });
    } catch (error) {
      renderFailure({
        message: "The playground server did not respond.",
        hint: "Start it with python -m playground.server and reload this page."
      });
      return;
    }
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        renderFailure({status: response.status, message: "The server response was not JSON."});
        return;
      }
    }
    if (!response.ok || !isRecord(payload)) {
      renderFailure({
        status: response.status,
        error: payload && payload.error,
        message: (payload && payload.message) || "The request failed."
      });
      return;
    }
    if (!Object.prototype.hasOwnProperty.call(payload, "result")) {
      renderFailure({
        status: response.status,
        error: "Incomplete response",
        message: "The server response did not include a result."
      });
      return;
    }
    const summary = typeof payload.summary === "string" && payload.summary
      ? '<p class="result-summary">' + escapeHtml(payload.summary) + "</p>"
      : "";
    const note = typeof payload.note === "string" && payload.note
      ? '<p class="result-note">' + escapeHtml(payload.note) + "</p>"
      : "";
    $("output").className = "result-wrap";
    $("output").innerHTML = '<div class="result-status"><span class="status-dot"></span> EXECUTION COMPLETE</div>' + summary + renderResult(payload.result) + note;
  } finally {
    button.disabled = false;
    button.innerHTML = "<span>▶</span> Run example";
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}

document.querySelectorAll("[data-module]").forEach((button) => button.addEventListener("click", () => openModule(button.dataset.module)));
document.querySelectorAll("[data-open]").forEach((button) => button.addEventListener("click", () => openModule(button.dataset.open)));
$("run-button").addEventListener("click", runDemo);
openModule("overview");
fetch("/api/health").then((response) => {
  if (!response.ok) throw new Error("Runtime unavailable");
}).catch(() => {
  document.querySelector(".runtime-pill").innerHTML = '<span style="color:#ff8888">●</span> Runtime disconnected';
});
