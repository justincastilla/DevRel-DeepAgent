/**
 * DevRel Research Agent - Dashboard Client
 *
 * Manages WebSocket connection and renders real-time agent activity.
 */

// =============================================================================
// State
// =============================================================================

const state = {
    ws: null,
    isRunning: false,
    eventCount: 0,
    currentPhase: null,
    completedPhases: new Set(),
    agentStatuses: {},
};

// =============================================================================
// DOM references
// =============================================================================

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
    form: $("#researchForm"),
    queryInput: $("#queryInput"),
    modelSelect: $("#modelSelect"),
    submitBtn: $("#submitBtn"),
    connectionStatus: $("#connectionStatus"),
    phaseBar: $("#phaseBar"),
    dashboard: $("#dashboard"),
    timeline: $("#timeline"),
    eventCounter: $("#eventCounter"),
    resultSection: $("#resultSection"),
    resultSummary: $("#resultSummary"),
    reportLink: $("#reportLink"),
};

// =============================================================================
// Phase management
// =============================================================================

const PHASE_ORDER = [
    "initializing",
    "checking_cache",
    "fetching_metrics",
    "analyzing_sentiment",
    "web_research",
    "scoring",
    "storing_report",
];

function setPhase(phase) {
    if (!phase || phase === state.currentPhase) return;

    // Mark old phase as completed
    if (state.currentPhase) {
        state.completedPhases.add(state.currentPhase);
    }

    state.currentPhase = phase;

    // Update DOM
    $$(".phase-step").forEach((step) => {
        const stepPhase = step.dataset.phase;
        step.classList.remove("active", "completed");

        if (stepPhase === phase) {
            step.classList.add("active");
        } else if (state.completedPhases.has(stepPhase)) {
            step.classList.add("completed");
        }
    });
}

// =============================================================================
// Agent card management
// =============================================================================

function setAgentStatus(agent, status) {
    const statusEl = $(`#status-${agent}`);
    const cardEl = $(`#card-${agent}`);

    if (!statusEl || !cardEl) return;

    state.agentStatuses[agent] = status;

    statusEl.textContent = status;
    statusEl.className = "agent-status";
    cardEl.classList.remove("active", "done");

    if (status === "running") {
        statusEl.classList.add("running");
        cardEl.classList.add("active");
    } else if (status === "done") {
        statusEl.classList.add("done");
        cardEl.classList.add("done");
    }
}

function addAgentActivity(agent, html) {
    const bodyEl = $(`#activity-${agent}`);
    if (!bodyEl) return;

    // Remove placeholder
    const placeholder = bodyEl.querySelector(".placeholder-text");
    if (placeholder) placeholder.remove();

    const entry = document.createElement("div");
    entry.className = "activity-entry";
    entry.innerHTML = html;

    bodyEl.appendChild(entry);
    bodyEl.scrollTop = bodyEl.scrollHeight;
}

// =============================================================================
// Timeline management
// =============================================================================

function formatTime(isoString) {
    if (!isoString) return "--:--:--";
    const d = new Date(isoString);
    return d.toLocaleTimeString("en-US", {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    });
}

function agentClass(agent) {
    return `agent-${agent}`;
}

function addTimelineEvent(msg) {
    // Remove the empty state
    const empty = dom.timeline.querySelector(".timeline-empty");
    if (empty) empty.remove();

    state.eventCount++;
    dom.eventCounter.textContent = `${state.eventCount} events`;

    const el = document.createElement("div");
    el.className = "timeline-event";

    const time = formatTime(msg.timestamp);
    const agent = msg.agent || "system";

    let bodyHtml = "";

    switch (msg.type) {
        case "tool_start":
            bodyHtml = renderToolStart(msg);
            break;
        case "tool_end":
            bodyHtml = renderToolEnd(msg);
            break;
        case "agent_start":
            el.classList.add("event-status");
            bodyHtml = `<span class="event-detail">${escapeHtml(msg.detail || "Subagent started")}</span>`;
            break;
        case "status":
            el.classList.add("event-status");
            bodyHtml = `<span class="event-detail">${escapeHtml(msg.message)}</span>`;
            break;
        case "error":
            el.classList.add("event-error-row");
            bodyHtml = `<span class="event-error">${escapeHtml(msg.message)}</span>`;
            break;
        default:
            bodyHtml = `<span class="event-detail">${escapeHtml(msg.message || msg.type)}</span>`;
    }

    el.innerHTML = `
        <span class="event-time">${time}</span>
        <span class="event-agent ${agentClass(agent)}">${escapeHtml(agent)}</span>
        <div class="event-body">${bodyHtml}</div>
    `;

    dom.timeline.appendChild(el);
    dom.timeline.scrollTop = dom.timeline.scrollHeight;
}

