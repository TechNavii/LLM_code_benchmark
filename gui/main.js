const runForm = document.querySelector('#run-form');
const runButton = document.querySelector('#run-button');
const runStatus = document.querySelector('#run-status');
const resultsCard = document.querySelector('#results-card');
const runIdSpan = document.querySelector('#run-id');
const resultsBody = document.querySelector('#results-body');
const aggregateMetrics = document.querySelector('#aggregate-metrics');
const leaderboardBody = document.querySelector('#leaderboard-body');
const historyBody = document.querySelector('#history-body');

let currentSocket = null;
let currentRun = null;

runForm.addEventListener('submit', startRun);
refreshLeaderboard();
refreshHistory();

function mapStatus(status) {
  const normalized = (status || '').toString().trim().toLowerCase();
  if (["pass", "passed", "success"].includes(normalized)) {
    return { label: 'PASS', className: 'status-pass', chip: 'pass' };
  }
  if (["fail", "failed", "error"].includes(normalized)) {
    return { label: 'FAIL', className: 'status-fail', chip: 'fail' };
  }
  if (!normalized || normalized === 'pending' || normalized === 'queued') {
    return { label: 'PENDING', className: 'status-pending', chip: 'pending' };
  }
  if (normalized === 'running') {
    return { label: 'RUNNING', className: 'status-info', chip: 'info' };
  }
  return { label: normalized.toUpperCase(), className: `status-${normalized}`, chip: 'info' };
}

function applyStatus(cell, status) {
  const { label, className, chip } = mapStatus(status);
  cell.className = `status-cell ${className}`;
  cell.innerHTML = `<span class="status-chip ${chip}">${label}</span>`;
}

async function startRun(event) {
  event.preventDefault();
  const models = getInputArray('#model-input');
  if (models.length === 0) {
    renderStatus('Provide at least one model ID', 'error');
    return;
  }

  const tasks = getInputArray('#task-input');
  const payload = {
    models,
    samples: Number(runForm.querySelector('#sample-input').value) || 1,
    include_tests: runForm.querySelector('#include-tests').checked,
    install_deps: runForm.querySelector('#install-deps').checked,
  };
  if (tasks.length) {
    payload.tasks = tasks;
  }

  abortCurrentSocket();
  runButton.disabled = true;
  renderStatus('Launching run…', 'info');
  resultsCard.hidden = true;

  try {
    const response = await fetch('/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || response.statusText || 'Unknown error');
    }
    const data = await response.json();
    renderStatus(`Run ${data.run_id} started…`, 'info');
    listenToRun(data.run_id);
  } catch (error) {
    console.error(error);
    renderStatus(`Run failed to launch: ${error.message}`, 'error');
    runButton.disabled = false;
  }
}

