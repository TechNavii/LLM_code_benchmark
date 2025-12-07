/**
 * Shared UI Components Module
 * Provides reusable components across Code and QA dashboards
 */

// ============================================================================
// Toast Notification System
// ============================================================================

const toastContainer = document.createElement('div');
toastContainer.id = 'toast-container';
toastContainer.setAttribute('role', 'alert');
toastContainer.setAttribute('aria-live', 'polite');
document.body.appendChild(toastContainer);

export function showToast(message, type = 'info', duration = 4000) {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', 'status');
  
  const icon = document.createElement('span');
  icon.className = 'toast-icon';
  icon.textContent = type === 'success' ? '✓' : type === 'error' ? '✕' : type === 'warning' ? '⚠' : 'ℹ';
  
  const text = document.createElement('span');
  text.className = 'toast-message';
  text.textContent = message;
  
  const closeBtn = document.createElement('button');
  closeBtn.className = 'toast-close';
  closeBtn.textContent = '×';
  closeBtn.setAttribute('aria-label', 'Close notification');
  closeBtn.onclick = () => dismissToast(toast);
  
  toast.appendChild(icon);
  toast.appendChild(text);
  toast.appendChild(closeBtn);
  toastContainer.appendChild(toast);
  
  requestAnimationFrame(() => toast.classList.add('toast-visible'));
  
  if (duration > 0) {
    setTimeout(() => dismissToast(toast), duration);
  }
  
  return toast;
}

function dismissToast(toast) {
  toast.classList.remove('toast-visible');
  toast.classList.add('toast-hiding');
  setTimeout(() => toast.remove(), 300);
}

// ============================================================================
// Status Chip Component
// ============================================================================

export function mapStatus(status) {
  const normalized = (status || '').toString().trim().toLowerCase();
  if (['pass', 'passed', 'success'].includes(normalized)) {
    return { label: 'PASS', className: 'status-pass', chip: 'pass' };
  }
  if (['fail', 'failed'].includes(normalized)) {
    return { label: 'FAIL', className: 'status-fail', chip: 'fail' };
  }
  if (['error', 'exception'].includes(normalized)) {
    return { label: 'ERROR', className: 'status-fail', chip: 'fail' };
  }
  if (!normalized || normalized === 'pending' || normalized === 'queued') {
    return { label: 'PENDING', className: 'status-pending', chip: 'pending' };
  }
  if (normalized === 'running') {
    return { label: 'RUNNING', className: 'status-info', chip: 'info' };
  }
  return { label: normalized.toUpperCase(), className: `status-${normalized}`, chip: 'info' };
}

export function applyStatus(cell, status) {
  const { label, className, chip } = mapStatus(status);
  cell.className = `status-cell ${className}`;
  cell.innerHTML = `<span class="status-chip ${chip}">${label}</span>`;
}

export function createStatusBadge(status) {
  const { label, chip } = mapStatus(status);
  const badge = document.createElement('span');
  badge.className = `status-badge ${chip}`;
  badge.textContent = label;
  return badge;
}

// ============================================================================
// Progress Bar Component
// ============================================================================

export function createProgressBar(container) {
  const wrapper = document.createElement('div');
  wrapper.className = 'progress-wrapper';
  wrapper.setAttribute('role', 'progressbar');
  wrapper.setAttribute('aria-valuemin', '0');
  wrapper.setAttribute('aria-valuemax', '100');
  wrapper.setAttribute('aria-valuenow', '0');
  
  const bar = document.createElement('div');
  bar.className = 'progress-bar';
  
  const fill = document.createElement('div');
  fill.className = 'progress-fill';
  
  const text = document.createElement('span');
  text.className = 'progress-text';
  text.textContent = '0%';
  
  bar.appendChild(fill);
  wrapper.appendChild(bar);
  wrapper.appendChild(text);
  container.appendChild(wrapper);
  
  return {
    element: wrapper,
    update(current, total, label = null) {
      const percent = total > 0 ? Math.round((current / total) * 100) : 0;
      fill.style.width = `${percent}%`;
      text.textContent = label || `${current}/${total} (${percent}%)`;
      wrapper.setAttribute('aria-valuenow', String(percent));
    },
    show() { wrapper.hidden = false; },
    hide() { wrapper.hidden = true; },
    reset() {
      fill.style.width = '0%';
      text.textContent = '0%';
      wrapper.setAttribute('aria-valuenow', '0');
    }
  };
}

// ============================================================================
// Sortable Table Component
// ============================================================================

