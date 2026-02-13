import {
  showToast,
  mapStatus,
  applyStatus,
  createProgressBar,
  makeSortable,
  createFilterBar,
  createPagination,
  exportToCSV,
  exportToJSON,
  showTableSkeleton,
  registerShortcut,
  formatNumber,
  formatCost,
  formatPercent,
  formatTimestamp
} from '../components.js?v=20260110_6';

const DEBUG = new URLSearchParams(window.location.search).has('debug');
const debugLog = (...args) => {
  if (DEBUG) console.log(...args);
};

// ============================================================================
// DOM Elements
// ============================================================================

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
const progressContainer = document.querySelector('#qa-progress-container');
const filterContainer = document.querySelector('#qa-filter-container');
const historyPaginationContainer = document.querySelector('#qa-history-pagination');
const leaderboardFilterContainer = document.querySelector('#qa-leaderboard-filter-container');
const resultsTable = document.querySelector('#qa-results-table');
const historyTable = document.querySelector('#qa-history-table');
const leaderboardTable = document.querySelector('.leaderboard-card table');

const temperatureInput = document.querySelector('#qa-temperature-input');
const maxTokensInput = document.querySelector('#qa-max-tokens-input');
const sampleInput = document.querySelector('#qa-sample-input');
const modelInput = document.querySelector('#qa-model-input');
const providerInput = document.querySelector('#qa-provider-input');
const modelSourceSelect = document.querySelector('#qa-model-source-select');
const sweepThinkingLevelsInput = document.querySelector('#qa-sweep-thinking-levels');
const includeThinkingVariantsInput = document.querySelector('#qa-include-thinking-variants');
const modelCapabilitiesNote = document.querySelector('#qa-model-capabilities');

const exportCsvBtn = document.querySelector('#qa-export-csv-btn');
const exportJsonBtn = document.querySelector('#qa-export-json-btn');
const exportHistoryCsvBtn = document.querySelector('#qa-export-history-csv');
const qaApiErrorSection = document.querySelector('#qa-api-error-section');
const qaApiErrorCount = document.querySelector('#qa-api-error-count');
const qaRetryApiErrorsBtn = document.querySelector('#qa-retry-api-errors-btn');

// ============================================================================
// State
// ============================================================================

let currentSocket = null;
let currentRun = null;
let progressBar = null;
let resultsFilter = null;
let leaderboardFilter = null;
let historyPagination = null;
let allHistoryData = [];
let allResultsData = [];
let allLeaderboardData = [];

// ============================================================================
// Initialization
// ============================================================================

runForm?.addEventListener('submit', startRun);
runButton?.addEventListener('click', (event) => {
  if (runButton?.type === 'submit') return;
  startRun(event);
});
backButton?.addEventListener('click', () => {
  window.location.href = '/ui/index.html';
});

refreshLeaderboard();
refreshHistory();
resetResultsLayout();

// Initialize progress bar
if (progressContainer) {
  progressBar = createProgressBar(progressContainer);
  progressBar.hide();
}

// Initialize results filter
if (filterContainer) {
  resultsFilter = createFilterBar(filterContainer, {
    searchPlaceholder: 'Search questions...',
    showLanguageFilter: false
  });
  resultsFilter.onFilter(applyResultsFilter);
  resultsFilter.element.hidden = true;
}

// Initialize leaderboard filter (search only)
if (leaderboardFilterContainer) {
  leaderboardFilter = createFilterBar(leaderboardFilterContainer, {
    searchPlaceholder: 'Search models...',
    showStatusFilter: false,
    showLanguageFilter: false
  });
  leaderboardFilter.onFilter(applyLeaderboardFilter);
}

// Initialize history pagination
if (historyPaginationContainer) {
  historyPagination = createPagination(historyPaginationContainer, { pageSize: 20 });
  historyPagination.onPageChange(renderHistoryPage);
}

// Make tables sortable
if (resultsTable) makeSortable(resultsTable);
// historyTable uses custom sorting that works with pagination (see setupHistorySorting)
if (leaderboardTable) makeSortable(leaderboardTable);

// Setup history table sorting that works with pagination
let historySortColumn = 1; // Default: sort by timestamp (column 1)
let historySortDirection = 'desc'; // Default: newest first

