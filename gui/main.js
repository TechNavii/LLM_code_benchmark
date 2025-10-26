import { TASK_LANGUAGE } from './task-language.js';

const LANGUAGE_LABELS = {
  javascript: 'JS',
  python: 'PY',
  go: 'GO',
  cpp: 'C++',
  html: 'HTML',
  rust: 'RS',
  default: '??',
};

const runForm = document.querySelector('#run-form');
const runButton = document.querySelector('#run-button');
const runStatus = document.querySelector('#run-status');
const resultsCard = document.querySelector('#results-card');
const runIdSpan = document.querySelector('#run-id');
const resultsBody = document.querySelector('#results-body');
const aggregateMetrics = document.querySelector('#aggregate-metrics');
const leaderboardBody = document.querySelector('#leaderboard-body');
const historyBody = document.querySelector('#history-body');
const dashboardGrid = document.querySelector('main.dashboard-grid');
const resultsPlaceholder = document.querySelector('#results-placeholder');
const latestRunIdLabel = document.querySelector('#latest-run-id');
const temperatureInput = runForm.querySelector('#temperature-input');
const maxTokensInput = runForm.querySelector('#max-tokens-input');
const responseTextInput = runForm.querySelector('#response-text');
const allowIncompleteDiffsInput = runForm.querySelector('#allow-incomplete-diffs');
const allowDiffRewriteInput = runForm.querySelector('#allow-diff-rewrite');
const providerInput = runForm.querySelector('#provider-input');
const thinkingLevelInput = runForm.querySelector('#thinking-level-input');
const includeThinkingVariantsInput = runForm.querySelector('#include-thinking-variants');
const sweepThinkingLevelsInput = runForm.querySelector('#sweep-thinking-levels');
const modelCapabilitiesNote = document.querySelector('#model-capabilities');
const openQaButton = document.querySelector('#open-qa-button');

let currentSocket = null;
let currentRun = null;

runForm.addEventListener('submit', startRun);
if (openQaButton) {
  openQaButton.addEventListener('click', () => {
    window.location.href = '/ui/qa/index.html';
  });
}
refreshLeaderboard();
refreshHistory();
resetResultsLayout();

let capabilityTimer = null;
const modelInput = runForm.querySelector('#model-input');
modelInput?.addEventListener('input', () => {
  if (capabilityTimer) {
    clearTimeout(capabilityTimer);
  }
  capabilityTimer = setTimeout(checkModelCapabilities, 600);
});


function setResultsPlaceholder(message) {
  if (!resultsPlaceholder) return;
  const holder = resultsPlaceholder.querySelector('p') || resultsPlaceholder;
  holder.textContent = message;
}

function setLatestRunId(runId) {
  if (!latestRunIdLabel) return;
  if (!runId) {
    latestRunIdLabel.textContent = '—';
    latestRunIdLabel.removeAttribute('title');
    return;
  }
  const displayId = formatRunId(runId);
  latestRunIdLabel.textContent = displayId;
  latestRunIdLabel.title = runId;
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

function resetResultsLayout(message = 'Start a run to see live attempt results here.') {
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

function renderTaskName(taskId) {
  const language = (TASK_LANGUAGE && TASK_LANGUAGE[taskId]) || 'default';
  const label = LANGUAGE_LABELS[language] || LANGUAGE_LABELS.default;
  const iconClass = LANGUAGE_LABELS[language] ? language : 'default';
  return `<span class="task-name"><span class="task-icon ${iconClass}">${label}</span><span>${taskId}</span></span>`;
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
  if (temperatureInput) {
    const value = Number(temperatureInput.value);
    if (!Number.isNaN(value)) {
      payload.temperature = value;
    }
  }
  if (maxTokensInput) {
    const value = parseInt(maxTokensInput.value, 10);
    if (!Number.isNaN(value) && value > 0) {
      payload.max_tokens = value;
    }
  }
  const providerValue = providerInput?.value.trim();
  if (providerValue) {
    payload.provider = providerValue;
  }
  const thinkingValue = thinkingLevelInput?.value.trim();
  if (thinkingValue) {
    payload.thinking_level = thinkingValue;
  }
  if (includeThinkingVariantsInput) {
    payload.include_thinking_variants = includeThinkingVariantsInput.checked;
  }
  if (sweepThinkingLevelsInput) {
    payload.sweep_thinking_levels = !!sweepThinkingLevelsInput.checked;
  }
  if (responseTextInput) {
    const responseText = responseTextInput.value.trim();
    if (responseText) {
      payload.response_text = responseText;
    }
  }
  if (allowIncompleteDiffsInput) {
    payload.allow_incomplete_diffs = allowIncompleteDiffsInput.checked;
  }
  if (allowDiffRewriteInput) {
    payload.allow_diff_rewrite_fallback = allowDiffRewriteInput.checked;
  }
  if (tasks.length) {
    payload.tasks = tasks;
  }

  abortCurrentSocket();
  runButton.disabled = true;
  renderStatus('Launching run…', 'info');

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
    setLatestRunId(data.run_id);
    showResultsPlaceholder('Waiting for live attempt updates…', data.run_id);
    listenToRun(data.run_id);
  } catch (error) {
    console.error(error);
    renderStatus(`Run failed to launch: ${error.message}`, 'error');
    runButton.disabled = false;
    resetResultsLayout('Start a run to see live attempt results here.');
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
        if (!currentRun.rows.size) {
          showResultsPlaceholder('Run halted before attempts could start.', runId);
        }
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
        showResultsPlaceholder('Connection closed before run results were available.', currentRun?.runId);
      }
    }
  };
}