export function makeSortable(table, options = {}) {
  const headers = table.querySelectorAll('thead th');
  const tbody = table.querySelector('tbody');
  let currentSort = { column: null, direction: 'asc' };
  
  headers.forEach((header, index) => {
    if (header.classList.contains('no-sort') || header.classList.contains('actions-header')) return;
    
    header.classList.add('sortable');
    header.setAttribute('role', 'columnheader');
    header.setAttribute('aria-sort', 'none');
    header.tabIndex = 0;
    
    const sortIcon = document.createElement('span');
    sortIcon.className = 'sort-icon';
    sortIcon.innerHTML = '⇅';
    header.appendChild(sortIcon);
    
    const handleSort = () => {
      const direction = currentSort.column === index && currentSort.direction === 'asc' ? 'desc' : 'asc';
      sortTable(tbody, index, direction, options.comparators?.[index]);
      
      headers.forEach(h => {
        h.setAttribute('aria-sort', 'none');
        h.querySelector('.sort-icon')?.classList.remove('asc', 'desc');
      });
      
      header.setAttribute('aria-sort', direction === 'asc' ? 'ascending' : 'descending');
      sortIcon.classList.add(direction);
      currentSort = { column: index, direction };
    };
    
    header.addEventListener('click', handleSort);
    header.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleSort();
      }
    });
  });
}

function sortTable(tbody, columnIndex, direction, comparator) {
  const rows = Array.from(tbody.querySelectorAll('tr'));
  
  rows.sort((a, b) => {
    const aCell = a.cells[columnIndex];
    const bCell = b.cells[columnIndex];
    const aVal = aCell?.textContent?.trim() || '';
    const bVal = bCell?.textContent?.trim() || '';
    
    if (comparator) {
      return comparator(aVal, bVal, direction);
    }
    
    // Try numeric comparison first
    const aNum = parseFloat(aVal.replace(/[$,%]/g, ''));
    const bNum = parseFloat(bVal.replace(/[$,%]/g, ''));
    
    if (!isNaN(aNum) && !isNaN(bNum)) {
      return direction === 'asc' ? aNum - bNum : bNum - aNum;
    }
    
    // Fall back to string comparison
    const result = aVal.localeCompare(bVal, undefined, { numeric: true, sensitivity: 'base' });
    return direction === 'asc' ? result : -result;
  });
  
  rows.forEach(row => tbody.appendChild(row));
}

// ============================================================================
// Filter/Search Component
// ============================================================================

export function createFilterBar(container, options = {}) {
  const wrapper = document.createElement('div');
  wrapper.className = 'filter-bar';
  
  // Search input
  const searchGroup = document.createElement('div');
  searchGroup.className = 'filter-group';
  
  const searchInput = document.createElement('input');
  searchInput.type = 'text';
  searchInput.placeholder = options.searchPlaceholder || 'Search...';
  searchInput.className = 'filter-search';
  searchInput.setAttribute('aria-label', 'Search');
  searchGroup.appendChild(searchInput);
  wrapper.appendChild(searchGroup);
  
  // Status filter
  const statusGroup = document.createElement('div');
  statusGroup.className = 'filter-group';
  
  const statusSelect = document.createElement('select');
  statusSelect.className = 'filter-select';
  statusSelect.setAttribute('aria-label', 'Filter by status');
  statusSelect.innerHTML = `
    <option value="">All Statuses</option>
    <option value="passed">Passed</option>
    <option value="failed">Failed</option>
    <option value="error">Error</option>
  `;
  statusGroup.appendChild(statusSelect);
  wrapper.appendChild(statusGroup);
  
  // Language filter (for code tasks)
  let languageSelect = null;
  if (options.showLanguageFilter) {
    const langGroup = document.createElement('div');
    langGroup.className = 'filter-group';
    
    languageSelect = document.createElement('select');
    languageSelect.className = 'filter-select';
    languageSelect.setAttribute('aria-label', 'Filter by language');
    languageSelect.innerHTML = `
      <option value="">All Languages</option>
      <option value="python">Python</option>
      <option value="javascript">JavaScript</option>
      <option value="go">Go</option>
      <option value="rust">Rust</option>
      <option value="cpp">C++</option>
      <option value="html">HTML</option>
    `;
    langGroup.appendChild(languageSelect);
    wrapper.appendChild(langGroup);
  }
  
  // Clear button
  const clearBtn = document.createElement('button');
  clearBtn.type = 'button';
  clearBtn.className = 'ghost filter-clear';
  clearBtn.textContent = 'Clear Filters';
  clearBtn.setAttribute('aria-label', 'Clear all filters');
  wrapper.appendChild(clearBtn);
  
  container.insertBefore(wrapper, container.firstChild);
  
  return {
    element: wrapper,
    searchInput,
    statusSelect,
    languageSelect,
    clearBtn,
    getFilters() {
      return {
        search: searchInput.value.toLowerCase().trim(),
        status: statusSelect.value,
        language: languageSelect?.value || ''
      };
    },
    clear() {
      searchInput.value = '';
      statusSelect.value = '';
      if (languageSelect) languageSelect.value = '';
    },
    onFilter(callback) {
      let debounceTimer;
      const triggerFilter = () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => callback(this.getFilters()), 150);
      };
      searchInput.addEventListener('input', triggerFilter);
      statusSelect.addEventListener('change', triggerFilter);
      languageSelect?.addEventListener('change', triggerFilter);
      clearBtn.addEventListener('click', () => {
        this.clear();
        callback(this.getFilters());
      });
    }
  };
}