function listenToRun(runId) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${window.location.host}/runs/${runId}/stream`);
  currentSocket = socket;
  currentRun = {
    runId,
    tasks: [],
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
    }
  };
}

function setupRunView(metadata, runId) {
  const { models = [], tasks = [] } = metadata || {};
  resultsCard.hidden = false;
  resultsCard.classList.remove('card-pop');
  requestAnimationFrame(() => resultsCard.classList.add('card-pop'));

  currentRun.tasks = tasks;
  runIdSpan.textContent = runId;
  aggregateMetrics.innerHTML = '';
  const metrics = [
    `Models: ${models.join(', ') || '—'}`,
    `Tasks: ${tasks.length}`,
    'Pass Rate: pending…',
    'Total Cost: pending…',
    'Total Duration: pending…',
  ];
  metrics.forEach((text) => {
    const span = document.createElement('span');
    span.textContent = text;
    aggregateMetrics.appendChild(span);
  });

  resultsBody.innerHTML = '';
  tasks.forEach((task, index) => {
    const row = document.createElement('tr');
    row.classList.add('fade-in');
    row.style.animationDelay = `${index * 30}ms`;
    row.dataset.taskId = task;
    row.innerHTML = `
      <td>${task}</td>
      <td class="status-cell"></td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td></td>
    `;
    applyStatus(row.querySelector('.status-cell'), 'pending');
    resultsBody.appendChild(row);
    currentRun.rows.set(task, row);
  });
}

function updateAttemptRow(event) {
  const { task_id: taskId, status, duration_seconds: duration, prompt_tokens: prompt, completion_tokens: completion, cost_usd: cost, error } = event;
  const row = currentRun.rows.get(taskId);
  if (!row) {
    return;
  }
  const cells = row.children;
  const statusCell = cells[1];
  applyStatus(statusCell, status);
  cells[2].textContent = duration != null ? duration.toFixed(2) : '-';
  cells[3].textContent = prompt != null ? prompt : '-';
  cells[4].textContent = completion != null ? completion : '-';
  cells[5].textContent = cost != null ? `$${cost.toFixed(6)}` : '-';
  cells[6].textContent = error || '';
}

function renderRun(summary) {
  resultsCard.hidden = false;
  runIdSpan.textContent = summary.run_id || summary.run_dir?.split('/').pop();

  aggregateMetrics.innerHTML = '';
  const accuracy = summary.metrics?.overall?.macro_model_accuracy ?? 0;
  const passRate = `${(accuracy * 100).toFixed(2)}%`;
  const totalCost = (summary.token_usage?.total_cost_usd ?? 0).toFixed(6);
  const totalDuration = (summary.timing?.total_duration_seconds ?? 0).toFixed(2);
  const promptTokens = summary.token_usage?.prompt_tokens ?? 0;
  const completionTokens = summary.token_usage?.completion_tokens ?? 0;

  const metrics = [
    `Models: ${summary.models.join(', ')}`,
    `Tasks: ${summary.tasks.length}`,
    `Pass Rate: ${passRate}`,
    `Total Cost: $${totalCost}`,
    `Total Duration: ${totalDuration}s`,
    `Tokens (P/C): ${promptTokens}/${completionTokens}`,
  ];
  metrics.forEach((text) => {
    const span = document.createElement('span');
    span.textContent = text;
    aggregateMetrics.appendChild(span);
  });

  resultsBody.innerHTML = '';
  summary.attempts.forEach((attempt, index) => {
    const row = document.createElement('tr');
    row.classList.add('fade-in');
    row.style.animationDelay = `${index * 40}ms`;
    const usage = attempt.usage || {};
    const prompt = usage.prompt_tokens ?? usage.input_tokens;
    const completion = usage.completion_tokens ?? usage.output_tokens;
    const cost = attempt.cost_usd != null ? `$${attempt.cost_usd.toFixed(6)}` : '-';
    const duration = attempt.duration_seconds != null ? attempt.duration_seconds.toFixed(2) : '-';
    row.innerHTML = `
      <td>${attempt.task_id}</td>
      <td class="status-cell"></td>
      <td>${duration}</td>
      <td>${prompt ?? '-'}</td>
      <td>${completion ?? '-'}</td>
      <td>${cost}</td>
      <td>${attempt.error ?? ''}</td>
    `;
    applyStatus(row.querySelector('.status-cell'), attempt.status);
    resultsBody.appendChild(row);
  });
}

function renderStatus(message, level) {
  runStatus.textContent = message;
  runStatus.className = `status ${level}`;
  runStatus.classList.remove('pop');
  requestAnimationFrame(() => runStatus.classList.add('pop'));
}

async function refreshLeaderboard() {
  const response = await fetch('/leaderboard');
  if (!response.ok) return;
  const data = await response.json();
  leaderboardBody.innerHTML = '';
  data.models.forEach((model) => {
    const row = document.createElement('tr');
    const accuracyValue = model.best_accuracy;
    const accuracyText = accuracyValue != null ? `${(accuracyValue * 100).toFixed(2)}%` : '—';
    const bestCost = model.cost_at_best != null ? `$${Number(model.cost_at_best).toFixed(6)}` : '—';
    const bestDuration = model.duration_at_best != null ? Number(model.duration_at_best).toFixed(2) : '-';
    row.innerHTML = `
      <td class="breakable">${model.model_id}</td>
      <td>${accuracyText}</td>
      <td>${bestCost}</td>
      <td>${bestDuration}</td>
      <td>${model.runs}</td>
    `;
    leaderboardBody.appendChild(row);
  });
}

async function refreshHistory() {
  const response = await fetch('/runs');
  if (!response.ok) return;
  const data = await response.json();
  historyBody.innerHTML = '';
  data.runs.forEach((run, index) => {
    const row = document.createElement('tr');
    row.classList.add('fade-in');
    row.style.animationDelay = `${index * 30}ms`;
    const accuracy = (run.accuracy ?? 0) * 100;
    const displayRunId = formatRunId(run.run_id);
    const runHref = buildRunDetailHref(run.run_id);
    row.innerHTML = `
      <td class="breakable"><a href="${runHref}" target="_blank"></a></td>
      <td>${run.timestamp_utc}</td>
      <td class="breakable">${run.model_id}</td>
      <td>${accuracy.toFixed(2)}%</td>
      <td>$${(run.total_cost_usd ?? 0).toFixed(6)}</td>
      <td>${run.total_duration_seconds != null ? run.total_duration_seconds.toFixed(2) : '-'}</td>
    `;
    const runLink = row.querySelector('a');
    runLink.textContent = displayRunId;
    runLink.title = `Open run ${run.run_id}`;
    runLink.rel = 'noopener noreferrer';
    historyBody.appendChild(row);
  });
}

function getInputArray(selector) {
  return runForm
    .querySelector(selector)
    .value.split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

function abortCurrentSocket() {
  if (currentSocket) {
    currentSocket.onmessage = null;
    currentSocket.onclose = null;
    currentSocket.onerror = null;
    currentSocket.close();
    currentSocket = null;
  }
}

function formatRunId(runId) {
  if (!runId) {
    return 'View';
  }
  const baseId = String(runId).split('/').pop();
  if (!baseId) {
    return 'View Run';
  }
  if (baseId.length <= 12) {
    return baseId;
  }
  return `${baseId.slice(0, 6)}…${baseId.slice(-4)}`;
}

function buildRunDetailHref(runId) {
  if (!runId) {
    return '/ui/run.html';
  }
  return `/ui/run.html?run_id=${encodeURIComponent(runId)}`;
}