function setupRunView(metadata, runId) {
  const { models = [], tasks = [], provider } = metadata || {};
  hideResultsPlaceholder();
  resultsCard.hidden = false;
  dashboardGrid?.classList.add('show-results');
  setLatestRunId(runId);
  resultsCard.classList.remove('card-pop');
  requestAnimationFrame(() => resultsCard.classList.add('card-pop'));

  currentRun.tasks = tasks;
  runIdSpan.textContent = runId;
  aggregateMetrics.innerHTML = '';
  const metrics = [
    `Models: ${models.join(', ') || '—'}`,
    `Provider: ${provider || 'auto'}`,
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
  currentRun.rows.clear();
}

function updateAttemptRow(event) {
  const { task_id: taskId, status, duration_seconds: duration, prompt_tokens: prompt, completion_tokens: completion, cost_usd: cost, error } = event;
  const levelKey = event.thinking_level_applied || event.thinking_level_requested || 'base';
  const rowKey = `${taskId}::${levelKey}`;
  let row = currentRun.rows.get(rowKey);
  if (!row) {
    row = document.createElement('tr');
    row.classList.add('fade-in');
    row.dataset.task = taskId;
    row.dataset.level = levelKey;
    row.dataset.levelOrder = String(levelOrder(levelKey));
    const levelLabel = formatThinkingLevel(levelKey);
    row.innerHTML = `
      <td>${renderTaskName(taskId)}</td>
      <td>${levelLabel}</td>
      <td class="status-cell"></td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td></td>
    `;
    // Insert in order: task asc, then level order
    const children = Array.from(resultsBody.children);
    let inserted = false;
    for (let i = 0; i < children.length; i++) {
      const r = children[i];
      const rt = r.dataset.task || '';
      const rl = Number(r.dataset.levelOrder || '999');
      const cmp = rt.localeCompare(taskId);
      const el = Number(row.dataset.levelOrder || '999');
      if (cmp > 0 || (cmp === 0 && el < rl)) {
        resultsBody.insertBefore(row, r);
        inserted = true;
        break;
      }
    }
    if (!inserted) resultsBody.appendChild(row);
    currentRun.rows.set(rowKey, row);
  }
  const cells = row.children;
  applyStatus(cells[2], status);
  cells[3].textContent = duration != null ? duration.toFixed(2) : '-';
  cells[4].textContent = prompt != null ? prompt : '-';
  cells[5].textContent = completion != null ? completion : '-';
  cells[6].textContent = cost != null ? `$${Number(cost).toFixed(6)}` : '-';
  cells[7].textContent = error || '';
}

function renderRun(summary) {
  hideResultsPlaceholder();
  resultsCard.hidden = false;
  runIdSpan.textContent = summary.run_id || summary.run_dir?.split('/').pop();
  setLatestRunId(summary.run_id || summary.run_dir);

  aggregateMetrics.innerHTML = '';
  const accuracy = summary.metrics?.overall?.macro_model_accuracy ?? 0;
  const passRate = `${(accuracy * 100).toFixed(2)}%`;
  const totalCost = (summary.token_usage?.total_cost_usd ?? 0).toFixed(6);
  const totalDuration = (summary.timing?.total_duration_seconds ?? 0).toFixed(2);
  const promptTokens = summary.token_usage?.prompt_tokens ?? 0;
  const completionTokens = summary.token_usage?.completion_tokens ?? 0;

  const metrics = [
    `Models: ${summary.models.join(', ')}`,
    `Provider: ${summary.provider || 'auto'}`,
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
  const attempts = Array.isArray(summary.attempts) ? summary.attempts.slice() : [];
  attempts.sort((a, b) => {
    const ta = a.task_id || '';
    const tb = b.task_id || '';
    const cmp = ta.localeCompare(tb);
    if (cmp !== 0) return cmp;
    const la = levelOrder(a.thinking_level_applied || a.thinking_level_requested || 'base');
    const lb = levelOrder(b.thinking_level_applied || b.thinking_level_requested || 'base');
    return la - lb;
  });
  attempts.forEach((attempt, index) => {
    const usage = attempt.usage || {};
    const prompt = usage.prompt_tokens ?? usage.input_tokens;
    const completion = usage.completion_tokens ?? usage.output_tokens;
    const cost = attempt.cost_usd != null ? `$${Number(attempt.cost_usd).toFixed(6)}` : '-';
    const duration = attempt.duration_seconds != null ? Number(attempt.duration_seconds).toFixed(2) : '-';
    const levelLabel = formatThinkingLevel(attempt.thinking_level_applied || attempt.thinking_level_requested || 'base');
    const row = document.createElement('tr');
    row.classList.add('fade-in');
    row.style.animationDelay = `${index * 30}ms`;
    row.innerHTML = `
      <td>${renderTaskName(attempt.task_id)}</td>
      <td>${levelLabel}</td>
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
    const rawLevel = model.thinking_level || 'base';
    const levelLabel = formatThinkingLevel(rawLevel);
    row.innerHTML = `
      <td class="breakable">${model.model_id}</td>
      <td>${accuracyText}</td>
      <td>${bestCost}</td>
      <td>${bestDuration}</td>
      <td>${model.runs}</td>
      <td>${levelLabel}</td>
      <td class="actions-cell">
        <button type="button" class="ghost copy-model" data-action="copy-model" data-model="${model.model_id}">Copy ID</button>
        <button type="button" class="ghost danger" data-action="delete-model" data-model="${model.model_id}" data-level="${rawLevel}">Delete</button>
      </td>
    `;
    leaderboardBody.appendChild(row);
  });
}

function formatThinkingLevel(level) {
  if (!level || level === 'base') {
    return '—';
  }
  if (level.startsWith('unsupported')) {
    return level
      .replace('unsupported', 'Unsupported')
      .replace(/\((.+)\)/, (_, inner) => inner ? ` (${inner})` : '');
  }
  return level.replace(/\b\w/g, (char) => char.toUpperCase());
}

function levelOrder(level) {
  const l = String(level || '').toLowerCase();
  if (!l || l === 'base') return 0;
  if (l === 'low') return 1;
  if (l === 'medium') return 2;
  if (l === 'high') return 3;
  if (l.startsWith('unsupported')) return 98;
  return 50;
}

leaderboardBody?.addEventListener('click', async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  if (target.dataset.action === 'copy-model') {
    const modelId = target.dataset.model;
    if (!modelId) return;
    try {
      await navigator.clipboard.writeText(modelId);
      renderStatus(`Copied "${modelId}" to clipboard`, 'success');
    } catch (error) {
      console.error(error);
      renderStatus('Failed to copy model id', 'error');
    }
  } else if (target.dataset.action === 'delete-model') {
    const modelId = target.dataset.model;
    const level = target.dataset.level;
    if (!modelId) return;
    const confirmed = window.confirm(`Delete stored runs for "${modelId}"${level && level !== 'base' ? ` (${level})` : ''}?`);
    if (!confirmed) return;
    target.disabled = true;
    try {
      const query = level && level !== 'base' ? `?thinking_level=${encodeURIComponent(level)}` : '';
      const response = await fetch(`/leaderboard/${encodeURIComponent(modelId)}${query}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || response.statusText || 'Failed');
      }
      renderStatus(`Deleted runs for ${modelId}`, 'success');
      await refreshLeaderboard();
      await refreshHistory();
    } catch (error) {
      console.error(error);
      renderStatus(`Failed to delete runs: ${error.message}`, 'error');
      target.disabled = false;
    }
  }
});

