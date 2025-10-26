const runForm = document.querySelector('#qa-run-form');
const runButton = document.querySelector('#qa-run-button');
const backButton = document.querySelector('#qa-back-button');
const runStatus = document.querySelector('#qa-run-status');
const latestRunIdLabel = document.querySelector('#qa-latest-run-id');
const resultsCard = document.querySelector('#qa-results-card');
const resultsPlaceholder = document.querySelector('#qa-results-placeholder');
const resultsBody = document.querySelector('#qa-results-body');
const aggregateMetrics = document.querySelector('#qa-aggregate-metrics');
const runIdSpan = document.querySelector('#qa-run-id');
const leaderboardBody = document.querySelector('#qa-leaderboard-body');
const leaderboardStatus = document.querySelector('#qa-leaderboard-status');
const historyBody = document.querySelector('#qa-history-body');
const dashboardGrid = document.querySelector('main.dashboard-grid');

const temperatureInput = document.querySelector('#qa-temperature-input');
const maxTokensInput = document.querySelector('#qa-max-tokens-input');
const sampleInput = document.querySelector('#qa-sample-input');
const modelInput = document.querySelector('#qa-model-input');
const providerInput = document.querySelector('#qa-provider-input');
const sweepThinkingLevelsInput = document.querySelector('#qa-sweep-thinking-levels');
const includeThinkingVariantsInput = document.querySelector('#qa-include-thinking-variants');
const modelCapabilitiesNote = document.querySelector('#qa-model-capabilities');

let currentSocket = null;
let currentRun = null;

runForm?.addEventListener('submit', startRun);
backButton?.addEventListener('click', () => {
  window.location.href = '/ui/index.html';
});

refreshLeaderboard();
refreshHistory();
resetResultsLayout();

// Auto-check model capabilities
let capabilityTimer = null;
modelInput?.addEventListener('input', () => {
  if (capabilityTimer) clearTimeout(capabilityTimer);
  capabilityTimer = setTimeout(checkModelCapabilities, 600);
});

function resetResultsLayout(message = 'Start a question run to see live answers and grading.') {
  dashboardGrid?.classList.remove('show-results');
  if (resultsCard) {
    resultsCard.classList.add('results-empty');
    resultsCard.hidden = true;
    setResultsPlaceholder(message);
  }
  if (runIdSpan) {
    runIdSpan.textContent = '—';
  }
  setLatestRunId(null);
}

function setResultsPlaceholder(message) {
  if (!resultsPlaceholder) return;
  const para = resultsPlaceholder.querySelector('p');
  if (para) {
    para.textContent = message;
  } else {
    resultsPlaceholder.textContent = message;
  }
}

function setLatestRunId(runId) {
  if (!latestRunIdLabel) return;
  if (!runId) {
    latestRunIdLabel.textContent = '—';
    latestRunIdLabel.removeAttribute('title');
    return;
  }
  latestRunIdLabel.textContent = runId;
  latestRunIdLabel.title = runId;
}

function mapStatus(status) {
  const normalized = (status || '').toString().toLowerCase();
  if (['pass', 'passed', 'success'].includes(normalized)) {
    return { label: 'PASS', className: 'status-pass', chip: 'pass' };
  }
  if (['fail', 'failed'].includes(normalized)) {
    return { label: 'FAIL', className: 'status-fail', chip: 'fail' };
  }
  if (['error', 'exception'].includes(normalized)) {
    return { label: 'ERROR', className: 'status-error', chip: 'fail' };
  }
  if (!normalized || normalized === 'pending') {
    return { label: 'PENDING', className: 'status-pending', chip: 'pending' };
  }
  return { label: normalized.toUpperCase(), className: 'status-info', chip: 'info' };
}

function applyStatus(cell, status) {
  const { label, className, chip } = mapStatus(status);
  cell.className = `status-cell ${className}`;
  cell.innerHTML = `<span class="status-chip ${chip}">${label}</span>`;
}

function renderStatus(message, level = 'info') {
  if (!runStatus) return;
  runStatus.textContent = message;
  runStatus.className = `status ${level}`;
  runStatus.classList.remove('pop');
  requestAnimationFrame(() => runStatus.classList.add('pop'));
}