function renderToolStart(msg) {
    let html = `<span class="event-tool">${escapeHtml(msg.tool)}</span>`;

    if (msg.is_elastic_tool && msg.elastic_tool_id) {
        html += ` <span class="elastic-tool-id">[ES|QL: ${escapeHtml(msg.elastic_tool_id)}]</span>`;
    }

    // Show parameters
    if (msg.params && Object.keys(msg.params).length > 0) {
        const paramsClass = msg.is_elastic_tool
            ? "event-params elastic-highlight"
            : "event-params";

        const paramsStr = Object.entries(msg.params)
            .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
            .join("\n");

        html += `<div class="${paramsClass}">${escapeHtml(paramsStr)}</div>`;
    }

    return html;
}

function renderCacheBadge(cacheHit) {
    if (cacheHit === null || cacheHit === undefined) return "";
    return cacheHit
        ? `<span class="cache-badge cache-hit">cache hit</span>`
        : `<span class="cache-badge cache-miss">cache miss</span>`;
}

function renderToolEnd(msg) {
    let html = `<span class="event-tool">${escapeHtml(msg.tool)}</span>`;
    html += renderCacheBadge(msg.cache_hit);

    if (msg.output_summary) {
        const isError = msg.output_summary.startsWith("Error:");
        const cls = isError ? "event-error" : "event-result";
        html += `<div class="${cls}">${escapeHtml(msg.output_summary)}</div>`;
    }

    return html;
}

function escapeHtml(text) {
    if (!text) return "";
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
    return String(text).replace(/[&<>"']/g, (m) => map[m]);
}

// =============================================================================
// WebSocket connection
// =============================================================================

function startResearch(query, model) {
    // Determine WebSocket URL
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/research`;

    // Reset state
    state.eventCount = 0;
    state.currentPhase = null;
    state.completedPhases.clear();
    state.agentStatuses = {};
    state.isRunning = true;

    // Reset UI
    dom.dashboard.classList.remove("hidden");
    dom.phaseBar.classList.remove("hidden");
    dom.resultSection.classList.add("hidden");
    dom.timeline.innerHTML = '<div class="timeline-empty"><p>Connecting...</p></div>';
    dom.eventCounter.textContent = "0 events";
    dom.submitBtn.disabled = true;
    dom.submitBtn.querySelector("span").textContent = "Running...";

    // Reset agent cards
    ["orchestrator", "metrics-agent", "sentiment-agent", "web-research-agent", "elastic-agent"].forEach((a) => {
        setAgentStatus(a, "idle");
        const body = $(`#activity-${a}`);
        if (body) body.innerHTML = '<p class="placeholder-text">Waiting for activity...</p>';
    });

    // Reset plan card content (card is always visible)
    $("#todoList").innerHTML = '<li class="todo-placeholder">Waiting for orchestrator to create a plan...</li>';
    $("#planProgress").textContent = "";

    // Reset phases
    $$(".phase-step").forEach((s) => s.classList.remove("active", "completed"));

    // Update connection status
    dom.connectionStatus.textContent = "Connecting";
    dom.connectionStatus.className = "status-badge status-running";

    // Create WebSocket
    const ws = new WebSocket(wsUrl);
    state.ws = ws;

    ws.onopen = () => {
        dom.connectionStatus.textContent = "Connected";
        dom.connectionStatus.className = "status-badge status-connected";

        // Send the query
        ws.send(JSON.stringify({ query, model }));
    };

    ws.onmessage = (event) => {
        let msg;
        try {
            msg = JSON.parse(event.data);
        } catch {
            return;
        }

        handleMessage(msg);
    };

    ws.onclose = () => {
        dom.connectionStatus.textContent = "Disconnected";
        dom.connectionStatus.className = "status-badge status-disconnected";
        finishResearch();
    };

    ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        addTimelineEvent({
            type: "error",
            agent: "system",
            message: "WebSocket connection error",
            timestamp: new Date().toISOString(),
        });
    };
}

function handleMessage(msg) {
    // Update phase
    if (msg.phase) {
        setPhase(msg.phase);
    }

    // Update agent status
    if (msg.agent && msg.agent !== "system") {
        if (msg.type === "tool_start" || msg.type === "agent_start") {
            setAgentStatus(msg.agent, "running");
        }
    }

    switch (msg.type) {
        case "status":
            addTimelineEvent(msg);
            break;

        case "tool_start":
            addTimelineEvent(msg);
            addAgentActivity(msg.agent, renderToolStartCard(msg));
            break;

        case "tool_end":
            addTimelineEvent(msg);
            addAgentActivity(msg.agent, renderToolEndCard(msg));
            break;

        case "agent_start":
            addTimelineEvent(msg);
            break;

        case "todos_update":
            renderTodos(msg.todos);
            break;

        case "llm_token":
            // Light-touch: just mark agent as active
            if (msg.agent) {
                setAgentStatus(msg.agent, "running");
            }
            break;

        case "error":
            addTimelineEvent(msg);
            break;

        case "complete":
            handleComplete(msg);
            break;
    }
}

