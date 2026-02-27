import { TASK_LANGUAGE } from './task-language.js';
import {
  showToast,
  mapStatus,
  createStatusBadge,
  makeSortable,
  createFilterBar,
  createCopyButton,
  exportToCSV,
  registerShortcut,
  formatNumber,
  formatCost,
  renderTaskName,
  getTaskLanguage,
  LANGUAGE_LABELS
} from './components.js?v=20260110_6';

// ============================================================================
// DOM Elements
// ============================================================================

const params = new URLSearchParams(window.location.search);
const runId = params.get('run_id');
const selectedModelFilter = params.get('model');
const selectedThinkingLevelFilter = params.get('thinking_level');
const DEBUG = params.has('debug');
const debugLog = (...args) => {
  if (DEBUG) console.log(...args);
};

const runTitle = document.querySelector('#run-title');
const runSubtitle = document.querySelector('#run-subtitle');
const runMessage = document.querySelector('#run-message');
const runMetrics = document.querySelector('#run-metrics');
const runMeta = document.querySelector('#run-meta');
const attemptBody = document.querySelector('#attempt-body');
const attemptEmpty = document.querySelector('#attempt-empty');
const detailCard = document.querySelector('#attempt-detail');
const detailTitle = document.querySelector('#detail-title');
const detailDescription = document.querySelector('#detail-description');
const detailMeta = document.querySelector('#detail-meta');
const detailLogs = document.querySelector('#detail-logs');
const attemptsTable = document.querySelector('#attempts-table');
const attemptsFilterContainer = document.querySelector('#attempts-filter-container');
const exportAttemptsCsvBtn = document.querySelector('#export-attempts-csv');
const apiErrorSection = document.querySelector('#api-error-section');
const apiErrorCount = document.querySelector('.api-error-count');
const retryApiErrorsBtn = document.querySelector('#retry-api-errors-btn');

// ============================================================================
// State
// ============================================================================

let attempts = [];
let selectedRow = null;
let attemptsFilter = null;

// ============================================================================
// Initialization
// ============================================================================

if (!runId) {
  setRunMessage('Run ID missing from URL. Append ?run_id=<id>.', 'error');
  runTitle.textContent = 'Unknown run';
} else {
  runTitle.textContent = runId;
  loadRunDetails();
}

// Initialize filter
if (attemptsFilterContainer) {
  attemptsFilter = createFilterBar(attemptsFilterContainer, {
    searchPlaceholder: 'Search tasks...',
    showLanguageFilter: true
  });
  attemptsFilter.onFilter(applyAttemptsFilter);
}

// Make table sortable
if (attemptsTable) makeSortable(attemptsTable);

// Export button
exportAttemptsCsvBtn?.addEventListener('click', () => {
  if (attempts.length) {
    const data = attempts.map(a => ({
      task_id: a.task_id,
      language: getTaskLanguage(a.task_id, TASK_LANGUAGE),
      status: a.status,
      duration_seconds: a.duration_seconds,
      prompt_tokens: extractTokens(a.usage, 'prompt'),
      completion_tokens: extractTokens(a.usage, 'completion'),
      cost_usd: a.cost_usd,
      error: a.error || ''
    }));
    exportToCSV(data, `run_${runId}_attempts.csv`);
  }
});

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

registerShortcut('d', () => {
  window.location.href = '/ui/index.html';
}, 'Go to dashboard');

registerShortcut('j', () => {
  const rows = attemptBody?.querySelectorAll('tr:not([hidden])');
  if (!rows?.length) return;
  const currentIdx = Array.from(rows).findIndex(r => r.classList.contains('selected'));
  const nextIdx = currentIdx < rows.length - 1 ? currentIdx + 1 : 0;
  rows[nextIdx]?.click();
}, 'Next attempt');

registerShortcut('k', () => {
  const rows = attemptBody?.querySelectorAll('tr:not([hidden])');
  if (!rows?.length) return;
  const currentIdx = Array.from(rows).findIndex(r => r.classList.contains('selected'));
  const prevIdx = currentIdx > 0 ? currentIdx - 1 : rows.length - 1;
  rows[prevIdx]?.click();
}, 'Previous attempt');

// ============================================================================
// Filter
// ============================================================================