async function checkModelCapabilities() {
  const models = getInputArray('#model-input');
  if (!models.length) {
    if (modelCapabilitiesNote) modelCapabilitiesNote.textContent = '';
    return;
  }
  const uniqueModels = [...new Set(models)].slice(0, 5);
  modelCapabilitiesNote.textContent = 'Checking model capabilities…';
  try {
    const results = await Promise.all(uniqueModels.map(async (model) => {
      try {
        const response = await fetch(`/models/capabilities?model_id=${encodeURIComponent(model)}`);
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(error.detail || response.statusText);
        }
        const data = await response.json();
        const thinkingVariant = data.thinking_variant ? ` (variant: ${data.thinking_variant})` : '';
        if (data.supports_thinking) {
          const levels = Array.isArray(data.suggested_levels) && data.suggested_levels.length
            ? ` levels: ${data.suggested_levels.join(', ')}`
            : '';
          const budgets = [];
          if (data.supports_budget_tokens) budgets.push('budget_tokens');
          if (data.supports_budget_seconds) budgets.push('budget_seconds');
          const budgetText = budgets.length ? `; also supports ${budgets.join(' & ')}` : '';
          return `${model}: supports thinking${thinkingVariant}${levels}${budgetText}`;
        }
        const suggestion = data.thinking_variant ? ` try ${data.thinking_variant}` : '';
        return `${model}: no thinking support detected${suggestion ? ` (${suggestion})` : ''}`;
      } catch (error) {
        return `${model}: ${error.message ?? 'lookup failed'}`;
      }
    }));
    modelCapabilitiesNote.textContent = results.join(' • ');
  } catch (error) {
    console.error(error);
    if (modelCapabilitiesNote) {
      modelCapabilitiesNote.textContent = 'Unable to check model capabilities right now.';
    }
  }
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
