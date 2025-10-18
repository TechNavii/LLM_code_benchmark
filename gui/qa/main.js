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

let currentSocket = null;
let currentRun = null;

runForm?.addEventListener('submit', startRun);
backButton?.addEventListener('click', () => {
  window.location.href = '/ui/index.html';
});

refreshLeaderboard();
refreshHistory();
resetResultsLayout();

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
  const key = `${event.model || 'unknown'}::${event.question_number}::${event.sample_index ?? 0}`;
  let row = currentRun.rows.get(key);
  if (!row) {
    row = document.createElement('tr');
    row.classList.add('fade-in');
    row.innerHTML = `
      <td>${event.question_number ?? '—'}</td>
      <td>${event.model || '—'}</td>
      <td class="status-cell"></td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td></td>
      <td></td>
      <td></td>
    `;
    resultsBody.appendChild(row);
    currentRun.rows.set(key, row);
  }

  const cells = row.children;
  applyStatus(cells[2], event.status);
  cells[3].textContent = event.duration_seconds != null ? Number(event.duration_seconds).toFixed(2) : '-';
  cells[4].textContent = event.prompt_tokens ?? '-';
  cells[5].textContent = event.completion_tokens ?? '-';
  cells[6].textContent = event.cost_usd != null ? `$${Number(event.cost_usd).toFixed(6)}` : '-';
  cells[7].textContent = event.model_answer || '';
  cells[8].textContent = event.expected_answer || '';
  const judgeInfo = event.judge_decision
    ? `Judge: ${event.judge_decision}${event.judge_rationale ? ` – ${event.judge_rationale}` : ''}`
    : '';
  const judgeError = event.judge_error ? `Judge error: ${event.judge_error}` : '';
  const errorMessage = event.error || '';
  cells[9].textContent = [errorMessage, judgeInfo, judgeError].filter(Boolean).join(' | ');
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
    const modelCompare = (a.model || '').localeCompare(b.model || '');
    if (modelCompare !== 0) return modelCompare;
    return (a.question_number || 0) - (b.question_number || 0);
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
      expected_answer: attempt.expected_answer,
      error: attempt.error,
      judge_decision: attempt.judge_decision,
      judge_rationale: attempt.judge_rationale,
      judge_error: attempt.judge_error,
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