function setupHistorySorting() {
  if (!historyTable) {
    console.warn('History table not found for sorting setup');
    return;
  }

  const headers = historyTable.querySelectorAll('thead th');
  if (!headers.length) {
    console.warn('No headers found in history table');
    return;
  }

  headers.forEach((header, index) => {
    if (header.classList.contains('no-sort') || header.classList.contains('actions-header')) return;

    header.classList.add('sortable');
    header.style.cursor = 'pointer';

    // Only add sort icon if not already present
    if (!header.querySelector('.sort-icon')) {
      const sortIcon = document.createElement('span');
      sortIcon.className = 'sort-icon';
      sortIcon.textContent = ' ⇅';
      header.appendChild(sortIcon);
    }

    header.addEventListener('click', () => {
      // Toggle direction if same column, otherwise default to desc for new column
      if (historySortColumn === index) {
        historySortDirection = historySortDirection === 'asc' ? 'desc' : 'asc';
      } else {
        historySortColumn = index;
        historySortDirection = 'desc';
      }

      // Update header styles - mark active column
      headers.forEach(h => {
        const icon = h.querySelector('.sort-icon');
        if (icon) {
          icon.classList.remove('asc', 'desc');
          icon.textContent = ' ⇅';
        }
      });
      const activeIcon = header.querySelector('.sort-icon');
      if (activeIcon) {
        activeIcon.classList.add(historySortDirection);
        activeIcon.textContent = historySortDirection === 'asc' ? ' ↑' : ' ↓';
      }

      // Sort the data
      sortHistoryData(index, historySortDirection);

      // Re-render from page 1
      if (historyPagination) {
        historyPagination.update(historyData.length, 1);
      }
      renderHistoryPage(1, 0);
    });
  });

  debugLog('History table sorting initialized with', headers.length, 'columns');
}

function sortHistoryData(columnIndex, direction) {
  // Map column index to data field name
  const sortKeys = ['run_id', 'timestamp_utc', 'model_id', 'accuracy', 'total_cost_usd', 'total_duration_seconds', 'error_count'];
  const key = sortKeys[columnIndex];

  if (!key) {
    console.warn('No sort key for column index:', columnIndex);
    return;
  }

  if (!historyData || !historyData.length) {
    console.warn('No history data to sort');
    return;
  }

  debugLog('Sorting history by', key, direction);

  historyData.sort((a, b) => {
    let aVal = a[key];
    let bVal = b[key];

    // Handle null/undefined - put them at the end
    if (aVal == null && bVal == null) return 0;
    if (aVal == null) return 1;
    if (bVal == null) return -1;

    // Numeric comparison for numbers
    if (typeof aVal === 'number' && typeof bVal === 'number') {
      return direction === 'asc' ? aVal - bVal : bVal - aVal;
    }

    // String comparison (works for ISO timestamps too)
    aVal = String(aVal);
    bVal = String(bVal);

    if (direction === 'asc') {
      return aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
    } else {
      return aVal > bVal ? -1 : aVal < bVal ? 1 : 0;
    }
  });
}

// Initialize sorting after DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupHistorySorting);
} else {
  setupHistorySorting();
}

// Export buttons
exportCsvBtn?.addEventListener('click', () => {
  if (allResultsData.length) {
    const data = allResultsData.map(a => ({
      question_number: a.question_number,
      model: a.model,
      thinking_level: a.thinking_level_applied || a.thinking_level_requested || 'base',
      status: a.status,
      duration_seconds: a.duration_seconds,
      model_answer: a.model_answer,
      expected_answer: a.expected_answer,
      judge_decision: a.judge_decision || '',
      error: a.error || ''
    }));
    exportToCSV(data, `qa_run_${currentRun?.runId || 'results'}.csv`);
  }
});

exportJsonBtn?.addEventListener('click', () => {
  if (allResultsData.length) {
    exportToJSON(allResultsData, `qa_run_${currentRun?.runId || 'results'}.json`);
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
    exportToCSV(data, 'qa_history.csv');
  }
});

// Model capability check debounce
let capabilityTimer = null;
modelInput?.addEventListener('input', () => {
  if (capabilityTimer) clearTimeout(capabilityTimer);
  capabilityTimer = setTimeout(checkModelCapabilities, 600);
});

