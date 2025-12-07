import { TASK_LANGUAGE } from './task-language.js';
import {
  showToast,
  mapStatus,
  applyStatus,
  createProgressBar,
  makeSortable,
  createFilterBar,
  createPagination,
  createCopyButton,
  exportToCSV,
  exportToJSON,
  showTableSkeleton,
  registerShortcut,
  formatNumber,
  formatCost,
  formatPercent,
  formatTimestamp,
  renderTaskName,
  getTaskLanguage,
  LANGUAGE_LABELS
} from './components.js';

// ============================================================================
// DOM Elements
// ============================================================================

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
const temperatureInput = runForm?.querySelector('#temperature-input');
const maxTokensInput = runForm?.querySelector('#max-tokens-input');
const responseTextInput = runForm?.querySelector('#response-text');
const allowIncompleteDiffsInput = runForm?.querySelector('#allow-incomplete-diffs');
const allowDiffRewriteInput = runForm?.querySelector('#allow-diff-rewrite');
const providerInput = runForm?.querySelector('#provider-input');
const thinkingLevelInput = runForm?.querySelector('#thinking-level-input');
const includeThinkingVariantsInput = runForm?.querySelector('#include-thinking-variants');
const sweepThinkingLevelsInput = runForm?.querySelector('#sweep-thinking-levels');
const modelCapabilitiesNote = document.querySelector('#model-capabilities');
const progressContainer = document.querySelector('#progress-container');
const resultsFilterContainer = document.querySelector('#results-filter-container');
const historyPaginationContainer = document.querySelector('#history-pagination');
const resultsTable = document.querySelector('#results-table');
const historyTable = document.querySelector('#history-table');
const leaderboardTable = document.querySelector('.leaderboard-card table');
const exportCsvBtn = document.querySelector('#export-csv-btn');
const exportJsonBtn = document.querySelector('#export-json-btn');
const exportHistoryCsvBtn = document.querySelector('#export-history-csv');

// ============================================================================
// State
// ============================================================================

let currentSocket = null;
let currentRun = null;
let progressBar = null;
let resultsFilter = null;
let historyPagination = null;
let allHistoryData = [];
let allResultsData = [];

// ============================================================================
// Initialization
// ============================================================================

runForm?.addEventListener('submit', startRun);
refreshLeaderboard();
refreshHistory();
resetResultsLayout();

// Initialize progress bar
if (progressContainer) {
  progressBar = createProgressBar(progressContainer);
  progressBar.hide();
}

// Initialize results filter with language support
if (resultsFilterContainer) {
  resultsFilter = createFilterBar(resultsFilterContainer, {
    searchPlaceholder: 'Search tasks...',
    showLanguageFilter: true
  });
  resultsFilter.onFilter(applyResultsFilter);
  resultsFilter.element.hidden = true;
}

// Initialize history pagination
if (historyPaginationContainer) {
  historyPagination = createPagination(historyPaginationContainer, { pageSize: 20 });
  historyPagination.onPageChange(renderHistoryPage);
}

// Make tables sortable
if (resultsTable) makeSortable(resultsTable);
if (historyTable) makeSortable(historyTable);
if (leaderboardTable) makeSortable(leaderboardTable);

// Export buttons
exportCsvBtn?.addEventListener('click', () => {
  if (allResultsData.length) {
    const data = allResultsData.map(a => ({
      task_id: a.task_id,
      language: getTaskLanguage(a.task_id, TASK_LANGUAGE),
      thinking_level: a.thinking_level_applied || a.thinking_level_requested || 'base',
      status: a.status,
      duration_seconds: a.duration_seconds,
      prompt_tokens: a.usage?.prompt_tokens ?? a.usage?.input_tokens,
      completion_tokens: a.usage?.completion_tokens ?? a.usage?.output_tokens,
      cost_usd: a.cost_usd,
      error: a.error || ''
    }));
    exportToCSV(data, `run_${currentRun?.runId || 'results'}.csv`);
  }
});

exportJsonBtn?.addEventListener('click', () => {
  if (allResultsData.length) {
    exportToJSON(allResultsData, `run_${currentRun?.runId || 'results'}.json`);
  }
});