// ============================================================================
// Pagination Component
// ============================================================================

export function createPagination(container, options = {}) {
  const wrapper = document.createElement('div');
  wrapper.className = 'pagination';
  wrapper.setAttribute('role', 'navigation');
  wrapper.setAttribute('aria-label', 'Pagination');
  
  const info = document.createElement('span');
  info.className = 'pagination-info';
  
  const controls = document.createElement('div');
  controls.className = 'pagination-controls';
  
  const prevBtn = document.createElement('button');
  prevBtn.type = 'button';
  prevBtn.className = 'ghost pagination-btn';
  prevBtn.textContent = '← Previous';
  prevBtn.setAttribute('aria-label', 'Previous page');
  
  const pageInfo = document.createElement('span');
  pageInfo.className = 'pagination-page';
  
  const nextBtn = document.createElement('button');
  nextBtn.type = 'button';
  nextBtn.className = 'ghost pagination-btn';
  nextBtn.textContent = 'Next →';
  nextBtn.setAttribute('aria-label', 'Next page');
  
  controls.appendChild(prevBtn);
  controls.appendChild(pageInfo);
  controls.appendChild(nextBtn);
  
  wrapper.appendChild(info);
  wrapper.appendChild(controls);
  container.appendChild(wrapper);
  
  let currentPage = 1;
  let totalPages = 1;
  let totalItems = 0;
  const pageSize = options.pageSize || 20;
  
  return {
    element: wrapper,
    pageSize,
    update(total, page = 1) {
      totalItems = total;
      totalPages = Math.ceil(total / pageSize) || 1;
      currentPage = Math.min(Math.max(1, page), totalPages);
      
      info.textContent = `Showing ${Math.min((currentPage - 1) * pageSize + 1, total)}-${Math.min(currentPage * pageSize, total)} of ${total}`;
      pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
      
      prevBtn.disabled = currentPage <= 1;
      nextBtn.disabled = currentPage >= totalPages;
    },
    getPage() { return currentPage; },
    getOffset() { return (currentPage - 1) * pageSize; },
    onPageChange(callback) {
      prevBtn.addEventListener('click', () => {
        if (currentPage > 1) {
          currentPage--;
          this.update(totalItems, currentPage);
          callback(currentPage, this.getOffset());
        }
      });
      nextBtn.addEventListener('click', () => {
        if (currentPage < totalPages) {
          currentPage++;
          this.update(totalItems, currentPage);
          callback(currentPage, this.getOffset());
        }
      });
    }
  };
}

// ============================================================================
// Copy Button Component
// ============================================================================

export function createCopyButton(text, label = 'Copy') {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ghost copy-btn';
  btn.innerHTML = `<span class="copy-icon">📋</span> ${label}`;
  btn.setAttribute('aria-label', `Copy ${label}`);
  
  btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(text);
      btn.classList.add('copied');
      btn.innerHTML = `<span class="copy-icon">✓</span> Copied!`;
      showToast('Copied to clipboard', 'success', 2000);
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = `<span class="copy-icon">📋</span> ${label}`;
      }, 2000);
    } catch (err) {
      showToast('Failed to copy', 'error');
    }
  });
  
  return btn;
}

// ============================================================================
// Export Functions
// ============================================================================

export function exportToCSV(data, filename) {
  if (!data || !data.length) {
    showToast('No data to export', 'warning');
    return;
  }
  
  const headers = Object.keys(data[0]);
  const csvContent = [
    headers.join(','),
    ...data.map(row => headers.map(h => {
      const val = row[h];
      if (val === null || val === undefined) return '';
      const str = String(val);
      return str.includes(',') || str.includes('"') || str.includes('\n')
        ? `"${str.replace(/"/g, '""')}"`
        : str;
    }).join(','))
  ].join('\n');
  
  downloadFile(csvContent, filename, 'text/csv');
  showToast(`Exported ${data.length} rows to ${filename}`, 'success');
}

