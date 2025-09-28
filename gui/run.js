const params = new URLSearchParams(window.location.search);
const runId = params.get('run_id');

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

let attempts = [];
let selectedRow = null;

if (!runId) {
  setRunMessage('Run ID missing from URL. Append ?run_id=<id>.', 'error');
  runTitle.textContent = 'Unknown run';
} else {
  runTitle.textContent = runId;
  loadRunDetails();
}

function setRunMessage(message, level = 'info') {
  runMessage.textContent = message;
  runMessage.className = `status ${level}`;
}

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
  } catch (error) {
    console.error(error);
    setRunMessage(`Failed to load run: ${error.message}`, 'error');
  }
}

function renderRunSummary(summary) {
  const timestamp = summary.timestamp_utc
    ? new Date(summary.timestamp_utc).toLocaleString()
    : 'Unknown time';
  runSubtitle.textContent = `Started ${timestamp}`;

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
  attempts = summary.attempts || [];
  attemptBody.innerHTML = '';
  if (!attempts.length) {
    attemptEmpty.hidden = false;
    return;
  }
  attemptEmpty.hidden = true;
  attempts.forEach((attempt, index) => {
    const row = document.createElement('tr');
    row.style.animationDelay = `${index * 30}ms`;
    const { label, className, chip } = mapStatus(attempt.status);
    row.innerHTML = `
      <td>${attempt.task_id}</td>
      <td class="status-cell ${className}"><span class="status-chip ${chip}">${label}</span></td>
      <td>${formatNumber(attempt.duration_seconds)}</td>
      <td>${extractTokens(attempt.usage, 'prompt')}</td>
      <td>${extractTokens(attempt.usage, 'completion')}</td>
      <td>${formatCost(attempt.cost_usd)}</td>
    `;
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

function formatNumber(value) {
  if (value == null) {
    return '-';
  }
  return Number(value).toFixed(2);
}

function extractTokens(usage, type) {
  if (!usage) {
    return '-';
  }
  if (type === 'prompt') {
    return usage.prompt_tokens ?? usage.input_tokens ?? '-';
  }
  return usage.completion_tokens ?? usage.output_tokens ?? '-';
}

function formatCost(cost) {
  if (cost == null) {
    return '-';
  }
  return `$${Number(cost).toFixed(6)}`;
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
    { file: 'stdout.log', label: 'stdout.log' },
    { file: 'stderr.log', label: 'stderr.log' },
    { file: 'error.log', label: 'error.log' },
    { file: 'response.txt', label: 'response.txt' },
    { file: 'patch.diff', label: 'patch.diff' },
  ];

  const logPromises = logFiles.map(async (entry) => {
    const url = buildArtifactUrl(runId, `${attempt.attempt_dir}/${entry.file}`);
    const text = await fetchText(url);
    if (text === null) {
      return null;
    }
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

  logs.forEach(({ file, label, url, text }) => {
    const details = document.createElement('details');
    details.className = 'log-entry';
    const summary = document.createElement('summary');
    summary.textContent = label;
    details.appendChild(summary);

    const actions = document.createElement('div');
    actions.className = 'log-actions';
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open raw';
    actions.appendChild(link);
    details.appendChild(actions);

    const pre = document.createElement('pre');
    pre.className = 'log-output';
    pre.textContent = text;
    details.appendChild(pre);
    detailLogs.appendChild(details);
  });
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

function createStatusBadge(status) {
  const { label, className, chip } = mapStatus(status);
  const badge = document.createElement('span');
  const variant = chip || (className.startsWith('status-') ? className.replace('status-', '') : className);
  const palette = new Set(['pass', 'fail', 'pending', 'info']);
  badge.className = `status-badge ${palette.has(variant) ? variant : 'info'}`;
  badge.textContent = label;
  return badge;
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
  return path
    .split('/')
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join('/');
}

async function fetchText(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      return null;
    }
    const text = await response.text();
    return truncateForDisplay(text);
  } catch (error) {
    console.warn(`Failed to fetch ${url}`, error);
    return null;
  }
}

function truncateForDisplay(text) {
  const limit = 20000;
  if (text.length <= limit) {
    return text || '(empty)';
  }
  return `${text.slice(0, limit)}\n\n… truncated (${text.length - limit} characters omitted)`;
}