function applyAttemptsFilter(filters) {
  const rows = attemptBody?.querySelectorAll('tr') || [];
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
// UI Helpers
// ============================================================================

function setRunMessage(message, level = 'info') {
  runMessage.textContent = message;
  runMessage.className = `status ${level}`;
}

function extractTokens(usage, type) {
  if (!usage) return '-';
  if (type === 'prompt') {
    return usage.prompt_tokens ?? usage.input_tokens ?? '-';
  }
  return usage.completion_tokens ?? usage.output_tokens ?? '-';
}

function formatThinkingLevel(level) {
  if (!level || level === 'base') return 'base';
  if (String(level).startsWith('unsupported')) {
    return String(level).replace('unsupported', 'unsupported');
  }
  return String(level);
}

function resolveAttemptThinkingLevel(attempt, defaultLevel) {
  if (attempt?.thinking_level_applied) return String(attempt.thinking_level_applied);
  if (attempt?.thinking_level_supported === false && attempt?.thinking_level_requested) {
    return `unsupported (${attempt.thinking_level_requested})`;
  }
  if (attempt?.thinking_level_requested) return String(attempt.thinking_level_requested);
  if (defaultLevel) return String(defaultLevel);
  return 'base';
}

function buildRunApiPath(id) {
  const segments = encodePathSegments(String(id));
  return `/runs/${segments}`;
}

function buildArtifactUrl(run, path) {
  const runSegments = encodePathSegments(String(run));
  const relativeSegments = encodePathSegments(String(path));
  return `/artifacts/${runSegments}/${relativeSegments}`;
}

function encodePathSegments(path) {
  return path.split('/').filter(Boolean).map((segment) => encodeURIComponent(segment)).join('/');
}

async function fetchText(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) return null;
    const text = await response.text();
    return truncateForDisplay(text);
  } catch (error) {
    console.warn(`Failed to fetch ${url}`, error);
    return null;
  }
}

function truncateForDisplay(text) {
  const limit = 20000;
  if (text.length <= limit) return text || '(empty)';
  return `${text.slice(0, limit)}\n\n… truncated (${text.length - limit} characters omitted)`;
}

// ============================================================================
// Syntax Highlighting for Diffs
// ============================================================================