export function exportToJSON(data, filename) {
  if (!data || !data.length) {
    showToast('No data to export', 'warning');
    return;
  }
  
  const jsonContent = JSON.stringify(data, null, 2);
  downloadFile(jsonContent, filename, 'application/json');
  showToast(`Exported ${data.length} items to ${filename}`, 'success');
}

function downloadFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ============================================================================
// Loading Skeleton Component
// ============================================================================

export function createSkeleton(rows = 5, cols = 6) {
  const fragment = document.createDocumentFragment();
  for (let i = 0; i < rows; i++) {
    const row = document.createElement('tr');
    row.className = 'skeleton-row';
    for (let j = 0; j < cols; j++) {
      const cell = document.createElement('td');
      const skeleton = document.createElement('div');
      skeleton.className = 'skeleton';
      cell.appendChild(skeleton);
      row.appendChild(cell);
    }
    fragment.appendChild(row);
  }
  return fragment;
}

export function showTableSkeleton(tbody, rows = 5, cols = 6) {
  tbody.innerHTML = '';
  tbody.appendChild(createSkeleton(rows, cols));
}

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

const shortcuts = new Map();

export function registerShortcut(key, callback, description) {
  shortcuts.set(key.toLowerCase(), { callback, description });
}

export function showShortcutsHelp() {
  const modal = document.createElement('div');
  modal.className = 'shortcuts-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-label', 'Keyboard shortcuts');
  
  const content = document.createElement('div');
  content.className = 'shortcuts-content';
  
  const title = document.createElement('h3');
  title.textContent = 'Keyboard Shortcuts';
  content.appendChild(title);
  
  const list = document.createElement('dl');
  list.className = 'shortcuts-list';
  
  shortcuts.forEach((value, key) => {
    const dt = document.createElement('dt');
    dt.innerHTML = `<kbd>${key}</kbd>`;
    const dd = document.createElement('dd');
    dd.textContent = value.description;
    list.appendChild(dt);
    list.appendChild(dd);
  });
  
  content.appendChild(list);
  
  const closeBtn = document.createElement('button');
  closeBtn.className = 'ghost';
  closeBtn.textContent = 'Close (Esc)';
  closeBtn.onclick = () => modal.remove();
  content.appendChild(closeBtn);
  
  modal.appendChild(content);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.remove();
  });
  
  document.body.appendChild(modal);
  closeBtn.focus();
}

document.addEventListener('keydown', (e) => {
  // Don't trigger shortcuts when typing in inputs
  if (e.target.matches('input, textarea, select')) return;
  
  const key = e.key.toLowerCase();
  if (key === '?' && e.shiftKey) {
    e.preventDefault();
    showShortcutsHelp();
    return;
  }
  
  const shortcut = shortcuts.get(key);
  if (shortcut) {
    e.preventDefault();
    shortcut.callback();
  }
});

// Register default shortcuts
registerShortcut('?', showShortcutsHelp, 'Show keyboard shortcuts');

// ============================================================================
// Utility Functions
// ============================================================================

export function formatNumber(value, decimals = 2) {
  if (value == null) return '-';
  return Number(value).toFixed(decimals);
}

export function formatCost(value) {
  if (value == null) return '-';
  return `$${Number(value).toFixed(6)}`;
}

export function formatPercent(value) {
  if (value == null) return '-';
  return `${(value * 100).toFixed(2)}%`;
}

export function formatTimestamp(timestamp) {
  if (!timestamp) return '-';
  const date = new Date(timestamp);
  if (isNaN(date.getTime())) return timestamp;
  return date.toLocaleString();
}

export function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

// ============================================================================
// Language Utilities
// ============================================================================

export const LANGUAGE_LABELS = {
  javascript: 'JS',
  python: 'PY',
  go: 'GO',
  cpp: 'C++',
  html: 'HTML',
  rust: 'RS',
  default: '??',
};

export const LANGUAGE_COLORS = {
  javascript: '#fcd34d',
  python: '#fde68a',
  go: '#a7f3d0',
  cpp: '#bfdbfe',
  html: '#fca5a5',
  rust: '#fbbf24',
  default: '#cbd5e1',
};

export function renderTaskName(taskId, taskLanguageMap = {}) {
  const language = taskLanguageMap[taskId] || 'default';
  const label = LANGUAGE_LABELS[language] || LANGUAGE_LABELS.default;
  const iconClass = LANGUAGE_LABELS[language] ? language : 'default';
  return `<span class="task-name"><span class="task-icon ${iconClass}">${label}</span><span>${taskId}</span></span>`;
}

export function getTaskLanguage(taskId, taskLanguageMap = {}) {
  return taskLanguageMap[taskId] || 'default';
}