function getInputArray(input) {
  const element = document.querySelector(input);
  if (!element) return [];
  return element.value
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

async function startRun(event) {
  event.preventDefault();
  const models = getInputArray('#qa-model-input');
  if (!models.length) {
    renderStatus('Provide at least one model ID', 'error');
    return;
  }

  const sampleValue = Number(sampleInput?.value || 1);
  const temperatureValue = Number(temperatureInput?.value || 0.5);
  const maxTokensValue = Number(maxTokensInput?.value || 200000);

  const payload = {
    models,
    samples: Number.isFinite(sampleValue) && sampleValue > 0 ? sampleValue : 1,
    temperature: Number.isFinite(temperatureValue) ? temperatureValue : 0.5,
    max_tokens: Number.isFinite(maxTokensValue) && maxTokensValue > 0 ? maxTokensValue : 200000,
  };
  const providerValue = providerInput?.value.trim();
  if (providerValue) {
    payload.provider = providerValue;
  }
  if (sweepThinkingLevelsInput && sweepThinkingLevelsInput.checked) {
    payload.sweep_thinking_levels = true;
  }
  if (includeThinkingVariantsInput && includeThinkingVariantsInput.checked) {
    payload.include_thinking_variants = true;
  }

  abortCurrentSocket();
  runButton.disabled = true;
  renderStatus('Launching question run…', 'info');

  try {
    const response = await fetch('/qa/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText || 'Unknown error');
    }
    const data = await response.json();
    renderStatus(`Run ${data.run_id} started…`, 'info');
    setLatestRunId(data.run_id);
    showResultsPlaceholder('Waiting for question answers…', data.run_id);
    listenToRun(data.run_id);
  } catch (error) {
    renderStatus(`Failed to launch run: ${error.message}`, 'error');
    runButton.disabled = false;
    resetResultsLayout();
  }
}

async function checkModelCapabilities() {
  const raw = modelInput?.value || '';
  const models = raw.split(',').map((s) => s.trim()).filter(Boolean);
  if (!models.length) {
    if (modelCapabilitiesNote) modelCapabilitiesNote.textContent = '';
    return;
  }
  const unique = [...new Set(models)].slice(0, 5);
  modelCapabilitiesNote.textContent = 'Checking model capabilities…';
  try {
    const lines = await Promise.all(unique.map(async (m) => {
      try {
        const resp = await fetch(`/models/capabilities?model_id=${encodeURIComponent(m)}`);
        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}));
          throw new Error(detail.detail || resp.statusText);
        }
        const data = await resp.json();
        const thinkingVariant = data.thinking_variant ? ` (variant: ${data.thinking_variant})` : '';
        if (data.supports_thinking) {
          const levels = Array.isArray(data.suggested_levels) && data.suggested_levels.length
            ? ` levels: ${data.suggested_levels.join(', ')}`
            : '';
          return `${m}: supports thinking${thinkingVariant}${levels}`;
        }
        const suggestion = data.thinking_variant ? ` try ${data.thinking_variant}` : '';
        return `${m}: no thinking support detected${suggestion ? ` (${suggestion})` : ''}`;
      } catch (e) {
        return `${m}: ${e.message || 'lookup failed'}`;
      }
    }));
    modelCapabilitiesNote.textContent = lines.join(' • ');
  } catch (err) {
    console.error(err);
    if (modelCapabilitiesNote) modelCapabilitiesNote.textContent = 'Unable to check capabilities right now.';
  }
}

function showResultsPlaceholder(message, runId) {
  if (!resultsCard) return;
  if (message) setResultsPlaceholder(message);
  if (runId && runIdSpan) {
    runIdSpan.textContent = runId;
  }
  resultsCard.hidden = false;
  resultsCard.classList.add('results-empty');
  dashboardGrid?.classList.add('show-results');
}

function hideResultsPlaceholder() {
  if (!resultsCard) return;
  resultsCard.classList.remove('results-empty');
  resultsCard.hidden = false;
}

function abortCurrentSocket() {
  if (currentSocket) {
    currentSocket.close();
    currentSocket = null;
    currentRun = null;
  }
}