function highlightDiff(text) {
  const lines = text.split('\n');
  const highlighted = lines.map(line => {
    if (line.startsWith('+++') || line.startsWith('---')) {
      return `<span class="diff-header">${escapeHtml(line)}</span>`;
    }
    if (line.startsWith('@@')) {
      return `<span class="diff-range">${escapeHtml(line)}</span>`;
    }
    if (line.startsWith('+')) {
      return `<span class="diff-add">${escapeHtml(line)}</span>`;
    }
    if (line.startsWith('-')) {
      return `<span class="diff-remove">${escapeHtml(line)}</span>`;
    }
    return escapeHtml(line);
  });
  return highlighted.join('\n');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function escapeAttr(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function addLineNumbers(text) {
  const lines = text.split('\n');
  return lines.map((line, i) => `<span class="line">${line}</span>`).join('\n');
}

// ============================================================================
// Data Loading
// ============================================================================

async function loadRunDetails() {
  setRunMessage('Loading run details…', 'info');
  try {
    const response = await fetch(buildRunApiPath(runId));
    if (!response.ok) {
      setRunMessage(`Unable to load run: ${response.statusText}`, 'error');
      return;
    }
    const data = await response.json();
    const summary = data.summary;
    renderRunSummary(summary);
    renderAttempts(summary);
    setRunMessage('Run ready', 'success');
    showToast('Run details loaded', 'success', 2000);

    // Load API error info
    await loadApiErrorInfo();
  } catch (error) {
    console.error(error);
    setRunMessage(`Failed to load run: ${error.message}`, 'error');
    showToast(`Failed to load run: ${error.message}`, 'error');
  }
}

async function loadApiErrorInfo() {
  try {
    const response = await fetch(`${buildRunApiPath(runId)}/api-errors`);
    if (!response.ok) return;

    const data = await response.json();
    if (data.api_error_count > 0) {
      apiErrorSection.hidden = false;
      apiErrorCount.textContent = `${data.api_error_count} API error(s) detected (rate limits, empty responses, etc.)`;
    } else {
      apiErrorSection.hidden = true;
    }
  } catch (error) {
    console.warn('Failed to load API error info:', error);
  }
}

async function retryApiErrors() {
  if (!runId) return;

  retryApiErrorsBtn.disabled = true;
  retryApiErrorsBtn.textContent = 'Retrying...';

  try {
    const response = await fetch(`${buildRunApiPath(runId)}/retry-api-errors`, {
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
      retryApiErrorsBtn.textContent = 'No API Errors';
      return;
    }

    showToast(`Retrying ${data.api_errors_found} API errors...`, 'success');
    retryApiErrorsBtn.textContent = 'Retrying...';

    // Wait for retry to complete via WebSocket, with fallback polling
    const retryRunId = data.retry_run_id;
    await waitForRunCompletion(retryRunId, retryApiErrorsBtn, 'Retry API Errors');
  } catch (error) {
    console.error('Retry failed:', error);
    showToast(`Retry failed: ${error.message}`, 'error');
    retryApiErrorsBtn.disabled = false;
    retryApiErrorsBtn.textContent = 'Retry API Errors';
  }
}

// Helper function to wait for run completion with WebSocket + polling fallback
async function waitForRunCompletion(retryRunId, btn, btnText) {
  return new Promise((resolve) => {
    let completed = false;
    let wsConnected = false;

    const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${wsProtocol}//${location.host}/runs/${retryRunId}/stream`);

    const navigateToRun = () => {
      if (completed) return;
      completed = true;
      ws.close();
      showToast('Retry complete! Opening new run...', 'success');
      window.location.href = `/ui/run.html?run_id=${encodeURIComponent(retryRunId)}`;
      resolve();
    };

    const handleError = (msg) => {
      if (completed) return;
      completed = true;
      ws.close();
      showToast(msg, 'error');
      if (btn) {
        btn.disabled = false;
        btn.textContent = btnText;
      }
      resolve();
    };

    ws.onopen = () => {
      wsConnected = true;
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'complete') {
          navigateToRun();
        } else if (msg.type === 'error') {
          handleError(`Retry failed: ${msg.error || msg.message || 'Unknown error'}`);
        }
      } catch (e) {
        console.error('WebSocket message parse error:', e);
      }
    };

    ws.onerror = (e) => {
      console.error('WebSocket error:', e);
      // Don't fail immediately, let onclose handle it
    };

    ws.onclose = (e) => {
      if (completed) return;
      // If closed without completing, start polling as fallback
      if (e.code === 4404) {
        handleError('Run not found - retry may have failed to start');
      } else if (!wsConnected) {
        // WebSocket never connected, use polling
    debugLog('WebSocket failed to connect, using polling fallback');
        pollForRun(retryRunId, navigateToRun, handleError);
      } else {
        // WebSocket closed unexpectedly, use polling
    debugLog('WebSocket closed unexpectedly, using polling fallback');
        pollForRun(retryRunId, navigateToRun, handleError);
      }
    };

    // Timeout fallback after 5 minutes
    setTimeout(() => {
      if (!completed) {
        handleError('Retry timed out after 5 minutes');
      }
    }, 300000);
  });
}

// Poll for run existence as fallback
async function pollForRun(runId, onSuccess, onError) {
  const maxAttempts = 60;
  const interval = 2000;

  for (let i = 0; i < maxAttempts; i++) {
    try {
      const response = await fetch(`/runs/${runId}`);
      if (response.ok) {
        onSuccess();
        return;
      }
    } catch (e) {
      // Ignore fetch errors, keep polling
    }
    await new Promise(r => setTimeout(r, interval));
  }
  onError('Retry timed out - run not found after 2 minutes');
}

// Bind retry button
retryApiErrorsBtn?.addEventListener('click', retryApiErrors);

async function retrySingleAttempt(taskId, model, sampleIndex) {
  if (!runId || !taskId) return;

  const btn = document.querySelector(`tr[data-task="${taskId}"][data-model="${model}"][data-sample-index="${sampleIndex}"] .retry-single-btn`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Retrying...';
  }

  try {
    const response = await fetch(`${buildRunApiPath(runId)}/retry-single`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_id: taskId,
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
      if (btn) {
        btn.textContent = 'No Error';
      }
      return;
    }

    showToast(`Retrying ${taskId}...`, 'success');

    // Wait for retry to complete via WebSocket, with fallback polling
    const retryRunId = data.retry_run_id;
    await waitForRunCompletion(retryRunId, btn, 'Retry');
  } catch (error) {
    console.error('Single retry failed:', error);
    showToast(`Retry failed: ${error.message}`, 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Retry';
    }
  }
}

function renderRunSummary(summary) {
  const timestamp = summary.timestamp_utc
    ? new Date(summary.timestamp_utc).toLocaleString()
    : 'Unknown time';
  const filters = [];
  if (selectedModelFilter) {
    filters.push(`Model: ${selectedModelFilter}`);
  }
  if (selectedThinkingLevelFilter) {
    filters.push(`Thinking: ${formatThinkingLevel(selectedThinkingLevelFilter)}`);
  }
  runSubtitle.textContent = filters.length ? `Started ${timestamp} • ${filters.join(' • ')}` : `Started ${timestamp}`;

  runMetrics.innerHTML = '';
  const accuracy = summary.metrics?.overall?.macro_model_accuracy ?? null;
  const passRate = accuracy != null ? `${(accuracy * 100).toFixed(2)}%` : '—';
  const totalCost = summary.token_usage?.total_cost_usd;
  const totalDuration = summary.timing?.total_duration_seconds;
  const promptTokens = summary.token_usage?.prompt_tokens;
  const completionTokens = summary.token_usage?.completion_tokens;

  const metrics = [
    `Models: ${summary.models?.join(', ') || '—'}`,
    `Tasks: ${summary.tasks?.length ?? 0}`,
    `Pass Rate: ${passRate}`,
    `Total Cost: ${totalCost != null ? `$${totalCost.toFixed(6)}` : '—'}`,
    `Total Duration: ${totalDuration != null ? totalDuration.toFixed(2) : '—'}s`,
    `Tokens (P/C): ${promptTokens ?? 0}/${completionTokens ?? 0}`,
  ];
  metrics.forEach((text) => {
    const span = document.createElement('span');
    span.textContent = text;
    runMetrics.appendChild(span);
  });

  runMeta.innerHTML = '';
  const metaItems = [
    { label: 'Samples', value: summary.samples },
    { label: 'Temperature', value: summary.temperature },
    { label: 'Max Tokens', value: summary.max_tokens },
    { label: 'Include Tests', value: summary.include_tests ? 'Yes' : 'No' },
    { label: 'Install Dependencies', value: summary.install_deps ? 'Yes' : 'No' },
    { label: 'Allow Incomplete Diffs', value: summary.allow_incomplete_diffs ? 'Yes' : 'No' },
    { label: 'Allow Diff Rewrite', value: summary.allow_diff_rewrite_fallback ? 'Yes' : 'No' },
  ];
  metaItems.forEach(({ label, value }) => {
    const span = document.createElement('span');
    const strong = document.createElement('strong');
    strong.textContent = label;
    span.appendChild(strong);
    span.append(value != null ? String(value) : '—');
    runMeta.appendChild(span);
  });
}

function renderAttempts(summary) {
  const allAttempts = summary.attempts || [];
  attempts = allAttempts.filter((attempt) => {
    if (selectedModelFilter && attempt.model !== selectedModelFilter) {
      return false;
    }
    if (selectedThinkingLevelFilter) {
      const level = resolveAttemptThinkingLevel(attempt, summary.thinking_level);
      if (level !== selectedThinkingLevelFilter) {
        return false;
      }
    }
    return true;
  });
  attemptBody.innerHTML = '';

  if (!attempts.length) {
    attemptEmpty.hidden = false;
    attemptEmpty.textContent = selectedModelFilter
      ? 'No attempts found for the selected model/level in this run.'
      : 'No attempts recorded for this run.';
    return;
  }

  attemptEmpty.hidden = true;
  attemptEmpty.textContent = 'No attempts recorded for this run.';

  attempts.forEach((attempt, index) => {
    const row = document.createElement('tr');
    row.style.animationDelay = `${index * 30}ms`;
    row.classList.add('fade-in');
    row.dataset.task = attempt.task_id;
    row.dataset.status = attempt.status?.toLowerCase() || '';
    row.dataset.model = attempt.model || '';
    row.dataset.sampleIndex = attempt.sample_index ?? 0;

    const { label, className, chip } = mapStatus(attempt.status);
    const language = getTaskLanguage(attempt.task_id, TASK_LANGUAGE);
    const statusLower = attempt.status?.toLowerCase() || '';
    const canRetry = ['error', 'fail', 'failed', 'api_error', 'exception'].includes(statusLower);

    const errorText = attempt.error || '';
    const errorTruncated = errorText.length > 80 ? errorText.substring(0, 80) + '...' : errorText;
    const errorDisplay = errorText ? `<span class="error-text" title="${escapeAttr(errorText)}">${escapeHtml(errorTruncated)}</span>` : '-';

    row.innerHTML = `
      <td>${renderTaskName(attempt.task_id, TASK_LANGUAGE)}</td>
      <td class="status-cell ${className}"><span class="status-chip ${chip}">${label}</span></td>
      <td class="error-cell">${errorDisplay}</td>
      <td>${formatNumber(attempt.duration_seconds)}</td>
      <td>${extractTokens(attempt.usage, 'prompt')}</td>
      <td>${extractTokens(attempt.usage, 'completion')}</td>
      <td>${formatCost(attempt.cost_usd)}</td>
      <td class="actions-cell">${canRetry ? '<button class="ghost retry-single-btn" title="Retry this attempt">Retry</button>' : ''}</td>
    `;

    // Add click handler for retry button
    const retryBtn = row.querySelector('.retry-single-btn');
    if (retryBtn) {
      retryBtn.addEventListener('click', (e) => {
        e.stopPropagation(); // Don't trigger row click
        retrySingleAttempt(attempt.task_id, attempt.model, attempt.sample_index);
      });
    }

    row.addEventListener('click', () => {
      if (selectedRow) {
        selectedRow.classList.remove('selected');
      }
      row.classList.add('selected');
      selectedRow = row;
      showAttemptDetail(attempt);
    });

    attemptBody.appendChild(row);
  });

  // Lock onto the first attempt by default
  if (attempts.length) {
    attemptBody.firstElementChild?.classList.add('selected');
    selectedRow = attemptBody.firstElementChild;
    showAttemptDetail(attempts[0]);
  }
}

async function showAttemptDetail(attempt) {
  detailCard.hidden = false;
  detailTitle.textContent = attempt.task_id;
  detailDescription.innerHTML = '';

  const badge = createStatusBadge(attempt.status);
  detailDescription.appendChild(badge);

  if (attempt.error) {
    const errorBox = document.createElement('div');
    errorBox.className = 'empty-state';
    errorBox.textContent = attempt.error;
    detailDescription.appendChild(errorBox);
  }

  detailMeta.innerHTML = '';
  const metaItems = [
    { label: 'Model', value: attempt.model },
    { label: 'Sample', value: attempt.sample_index },
    { label: 'Duration (s)', value: formatNumber(attempt.duration_seconds) },
    { label: 'Return Code', value: attempt.return_code ?? '—' },
    { label: 'Prompt Tokens', value: extractTokens(attempt.usage, 'prompt') },
    { label: 'Completion Tokens', value: extractTokens(attempt.usage, 'completion') },
    { label: 'Cost (USD)', value: formatCost(attempt.cost_usd) },
    { label: 'API Latency (s)', value: formatNumber(attempt.api_latency_seconds) },
    { label: 'Attempt Folder', value: attempt.attempt_dir },
  ];
  metaItems.forEach(({ label, value }) => {
    const span = document.createElement('span');
    const strong = document.createElement('strong');
    strong.textContent = label;
    span.appendChild(strong);
    span.append(value != null ? String(value) : '—');
    detailMeta.appendChild(span);
  });

  detailLogs.innerHTML = '';
  const logFiles = [
    { file: 'stdout.log', label: 'stdout.log', highlight: false },
    { file: 'stderr.log', label: 'stderr.log', highlight: false },
    { file: 'error.log', label: 'error.log', highlight: false },
    { file: 'response.txt', label: 'response.txt', highlight: false },
    { file: 'patch.diff', label: 'patch.diff', highlight: true },
  ];

  const logPromises = logFiles.map(async (entry) => {
    const url = buildArtifactUrl(runId, `${attempt.attempt_dir}/${entry.file}`);
    const text = await fetchText(url);
    if (text === null) return null;
    return { ...entry, url, text };
  });

  const logs = (await Promise.all(logPromises)).filter(Boolean);

  if (!logs.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No logs captured for this attempt.';
    detailLogs.appendChild(empty);
    return;
  }

  logs.forEach(({ file, label, url, text, highlight }) => {
    const details = document.createElement('details');
    details.className = 'log-entry';

    const summary = document.createElement('summary');
    summary.textContent = label;
    details.appendChild(summary);

    const actions = document.createElement('div');
    actions.className = 'log-actions';
    actions.style.display = 'flex';
    actions.style.gap = '0.5rem';

    // Copy button
    const copyBtn = createCopyButton(text, 'Copy');
    actions.appendChild(copyBtn);

    // Open raw link
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open raw';
    actions.appendChild(link);

    details.appendChild(actions);

    const pre = document.createElement('pre');
    pre.className = 'log-output';

    if (highlight && file.endsWith('.diff')) {
      pre.classList.add('highlighted', 'line-numbers');
      pre.innerHTML = addLineNumbers(highlightDiff(text));
    } else {
      pre.textContent = text;
    }

    details.appendChild(pre);
    detailLogs.appendChild(details);
  });
}