exportHistoryCsvBtn?.addEventListener('click', () => {
  if (allHistoryData.length) {
    const data = allHistoryData.map(r => ({
      run_id: r.run_id,
      timestamp_utc: r.timestamp_utc,
      model_id: r.model_id,
      accuracy: r.accuracy,
      total_cost_usd: r.total_cost_usd,
      total_duration_seconds: r.total_duration_seconds
    }));
    exportToCSV(data, 'run_history.csv');
  }
});

// Model capability check debounce
let capabilityTimer = null;
const modelInput = runForm?.querySelector('#model-input');
modelInput?.addEventListener('input', () => {
  if (capabilityTimer) clearTimeout(capabilityTimer);
  capabilityTimer = setTimeout(checkModelCapabilities, 600);
});

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

registerShortcut('r', () => {
  runForm?.querySelector('#model-input')?.focus();
}, 'Focus model input');

registerShortcut('l', () => {
  document.querySelector('.leaderboard-card')?.scrollIntoView({ behavior: 'smooth' });
}, 'Scroll to leaderboard');

registerShortcut('h', () => {
  document.querySelector('.recent-card')?.scrollIntoView({ behavior: 'smooth' });
}, 'Scroll to history');

registerShortcut('q', () => {
  window.location.href = '/ui/qa/index.html';
}, 'Go to QA benchmark');

// ============================================================================
// Results Filtering
// ============================================================================

function applyResultsFilter(filters) {
  const rows = resultsBody?.querySelectorAll('tr') || [];
  rows.forEach(row => {
    const taskId = row.dataset.task || '';
    const status = row.dataset.status || '';
    const language = getTaskLanguage(taskId, TASK_LANGUAGE);
    
    let visible = true;
    
    if (filters.search && !taskId.toLowerCase().includes(filters.search)) {
      visible = false;
    }
    
    if (filters.status && status !== filters.status) {
      visible = false;
    }
    
    if (filters.language && language !== filters.language) {
      visible = false;
    }
    
    row.hidden = !visible;
  });
}

// ============================================================================
// UI Helper Functions
// ============================================================================

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
  resultsFilter?.element && (resultsFilter.element.hidden = true);
}