function listenToRun(runId) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${window.location.host}/qa/runs/${runId}/stream`);
  currentSocket = socket;
  currentRun = {
    runId,
    rows: new Map(),
    completed: false,
  };

  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    switch (data.type) {
      case 'init':
        setupRunView(data.metadata, runId);
        break;
      case 'attempt':
        updateAttemptRow(data);
        break;
      case 'complete':
        currentRun.completed = true;
        renderRun(data.summary);
        renderStatus(`Run ${runId} complete!`, 'success');
        runButton.disabled = false;
        refreshLeaderboard();
        refreshHistory();
        break;
      case 'error':
        currentRun.completed = true;
        renderStatus(`Run ${runId} failed: ${data.message}`, 'error');
        runButton.disabled = false;
        if (!currentRun.rows.size) {
          showResultsPlaceholder('Run halted before answers were recorded.', runId);
        }
        refreshHistory();
        break;
      default:
        break;
    }
  };

  socket.onerror = (event) => {
    console.error('WebSocket error', event);
    renderStatus('Live updates interrupted', 'error');
  };

  socket.onclose = () => {
    if (!currentRun?.completed) {
      renderStatus('Connection closed before completion', 'error');
      runButton.disabled = false;
      if (!currentRun?.rows?.size) {
        showResultsPlaceholder('Connection closed before any answers were recorded.', currentRun?.runId);
      }
    }
  };
}

function setupRunView(metadata, runId) {
  hideResultsPlaceholder();
  resultsCard.hidden = false;
  dashboardGrid?.classList.add('show-results');
  setLatestRunId(runId);
  runIdSpan.textContent = runId;

  const models = metadata?.models || [];
  const provider = metadata?.provider || 'auto';
  const questionCount = metadata?.question_count ?? 100;
  const samples = metadata?.samples ?? 1;
  aggregateMetrics.innerHTML = '';
  const info = [
    `Models: ${models.join(', ') || '—'}`,
    `Provider: ${provider}`,
    `Questions: ${questionCount}`,
    `Samples: ${samples}`,
    'Accuracy: pending…',
    'Total Cost: pending…',
    'Total Duration: pending…',
  ];
  info.forEach((text) => {
    const span = document.createElement('span');
    span.textContent = text;
    aggregateMetrics.appendChild(span);
  });

  resultsBody.innerHTML = '';
  currentRun.rows.clear();
}

function updateAttemptRow(event) {
  const levelKey = (event.thinking_level_applied || event.thinking_level_requested || 'base');
  const key = `${event.model || 'unknown'}::${event.question_number}::${event.sample_index ?? 0}::${levelKey}`;
  let row = currentRun.rows.get(key);
  if (!row) {
    row = document.createElement('tr');
    row.classList.add('fade-in');
    const levelLabel = levelKey && levelKey !== 'base' ? levelKey : '—';
    row.innerHTML = `
      <td>${event.question_number ?? '—'}</td>
      <td>${event.model || '—'}</td>
      <td>${levelLabel}</td>
      <td class="status-cell"></td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td class="breakable"></td>
      <td class="breakable"></td>
      <td></td>
    `;
    // Track ordering metadata
    row.dataset.question = String(event.question_number ?? '0');
    row.dataset.level = levelKey;
    row.dataset.levelOrder = String(_qaLevelOrder(levelKey));

    // Insert preserving question asc and level order
    const children = Array.from(resultsBody.children);
    let inserted = false;
    for (let i = 0; i < children.length; i++) {
      const r = children[i];
      const rq = Number(r.dataset.question || '0');
      const rl = Number(r.dataset.levelOrder || '999');
      const eq = Number(row.dataset.question || '0');
      const el = Number(row.dataset.levelOrder || '999');
      if (eq < rq || (eq === rq && el < rl)) {
        resultsBody.insertBefore(row, r);
        inserted = true;
        break;
      }
    }
    if (!inserted) {
      resultsBody.appendChild(row);
    }
    currentRun.rows.set(key, row);
  }

  const cells = row.children;
  applyStatus(cells[3], event.status);
  cells[4].textContent = event.duration_seconds != null ? Number(event.duration_seconds).toFixed(2) : '-';
  cells[5].textContent = event.prompt_tokens ?? '-';
  cells[6].textContent = event.completion_tokens ?? '-';
  cells[7].textContent = event.cost_usd != null ? `$${Number(event.cost_usd).toFixed(6)}` : '-';
  const modelAns = (event.model_answer != null && String(event.model_answer).trim())
    ? String(event.model_answer).trim()
    : (event.normalized_answer != null ? String(event.normalized_answer).trim() : '');
  const expectedAns = (event.expected_answer != null && String(event.expected_answer).trim())
    ? String(event.expected_answer).trim()
    : (event.normalized_expected != null ? String(event.normalized_expected).trim() : '');
  cells[8].textContent = modelAns;
  cells[9].textContent = expectedAns;
  const judgeInfo = event.judge_decision
    ? `Judge: ${event.judge_decision}${event.judge_rationale ? ` – ${event.judge_rationale}` : ''}`
    : '';
  const judgeError = event.judge_error ? `Judge error: ${event.judge_error}` : '';
  const errorMessage = event.error || '';
  cells[10].textContent = [errorMessage, judgeInfo, judgeError].filter(Boolean).join(' | ');
}

function _qaLevelOrder(level) {
  const l = String(level || '').toLowerCase();
  if (!l || l === 'base') return 0;
  if (l === 'low') return 1;
  if (l === 'medium') return 2;
  if (l === 'high') return 3;
  if (l.startsWith('unsupported')) return 98;
  return 50;
}

function renderRun(summary) {
  hideResultsPlaceholder();
  resultsCard.hidden = false;
  runIdSpan.textContent = summary.run_id || summary.run_dir?.split('/').pop();
  setLatestRunId(summary.run_id || summary.run_dir);

  const overall = summary.metrics?.overall || {};
  const tokens = summary.token_usage || {};
  const timing = summary.timing || {};
  const accuracy = overall.accuracy != null ? `${(overall.accuracy * 100).toFixed(2)}%` : '—';
  const totalCost = tokens.total_cost_usd != null ? `$${Number(tokens.total_cost_usd).toFixed(6)}` : '—';
  const totalDuration = timing.total_duration_seconds != null ? `${Number(timing.total_duration_seconds).toFixed(2)}s` : '—';
  const promptTokens = tokens.prompt_tokens ?? 0;
  const completionTokens = tokens.completion_tokens ?? 0;

  aggregateMetrics.innerHTML = '';
  const metrics = [
    `Models: ${summary.models?.join(', ') || '—'}`,
    `Provider: ${summary.provider || 'auto'}`,
    `Questions: ${summary.questions?.length ?? '—'}`,
    `Accuracy: ${accuracy}`,
    `Total Cost: ${totalCost}`,
    `Total Duration: ${totalDuration}`,
    `Tokens (P/C): ${promptTokens}/${completionTokens}`,
  ];
  metrics.forEach((text) => {
    const span = document.createElement('span');
    span.textContent = text;
    aggregateMetrics.appendChild(span);
  });

  const attempts = Array.isArray(summary.attempts) ? summary.attempts.slice() : [];
  attempts.sort((a, b) => {
    const aq = (a.question_number || 0);
    const bq = (b.question_number || 0);
    if (aq !== bq) return aq - bq;
    const al = _qaLevelOrder(a.thinking_level_applied || a.thinking_level_requested || 'base');
    const bl = _qaLevelOrder(b.thinking_level_applied || b.thinking_level_requested || 'base');
    if (al !== bl) return al - bl;
    return (a.model || '').localeCompare(b.model || '');
  });

  resultsBody.innerHTML = '';
  currentRun.rows.clear();

  attempts.forEach((attempt) => {
    const usage = attempt.usage || {};
    const mainPrompt = usage.prompt_tokens ?? usage.input_tokens;
    const mainCompletion = usage.completion_tokens ?? usage.output_tokens;
    const combinedPrompt =
      mainPrompt != null || attempt.judge_prompt_tokens != null
        ? Number(mainPrompt ?? 0) + Number(attempt.judge_prompt_tokens ?? 0)
        : null;
    const combinedCompletion =
      mainCompletion != null || attempt.judge_completion_tokens != null
        ? Number(mainCompletion ?? 0) + Number(attempt.judge_completion_tokens ?? 0)
        : null;
    updateAttemptRow({
      model: attempt.model,
      question_number: attempt.question_number,
      sample_index: attempt.sample_index,
      status: attempt.status,
      duration_seconds: attempt.duration_seconds,
      prompt_tokens: combinedPrompt,
      completion_tokens: combinedCompletion,
      cost_usd: attempt.cost_usd,
      model_answer: attempt.model_answer,
      normalized_answer: attempt.normalized_answer,
      expected_answer: attempt.expected_answer,
      normalized_expected: attempt.normalized_expected,
      error: attempt.error,
      judge_decision: attempt.judge_decision,
      judge_rationale: attempt.judge_rationale,
      judge_error: attempt.judge_error,
      thinking_level_applied: attempt.thinking_level_applied,
      thinking_level_requested: attempt.thinking_level_requested,
    });
  });
}

function formatTimestamp(timestamp) {
  if (!timestamp) return '—';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleString();
}

function formatAccuracy(value) {
  if (value == null) return '—';
  return `${(value * 100).toFixed(2)}%`;
}

function formatCost(value) {
  if (value == null) return '—';
  return `$${Number(value).toFixed(6)}`;
}

async function refreshLeaderboard() {
  if (!leaderboardBody) return;
  leaderboardBody.innerHTML = '';
  renderLeaderboardStatus('Loading…', 'info');
  try {
    const response = await fetch('/qa/leaderboard');
    if (!response.ok) throw new Error(response.statusText);
    const data = await response.json();
    const rows = Array.isArray(data.models) ? data.models : [];
    if (!rows.length) {
      renderLeaderboardStatus('No question runs yet.', 'info');
      return;
    }
    renderLeaderboardStatus('', 'info');
    rows.forEach((row) => {
      const tr = document.createElement('tr');
      const levelLabel = row.thinking_level && row.thinking_level !== 'base'
        ? row.thinking_level
        : '—';
      tr.innerHTML = `
        <td>${row.model_id}</td>
        <td>${formatAccuracy(row.accuracy)}</td>
        <td>${formatCost(row.cost_usd)}</td>
        <td>${row.duration_seconds != null ? Number(row.duration_seconds).toFixed(2) : '—'}</td>
        <td>${row.runs ?? '—'}</td>
        <td>${levelLabel}</td>
        <td><button class="danger" data-model="${row.model_id}">Clear</button></td>
      `;
      leaderboardBody.appendChild(tr);
    });
  } catch (error) {
    renderLeaderboardStatus(`Failed to load leaderboard: ${error.message}`, 'error');
  }
}

function renderLeaderboardStatus(message, level = 'info') {
  if (!leaderboardStatus) return;
  leaderboardStatus.textContent = message;
  leaderboardStatus.className = `status ${level}`;
  leaderboardStatus.classList.remove('pop');
  requestAnimationFrame(() => leaderboardStatus.classList.add('pop'));
}

leaderboardBody?.addEventListener('click', async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  const modelId = target.dataset.model;
  if (!modelId) return;
  const confirmed = window.confirm(`Delete stored question runs for "${modelId}"?`);
  if (!confirmed) return;
  target.disabled = true;
  try {
    const response = await fetch(`/qa/leaderboard/${encodeURIComponent(modelId)}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    renderLeaderboardStatus(`Cleared runs for ${modelId}`, 'success');
    refreshLeaderboard();
    refreshHistory();
  } catch (error) {
    renderLeaderboardStatus(`Failed to delete: ${error.message}`, 'error');
    target.disabled = false;
  }
});

async function refreshHistory() {
  if (!historyBody) return;
  historyBody.innerHTML = '';
  try {
    const response = await fetch('/qa/runs');
    if (!response.ok) throw new Error(response.statusText);
    const data = await response.json();
    const rows = Array.isArray(data.runs) ? data.runs : [];
    if (!rows.length) {
      const emptyRow = document.createElement('tr');
      emptyRow.innerHTML = '<td colspan="6" class="empty-state">No question runs yet.</td>';
      historyBody.appendChild(emptyRow);
      return;
    }
    rows.forEach((row) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${row.run_id}</td>
        <td>${formatTimestamp(row.timestamp_utc)}</td>
        <td>${row.model_id || '—'}</td>
        <td>${formatAccuracy(row.accuracy)}</td>
        <td>${formatCost(row.total_cost_usd)}</td>
        <td>${row.total_duration_seconds != null ? Number(row.total_duration_seconds).toFixed(2) : '—'}</td>
      `;
      historyBody.appendChild(tr);
    });
  } catch (error) {
    const row = document.createElement('tr');
    row.innerHTML = `<td colspan="6" class="error">Failed to load history: ${error.message}</td>`;
    historyBody.appendChild(row);
  }
}