modelSourceSelect?.addEventListener('change', () => {
  if (capabilityTimer) clearTimeout(capabilityTimer);
  capabilityTimer = setTimeout(checkModelCapabilities, 0);
});

// Retry API errors button
qaRetryApiErrorsBtn?.addEventListener('click', retryQaApiErrors);

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

registerShortcut('r', () => {
  modelInput?.focus();
}, 'Focus model input');

registerShortcut('l', () => {
  document.querySelector('.leaderboard-card')?.scrollIntoView({ behavior: 'smooth' });
}, 'Scroll to leaderboard');

registerShortcut('h', () => {
  document.querySelector('.recent-card')?.scrollIntoView({ behavior: 'smooth' });
}, 'Scroll to history');

registerShortcut('c', () => {
  window.location.href = '/ui/index.html';
}, 'Go to Code Tasks');

// ============================================================================
// Results Filtering
// ============================================================================

function applyResultsFilter(filters) {
  const rows = resultsBody?.querySelectorAll('tr') || [];
  rows.forEach(row => {
    const questionNum = row.dataset.question || '';
    const status = row.dataset.status || '';

    let visible = true;

    if (filters.search && !questionNum.includes(filters.search)) {
      visible = false;
    }

    if (filters.status && status !== filters.status) {
      visible = false;
    }

    row.hidden = !visible;
  });
}

// ============================================================================
// Leaderboard Filtering
// ============================================================================

function applyLeaderboardFilter(filters) {
  const rows = leaderboardBody?.querySelectorAll('tr') || [];
  rows.forEach(row => {
    const modelId = row.dataset.model || row.cells[0]?.textContent || '';

    let visible = true;

    if (filters.search && !modelId.toLowerCase().includes(filters.search)) {
      visible = false;
    }

    row.hidden = !visible;
  });
}

// ============================================================================
// UI Helper Functions
// ============================================================================

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
  progressBar?.hide();
  resultsFilter?.element && (resultsFilter.element.hidden = true);
  allResultsData = [];
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

function renderStatus(message, level = 'info') {
  if (!runStatus) return;
  runStatus.textContent = message;
  runStatus.className = `status ${level}`;
  runStatus.classList.remove('pop');
  requestAnimationFrame(() => runStatus.classList.add('pop'));
}

function getInputArray(selector) {
  const element = document.querySelector(selector);
  if (!element) return [];
  return element.value.split(',').map((value) => value.trim()).filter(Boolean);
}