function renderToolStartCard(msg) {
    let html = `<span class="tool-name">${escapeHtml(msg.tool)}</span>`;
    html += ` <span class="tool-status">started</span>`;

    if (msg.is_elastic_tool && msg.elastic_tool_id) {
        html += `<div class="elastic-params">`;
        html += `<span class="param-label">ES|QL Tool:</span> <span class="elastic-tool-id">${escapeHtml(msg.elastic_tool_id)}</span>`;

        if (msg.params) {
            Object.entries(msg.params).forEach(([k, v]) => {
                const val = typeof v === "string" ? v : JSON.stringify(v);
                html += `<br><span class="param-label">${escapeHtml(k)}:</span> ${escapeHtml(val)}`;
            });
        }

        html += `</div>`;
    } else if (msg.params && Object.keys(msg.params).length > 0) {
        const paramsStr = JSON.stringify(msg.params, null, 1);
        if (paramsStr.length < 200) {
            html += `<div style="color: var(--text-muted); font-family: var(--font-mono); font-size: 0.68rem; margin-top: 2px;">${escapeHtml(paramsStr)}</div>`;
        }
    }

    return html;
}

function renderToolEndCard(msg) {
    let html = `<span class="tool-name">${escapeHtml(msg.tool)}</span>`;
    html += renderCacheBadge(msg.cache_hit);

    if (msg.output_summary) {
        if (msg.output_summary.startsWith("Error:")) {
            html += ` <span class="tool-error">${escapeHtml(msg.output_summary)}</span>`;
        } else {
            html += ` <span class="tool-result">${escapeHtml(msg.output_summary)}</span>`;
        }
    } else {
        html += ` <span class="tool-status">completed</span>`;
    }

    return html;
}

// =============================================================================
// Research Plan / Todo rendering
// =============================================================================

function renderTodos(todos) {
    const todoList = $("#todoList");
    const planProgress = $("#planProgress");

    if (!todoList) return;

    todoList.innerHTML = "";

    if (!todos || todos.length === 0) return;

    const completed = todos.filter((t) => t.status === "completed").length;
    planProgress.textContent = `${completed} / ${todos.length}`;

    todos.forEach((todo) => {
        const li = document.createElement("li");
        li.className = `todo-item todo-${todo.status}`;

        const iconMap = {
            completed: "✓",
            in_progress: "▶",
            pending: "○",
        };
        const icon = iconMap[todo.status] || "○";

        li.innerHTML = `<span class="todo-icon">${icon}</span><span class="todo-content">${escapeHtml(todo.content)}</span>`;
        todoList.appendChild(li);
    });
}

function handleComplete(msg) {
    // Mark all phases as completed
    PHASE_ORDER.forEach((p) => state.completedPhases.add(p));
    $$(".phase-step").forEach((s) => {
        s.classList.remove("active");
        s.classList.add("completed");
    });

    // Mark all active agents as done
    Object.keys(state.agentStatuses).forEach((a) => {
        if (state.agentStatuses[a] === "running") {
            setAgentStatus(a, "done");
        }
    });
    setAgentStatus("orchestrator", "done");

    // Show result section
    if (msg.report_url) {
        dom.resultSection.classList.remove("hidden");
        dom.resultSummary.textContent = `Generated ${msg.word_count || "a"} word report across ${msg.event_count || 0} events.`;
        dom.reportLink.href = msg.report_url;
    }

    // Add to timeline
    addTimelineEvent({
        type: "status",
        agent: "orchestrator",
        message: msg.message || "Research complete!",
        timestamp: msg.timestamp,
    });

    finishResearch();
}

function finishResearch() {
    state.isRunning = false;
    dom.submitBtn.disabled = false;
    dom.submitBtn.querySelector("span").textContent = "Research";
}

// =============================================================================
// Event listeners
// =============================================================================

dom.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const query = dom.queryInput.value.trim();
    if (!query || state.isRunning) return;

    const model = dom.modelSelect.value;
    startResearch(query, model);
});

// Allow Ctrl/Cmd+Enter to submit
dom.queryInput.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        dom.form.dispatchEvent(new Event("submit"));
    }
});

// Set initial connection status
dom.connectionStatus.textContent = "Ready";
dom.connectionStatus.className = "status-badge status-disconnected";