function hideResultsPlaceholder() {
  if (!resultsCard) return;
  resultsCard.classList.remove('results-empty');
  resultsCard.hidden = false;
  resultsFilter?.element && (resultsFilter.element.hidden = false);
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
  progressBar?.hide();
  resultsFilter?.element && (resultsFilter.element.hidden = true);
  allResultsData = [];
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

function formatThinkingLevel(level) {
  if (!level || level === 'base') return '—';
  if (level.startsWith('unsupported')) {
    return level.replace('unsupported', 'Unsupported').replace(/\((.+)\)/, (_, inner) => inner ? ` (${inner})` : '');
  }
  return level.replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatRunId(runId) {
  if (!runId) return 'View';
  const baseId = String(runId).split('/').pop();
  if (!baseId) return 'View Run';
  if (baseId.length <= 12) return baseId;
  return `${baseId.slice(0, 6)}…${baseId.slice(-4)}`;
}

function buildRunDetailHref(runId) {
  if (!runId) return '/ui/run.html';
  return `/ui/run.html?run_id=${encodeURIComponent(runId)}`;
}

function getInputArray(selector) {
  return runForm?.querySelector(selector)?.value.split(',').map((value) => value.trim()).filter(Boolean) || [];
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

// ============================================================================
// Run Management
// ============================================================================

async function startRun(event) {
  event.preventDefault();
  const models = getInputArray('#model-input');
  if (models.length === 0) {
    renderStatus('Provide at least one model ID', 'error');
    showToast('Please provide at least one model ID', 'error');
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
    if (!Number.isNaN(value)) payload.temperature = value;
  }
  if (maxTokensInput) {
    const value = parseInt(maxTokensInput.value, 10);
    if (!Number.isNaN(value) && value > 0) payload.max_tokens = value;
  }
  
  const providerValue = providerInput?.value.trim();
  if (providerValue) payload.provider = providerValue;
  
  const thinkingValue = thinkingLevelInput?.value.trim();
  if (thinkingValue) payload.thinking_level = thinkingValue;
  
  if (includeThinkingVariantsInput) payload.include_thinking_variants = includeThinkingVariantsInput.checked;
  if (sweepThinkingLevelsInput) payload.sweep_thinking_levels = !!sweepThinkingLevelsInput.checked;
  
  if (responseTextInput) {
    const responseText = responseTextInput.value.trim();
    if (responseText) payload.response_text = responseText;
  }
  
  if (allowIncompleteDiffsInput) payload.allow_incomplete_diffs = allowIncompleteDiffsInput.checked;
  if (allowDiffRewriteInput) payload.allow_diff_rewrite_fallback = allowDiffRewriteInput.checked;
  if (tasks.length) payload.tasks = tasks;

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
    showToast(`Run ${formatRunId(data.run_id)} started`, 'success');
    setLatestRunId(data.run_id);
    showResultsPlaceholder('Waiting for live attempt updates…', data.run_id);
    listenToRun(data.run_id);
  } catch (error) {
    console.error(error);
    renderStatus(`Run failed to launch: ${error.message}`, 'error');
    showToast(`Failed to launch run: ${error.message}`, 'error');
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
    totalTasks: 0,
    completedTasks: 0,
  };

  socket.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      console.error('Failed to parse WebSocket message', e);
      return;
    }
    
    switch (data.type) {
      case 'init':
        setupRunView(data.metadata, runId);
        break;
      case 'attempt':
        updateAttemptRow(data);
        currentRun.completedTasks++;
        progressBar?.update(currentRun.completedTasks, currentRun.totalTasks);
        break;
      case 'complete':
        currentRun.completed = true;
        renderRun(data.summary);
        renderStatus(`Run ${runId} complete!`, 'success');
        showToast(`Run ${formatRunId(runId)} completed!`, 'success');
        runButton.disabled = false;
        progressBar?.hide();
        refreshLeaderboard();
        refreshHistory();
        break;
      case 'error':
        currentRun.completed = true;
        renderStatus(`Run ${runId} failed: ${data.message}`, 'error');
        showToast(`Run failed: ${data.message}`, 'error');
        runButton.disabled = false;
        progressBar?.hide();
        refreshHistory();
        if (!currentRun.rows.size) {
          showResultsPlaceholder('Run halted before attempts could start.', runId);
        }
        break;
    }
  };

  socket.onerror = (event) => {
    console.error('WebSocket error', event);
    renderStatus('Live updates interrupted', 'error');
    showToast('Live updates interrupted', 'warning');
  };

  socket.onclose = () => {
    if (!currentRun?.completed) {
      renderStatus('Connection closed before completion', 'error');
      runButton.disabled = false;
      progressBar?.hide();
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
  currentRun.totalTasks = tasks.length * (metadata.samples || 1);
  currentRun.completedTasks = 0;
  
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
  allResultsData = [];
  
  // Show and reset progress bar
  progressBar?.show();
  progressBar?.reset();
  progressBar?.update(0, currentRun.totalTasks);
}

function updateAttemptRow(event) {
  const { task_id: taskId, status, duration_seconds: duration, prompt_tokens: prompt, completion_tokens: completion, cost_usd: cost, error } = event;
  const levelKey = event.thinking_level_applied || event.thinking_level_requested || 'base';
  const rowKey = `${taskId}::${levelKey}`;
  const language = getTaskLanguage(taskId, TASK_LANGUAGE);
  
  // Store for export
  allResultsData.push(event);
  
  let row = currentRun.rows.get(rowKey);
  if (!row) {
    row = document.createElement('tr');
    row.classList.add('fade-in');
    row.dataset.task = taskId;
    row.dataset.level = levelKey;
    row.dataset.levelOrder = String(levelOrder(levelKey));
    row.dataset.status = status?.toLowerCase() || '';
    row.dataset.language = language;
    
    const levelLabel = formatThinkingLevel(levelKey);
    row.innerHTML = `
      <td>${renderTaskName(taskId, TASK_LANGUAGE)}</td>
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
  row.dataset.status = status?.toLowerCase() || '';
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
  allResultsData = summary.attempts || [];
  
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
    const language = getTaskLanguage(attempt.task_id, TASK_LANGUAGE);
    
    const row = document.createElement('tr');
    row.classList.add('fade-in');
    row.style.animationDelay = `${index * 30}ms`;
    row.dataset.task = attempt.task_id;
    row.dataset.status = attempt.status?.toLowerCase() || '';
    row.dataset.language = language;
    
    row.innerHTML = `
      <td>${renderTaskName(attempt.task_id, TASK_LANGUAGE)}</td>
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
  
  // Show filter bar
  resultsFilter?.element && (resultsFilter.element.hidden = false);
}

function renderStatus(message, level) {
  if (!runStatus) return;
  runStatus.textContent = message;
  runStatus.className = `status ${level}`;
  runStatus.classList.remove('pop');
  requestAnimationFrame(() => runStatus.classList.add('pop'));
}

// ============================================================================
// Leaderboard
// ============================================================================

async function refreshLeaderboard() {
  if (!leaderboardBody) return;
  showTableSkeleton(leaderboardBody, 5, 7);
  
  try {
    const response = await fetch('/leaderboard');
    if (!response.ok) throw new Error(response.statusText);
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
          <button type="button" class="ghost copy-model" data-action="copy-model" data-model="${model.model_id}" aria-label="Copy model ID">Copy ID</button>
          <button type="button" class="ghost danger" data-action="delete-model" data-model="${model.model_id}" data-level="${rawLevel}" aria-label="Delete model runs">Delete</button>
        </td>
      `;
      leaderboardBody.appendChild(row);
    });
  } catch (error) {
    console.error('Failed to refresh leaderboard:', error);
    leaderboardBody.innerHTML = '<tr><td colspan="7" class="empty-state">Failed to load leaderboard</td></tr>';
  }
}

leaderboardBody?.addEventListener('click', async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  
  if (target.dataset.action === 'copy-model') {
    const modelId = target.dataset.model;
    if (!modelId) return;
    try {
      await navigator.clipboard.writeText(modelId);
      showToast(`Copied "${modelId}" to clipboard`, 'success', 2000);
    } catch (error) {
      console.error(error);
      showToast('Failed to copy model id', 'error');
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
      const response = await fetch(`/leaderboard/${encodeURIComponent(modelId)}${query}`, { method: 'DELETE' });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || response.statusText || 'Failed');
      }
      showToast(`Deleted runs for ${modelId}`, 'success');
      await refreshLeaderboard();
      await refreshHistory();
    } catch (error) {
      console.error(error);
      showToast(`Failed to delete runs: ${error.message}`, 'error');
      target.disabled = false;
    }
  }
});

// ============================================================================
// Model Capabilities
// ============================================================================

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

// ============================================================================
// History
// ============================================================================

async function refreshHistory() {
  if (!historyBody) return;
  showTableSkeleton(historyBody, 5, 6);
  
  try {
    const response = await fetch('/runs?limit=200');
    if (!response.ok) throw new Error(response.statusText);
    const data = await response.json();
    allHistoryData = data.runs || [];
    
    historyPagination?.update(allHistoryData.length, 1);
    renderHistoryPage(1, 0);
  } catch (error) {
    console.error('Failed to refresh history:', error);
    historyBody.innerHTML = '<tr><td colspan="6" class="empty-state">Failed to load history</td></tr>';
  }
}

function renderHistoryPage(page, offset) {
  if (!historyBody) return;
  historyBody.innerHTML = '';
  
  const pageSize = historyPagination?.pageSize || 20;
  const pageData = allHistoryData.slice(offset, offset + pageSize);
  
  if (!pageData.length) {
    historyBody.innerHTML = '<tr><td colspan="6" class="empty-state">No runs yet</td></tr>';
    return;
  }
  
  pageData.forEach((run, index) => {
    const row = document.createElement('tr');
    row.classList.add('fade-in');
    row.style.animationDelay = `${index * 30}ms`;
    const accuracy = (run.accuracy ?? 0) * 100;
    const displayRunId = formatRunId(run.run_id);
    const runHref = buildRunDetailHref(run.run_id);
    
    row.innerHTML = `
      <td class="breakable"><a href="${runHref}" target="_blank" rel="noopener noreferrer" title="Open run ${run.run_id}">${displayRunId}</a></td>
      <td>${run.timestamp_utc || '-'}</td>
      <td class="breakable">${run.model_id || '-'}</td>
      <td>${accuracy.toFixed(2)}%</td>
      <td>$${(run.total_cost_usd ?? 0).toFixed(6)}</td>
      <td>${run.total_duration_seconds != null ? run.total_duration_seconds.toFixed(2) : '-'}</td>
    `;
    historyBody.appendChild(row);
  });
}