function abortCurrentSocket() {
  if (currentSocket) {
    currentSocket.close();
    currentSocket = null;
    currentRun = null;
  }
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

// ============================================================================
// Run Management
// ============================================================================

async function startRun(event) {
  event?.preventDefault?.();
  const models = getInputArray('#qa-model-input');
  if (!models.length) {
    renderStatus('Provide at least one model ID', 'error');
    showToast('Please provide at least one model ID', 'error');
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
  if (providerValue) payload.provider = providerValue;
  if (sweepThinkingLevelsInput?.checked) payload.sweep_thinking_levels = true;
  if (includeThinkingVariantsInput?.checked) payload.include_thinking_variants = true;

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
    showToast(`Run ${data.run_id} started`, 'success');
    setLatestRunId(data.run_id);
    showResultsPlaceholder('Waiting for question answers…', data.run_id);
    listenToRun(data.run_id);
  } catch (error) {
    renderStatus(`Failed to launch run: ${error.message}`, 'error');
    showToast(`Failed to launch run: ${error.message}`, 'error');
    runButton.disabled = false;
    resetResultsLayout();
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
    totalQuestions: 0,
    completedQuestions: 0,
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
        currentRun.completedQuestions++;
        progressBar?.update(currentRun.completedQuestions, currentRun.totalQuestions);
        break;
      case 'complete':
        currentRun.completed = true;
        renderRun(data.summary);
        renderStatus(`Run ${runId} complete!`, 'success');
        showToast(`Run ${runId} completed!`, 'success');
        runButton.disabled = false;
        progressBar?.hide();
        refreshLeaderboard();
        refreshHistory();
        loadQaApiErrorInfo(runId);
        break;
      case 'error':
        currentRun.completed = true;
        renderStatus(`Run ${runId} failed: ${data.message}`, 'error');
        showToast(`Run failed: ${data.message}`, 'error');
        runButton.disabled = false;
        progressBar?.hide();
        if (!currentRun.rows.size) {
          showResultsPlaceholder('Run halted before answers were recorded.', runId);
        }
        refreshHistory();
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

  currentRun.totalQuestions = questionCount * samples * models.length;
  currentRun.completedQuestions = 0;

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
  allResultsData = [];

  // Show and reset progress bar
  progressBar?.show();
  progressBar?.reset();
  progressBar?.update(0, currentRun.totalQuestions);
}

function updateAttemptRow(event) {
  const levelKey = (event.thinking_level_applied || event.thinking_level_requested || 'base');
  const key = `${event.model || 'unknown'}::${event.question_number}::${event.sample_index ?? 0}::${levelKey}`;

  // Store for export
  allResultsData.push(event);

  let row = currentRun.rows.get(key);
  if (!row) {
    row = document.createElement('tr');
    row.classList.add('fade-in');
    row.dataset.question = String(event.question_number || '');
    row.dataset.status = event.status?.toLowerCase() || '';
    row.dataset.model = event.model || '';
    row.dataset.sampleIndex = event.sample_index ?? 0;

    const levelLabel = levelKey && levelKey !== 'base' ? levelKey : '—';
    const cellData = [
      { text: event.question_number ?? '—' },
      { text: event.model || '—' },
      { text: levelLabel },
      { text: '', className: 'status-cell' },
      { text: '-' },
      { text: '-' },
      { text: '-' },
      { text: '-' },
      { text: '', className: 'breakable' },
      { text: '', className: 'breakable' },
      { text: '' },
      { text: '', className: 'actions-cell' },  // Actions column
    ];
    cellData.forEach((cell) => {
      const td = document.createElement('td');
      td.textContent = cell.text;
      if (cell.className) td.className = cell.className;
      row.appendChild(td);
    });

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
  row.dataset.status = event.status?.toLowerCase() || '';
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
  // Truncate long model answers for display, show full text on hover/click
  const maxLen = 60;
  const displayModelAns = modelAns.length > maxLen ? modelAns.substring(0, maxLen) + '...' : modelAns;
  // Clear any existing content and create a wrapper span for truncation
  cells[8].innerHTML = '';
  const answerSpan = document.createElement('span');
  answerSpan.textContent = displayModelAns;
  answerSpan.style.cssText = 'display:block;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
  if (modelAns.length > maxLen) {
    answerSpan.style.cursor = 'pointer';
    answerSpan.title = 'Click to copy full answer';
    answerSpan.onclick = (e) => {
      e.stopPropagation();
      navigator.clipboard.writeText(modelAns).then(() => {
        answerSpan.textContent = 'Copied!';
        setTimeout(() => { answerSpan.textContent = displayModelAns; }, 1000);
      }).catch(() => {
        prompt('Full answer:', modelAns);
      });
    };
  }
  cells[8].appendChild(answerSpan);
  cells[9].textContent = expectedAns;

  const judgeInfo = event.judge_decision
    ? `Judge: ${event.judge_decision}${event.judge_rationale ? ` – ${event.judge_rationale}` : ''}`
    : '';
  const judgeError = event.judge_error ? `Judge error: ${event.judge_error}` : '';
  const errorMessage = event.error || '';
  const combinedError = [errorMessage, judgeInfo, judgeError].filter(Boolean).join(' | ');
  cells[10].textContent = combinedError;
  cells[10].className = combinedError ? 'error-cell' : '';
  if (combinedError) {
    cells[10].title = combinedError;
  }

  // Update Actions column with retry button for any failed status
  const statusLower = event.status?.toLowerCase() || '';
  const canRetry = ['error', 'fail', 'failed', 'api_error', 'exception'].includes(statusLower);
  if (cells[11]) {
    if (canRetry && !cells[11].querySelector('.retry-single-btn')) {
      const retryBtn = document.createElement('button');
      retryBtn.className = 'ghost retry-single-btn';
      retryBtn.title = 'Retry this attempt';
      retryBtn.textContent = 'Retry';
      retryBtn.addEventListener('click', () => {
        retryQaSingleAttempt(event.question_number, event.model, event.sample_index);
      });
      cells[11].innerHTML = '';
      cells[11].appendChild(retryBtn);
    } else if (!canRetry) {
      cells[11].innerHTML = '';
    }
  }
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
  // Clear before re-rendering - updateAttemptRow will repopulate
  allResultsData = [];

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

  // Show filter bar
  resultsFilter?.element && (resultsFilter.element.hidden = false);
}

// ============================================================================
// Model Capabilities
// ============================================================================

async function checkModelCapabilities() {
  if (modelSourceSelect?.value === 'lmstudio') {
    if (modelCapabilitiesNote) modelCapabilitiesNote.textContent = '';
    return;
  }
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

// ============================================================================
// Leaderboard
// ============================================================================

async function refreshLeaderboard() {
  if (!leaderboardBody) return;
  showTableSkeleton(leaderboardBody, 5, 7);
  renderLeaderboardStatus('Loading…', 'info');

  try {
    const response = await fetch('/qa/leaderboard');
    if (!response.ok) throw new Error(response.statusText);
    const data = await response.json();
    const rows = Array.isArray(data.models) ? data.models : [];

    if (!rows.length) {
      renderLeaderboardStatus('No question runs yet.', 'info');
      leaderboardBody.innerHTML = '';
      return;
    }

    renderLeaderboardStatus('', 'info');
    leaderboardBody.innerHTML = '';
    allLeaderboardData = rows;

    rows.forEach((row) => {
      const tr = document.createElement('tr');
      tr.dataset.model = row.model_id;
      const levelLabel = row.thinking_level && row.thinking_level !== 'base' ? row.thinking_level : '—';
      const cellValues = [
        row.model_id,
        row.accuracy != null ? `${(row.accuracy * 100).toFixed(2)}%` : '—',
        row.cost_usd != null ? `$${Number(row.cost_usd).toFixed(6)}` : '—',
        row.duration_seconds != null ? Number(row.duration_seconds).toFixed(2) : '—',
        row.runs ?? '—',
        levelLabel,
      ];
      cellValues.forEach((text) => {
        const td = document.createElement('td');
        td.textContent = text;
        tr.appendChild(td);
      });
      const btnCell = document.createElement('td');
      btnCell.className = 'actions-cell';
      const btn = document.createElement('button');
      btn.className = 'ghost danger';
      btn.dataset.model = row.model_id;
      btn.textContent = 'Clear';
      btn.setAttribute('aria-label', `Clear runs for ${row.model_id}`);
      btnCell.appendChild(btn);
      tr.appendChild(btnCell);
      leaderboardBody.appendChild(tr);
    });
  } catch (error) {
    renderLeaderboardStatus(`Failed to load leaderboard: ${error.message}`, 'error');
    leaderboardBody.innerHTML = '';
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
    const response = await fetch(`/qa/leaderboard/${encodeURIComponent(modelId)}`, { method: 'DELETE' });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    showToast(`Cleared runs for ${modelId}`, 'success');
    refreshLeaderboard();
    refreshHistory();
  } catch (error) {
    showToast(`Failed to delete: ${error.message}`, 'error');
    target.disabled = false;
  }
});

// ============================================================================
// History
// ============================================================================

async function refreshHistory() {
  if (!historyBody) return;
  showTableSkeleton(historyBody, 5, 6);

  try {
    const response = await fetch('/qa/runs?limit=200');
    if (!response.ok) throw new Error(response.statusText);
    const data = await response.json();
    allHistoryData = Array.isArray(data.runs) ? data.runs : [];

    historyPagination?.update(allHistoryData.length, 1);
    renderHistoryPage(1, 0);
  } catch (error) {
    historyBody.innerHTML = `<tr><td colspan="7" class="empty-state">Failed to load history: ${error.message}</td></tr>`;
  }
}

function renderHistoryPage(page, offset) {
  if (!historyBody) return;
  historyBody.innerHTML = '';

  const pageSize = historyPagination?.pageSize || 20;
  const pageData = allHistoryData.slice(offset, offset + pageSize);

  if (!pageData.length) {
    historyBody.innerHTML = '<tr><td colspan="7" class="empty-state">No question runs yet.</td></tr>';
    return;
  }

  pageData.forEach((row) => {
    const tr = document.createElement('tr');
    tr.classList.add('clickable-row');
    tr.dataset.runId = row.run_id;
    const errorCount = row.error_count ?? 0;

    // First cell is a link
    const runIdTd = document.createElement('td');
    runIdTd.className = 'breakable';
    const runIdLink = document.createElement('a');
    runIdLink.href = '#';
    runIdLink.textContent = row.run_id;
    runIdLink.title = `Load run ${row.run_id}`;
    runIdLink.addEventListener('click', (e) => {
      e.preventDefault();
      loadQaRunDetails(row.run_id);
    });
    runIdTd.appendChild(runIdLink);
    tr.appendChild(runIdTd);

    // Timestamp cell with sort value
    const timestampTd = document.createElement('td');
    timestampTd.textContent = formatTimestamp(row.timestamp_utc);
    timestampTd.dataset.sortValue = row.timestamp_utc || '';
    tr.appendChild(timestampTd);

    // Rest of the cells
    const cells = [
      { text: row.model_id || '—', className: '' },
      { text: row.accuracy != null ? `${(row.accuracy * 100).toFixed(2)}%` : '—', className: '' },
      { text: row.total_cost_usd != null ? `$${Number(row.total_cost_usd).toFixed(6)}` : '—', className: '' },
      { text: row.total_duration_seconds != null ? Number(row.total_duration_seconds).toFixed(2) : '—', className: '' },
      { text: errorCount > 0 ? `${errorCount} error(s)` : '—', className: errorCount > 0 ? 'status-fail' : '' },
    ];
    cells.forEach((cell) => {
      const td = document.createElement('td');
      td.textContent = cell.text;
      if (cell.className) td.className = cell.className;
      tr.appendChild(td);
    });

    // Make row clickable to load run details
    tr.addEventListener('click', (e) => {
      if (e.target.tagName !== 'A') {
        loadQaRunDetails(row.run_id);
      }
    });

    historyBody.appendChild(tr);
  });
}

async function loadQaRunDetails(runId) {
  showResultsPlaceholder('Loading run details…', runId);

  try {
    const response = await fetch(`/qa/runs/${encodeURIComponent(runId)}`);
    if (!response.ok) {
      showToast(`Failed to load run: ${response.statusText}`, 'error');
      return;
    }

    const data = await response.json();
    const summary = data.summary;

    // Reset state and render the run
    currentRun = {
      runId,
      rows: new Map(),
      completed: true,
      totalQuestions: 0,
      completedQuestions: 0,
    };

    renderRun(summary);
    showToast('Run details loaded', 'success', 2000);

    // Check for API errors
    loadQaApiErrorInfo(runId);

  } catch (error) {
    console.error('Failed to load QA run details:', error);
    showToast(`Failed to load run: ${error.message}`, 'error');
  }
}

// ============================================================================
// API Error Retry
// ============================================================================

async function loadQaApiErrorInfo(runId) {
  if (!runId || !qaApiErrorSection) return;

  try {
    const response = await fetch(`/qa/runs/${encodeURIComponent(runId)}/api-errors`);
    if (!response.ok) {
      qaApiErrorSection.hidden = true;
      return;
    }

    const data = await response.json();
    if (data.api_error_count > 0) {
      qaApiErrorSection.hidden = false;
      qaApiErrorCount.textContent = `${data.api_error_count} API error(s) detected (rate limits, empty responses, etc.)`;
      qaApiErrorSection.dataset.runId = runId;
    } else {
      qaApiErrorSection.hidden = true;
    }
  } catch (error) {
    console.warn('Failed to load QA API error info:', error);
    qaApiErrorSection.hidden = true;
  }
}

async function retryQaApiErrors() {
  const runId = qaApiErrorSection?.dataset.runId;
  if (!runId) {
    showToast('No run selected for retry', 'error');
    return;
  }

  qaRetryApiErrorsBtn.disabled = true;
  qaRetryApiErrorsBtn.textContent = 'Retrying...';

  try {
    const response = await fetch(`/qa/runs/${encodeURIComponent(runId)}/retry-api-errors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Failed to start retry');
    }

    const data = await response.json();

    if (data.api_errors_found === 0) {
      showToast('No API errors to retry', 'info');
      qaRetryApiErrorsBtn.textContent = 'No API Errors';
      return;
    }

    showToast(`Retrying ${data.api_errors_found} API errors...`, 'success');

    // Store original run ID and listen to retry progress
    const originalRunId = data.original_run_id || runId;
    const retryRunId = data.retry_run_id;

    qaApiErrorSection.hidden = true;
    showResultsPlaceholder('Retrying failed API calls…', retryRunId);

    // Create a WebSocket to track retry progress
    const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${wsProtocol}//${location.host}/qa/runs/${retryRunId}/stream`);

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'complete') {
        ws.close();
        showToast('Retry complete! Reloading results...', 'success');
        // Reload the original run to see updated results
        setTimeout(() => loadQaRunDetails(originalRunId), 500);
      } else if (msg.type === 'error') {
        ws.close();
        showToast(`Retry error: ${msg.error}`, 'error');
        qaRetryApiErrorsBtn.disabled = false;
        qaRetryApiErrorsBtn.textContent = 'Retry API Errors';
      }
    };

    ws.onerror = () => {
      showToast('Connection error during retry', 'error');
      qaRetryApiErrorsBtn.disabled = false;
      qaRetryApiErrorsBtn.textContent = 'Retry API Errors';
    };

  } catch (error) {
    console.error('QA Retry failed:', error);
    showToast(`Retry failed: ${error.message}`, 'error');
    qaRetryApiErrorsBtn.disabled = false;
    qaRetryApiErrorsBtn.textContent = 'Retry API Errors';
  }
}

async function retryQaSingleAttempt(questionNumber, model, sampleIndex) {
  const runId = qaApiErrorSection?.dataset.runId || currentRun?.runId;
  if (!runId || questionNumber == null) {
    showToast('No run or question selected for retry', 'error');
    return;
  }

  // Find and disable the button
  const rows = resultsBody?.querySelectorAll('tr') || [];
  let targetBtn = null;
  rows.forEach(row => {
    if (row.dataset.question === String(questionNumber) &&
        row.dataset.model === model &&
        row.dataset.sampleIndex == sampleIndex) {
      targetBtn = row.querySelector('.retry-single-btn');
    }
  });

  if (targetBtn) {
    targetBtn.disabled = true;
    targetBtn.textContent = 'Retrying...';
  }

  try {
    const response = await fetch(`/qa/runs/${encodeURIComponent(runId)}/retry-single`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question_number: questionNumber,
        model: model || null,
        sample_index: sampleIndex ?? null,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Failed to start retry');
    }

    const data = await response.json();

    if (data.api_errors_found === 0) {
      showToast('No matching API error to retry', 'info');
      if (targetBtn) {
        targetBtn.textContent = 'No Error';
      }
      return;
    }

    showToast(`Retrying question ${questionNumber}...`, 'success');

    // Store the original run ID to reload after retry completes
    const originalRunId = data.original_run_id || runId;

    // Listen to the retry progress, then reload original run when complete
    const retryRunId = data.retry_run_id;
    showResultsPlaceholder(`Retrying question ${questionNumber}…`, retryRunId);

    // Create a WebSocket to track retry progress
    const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${wsProtocol}//${location.host}/qa/runs/${retryRunId}/stream`);

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'complete') {
        ws.close();
        showToast('Retry complete! Reloading results...', 'success');
        // Reload the original run to see updated results
        setTimeout(() => loadQaRunDetails(originalRunId), 500);
      } else if (msg.type === 'error') {
        ws.close();
        showToast(`Retry error: ${msg.error}`, 'error');
        if (targetBtn) {
          targetBtn.disabled = false;
          targetBtn.textContent = 'Retry';
        }
      }
    };

    ws.onerror = () => {
      showToast('Connection error during retry', 'error');
      if (targetBtn) {
        targetBtn.disabled = false;
        targetBtn.textContent = 'Retry';
      }
    };

  } catch (error) {
    console.error('QA single retry failed:', error);
    showToast(`Retry failed: ${error.message}`, 'error');
    if (targetBtn) {
      targetBtn.disabled = false;
      targetBtn.textContent = 'Retry';
    }
  }
}
