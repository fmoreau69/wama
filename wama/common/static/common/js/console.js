/**
 * WAMA Unified Console
 *
 * Reads structured log entries from the centralized console endpoint.
 * Renders differently based on user role:
 *   - user:  minimal (message only)
 *   - dev:   detailed with timestamps, colored levels
 *   - admin: detailed + "All applications" toggle
 *
 * Data attributes on the console container:
 *   data-console-url  — endpoint URL (/common/api/console/)
 *   data-app-name     — current app name (anonymizer, imager, ...)
 *   data-user-role    — user | dev | admin | anonymous
 */
document.addEventListener('DOMContentLoaded', function () {
  var container = document.querySelector('[data-console-url]');
  if (!container) return;

  var endpoint = container.dataset.consoleUrl;
  var appName = container.dataset.appName || 'system';
  var role = container.dataset.userRole || 'user';
  if (!endpoint) return;

  // Level color classes
  var LEVEL_COLORS = {
    info: '#8ec8e8',
    warning: '#ffc107',
    error: '#ff6b6b',
    debug: '#6c757d'
  };

  // App badge colors
  var APP_COLORS = {
    anonymizer: '#667eea',
    imager: '#f093fb',
    enhancer: '#4fd1c5',
    transcriber: '#fbd38d',
    synthesizer: '#90cdf4',
    describer: '#feb2b2',
    model_manager: '#c4b5fd',
    system: '#adb5bd'
  };

  function getSelectedLevels() {
    var checks = document.querySelectorAll('.console-level-filter:checked');
    if (!checks.length) return '';
    var levels = [];
    checks.forEach(function (cb) { levels.push(cb.value); });
    return levels.join(',');
  }

  function getAllApps() {
    var toggle = document.getElementById('filter-all-apps');
    return toggle && toggle.checked;
  }

  function buildUrl() {
    var params = [];
    // Levels (only if toolbar visible = dev/admin)
    if (role === 'dev' || role === 'admin') {
      var levels = getSelectedLevels();
      // Always send levels param; empty = none selected = show nothing
      params.push('levels=' + (levels || 'none'));
    }
    // App filter
    if (getAllApps()) {
      params.push('app=all');
    } else {
      params.push('app=' + encodeURIComponent(appName));
    }
    return endpoint + (params.length ? '?' + params.join('&') : '');
  }

  function escapeHtml(str) {
    if (typeof str !== 'string') str = String(str == null ? '' : str);
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderLine(entry) {
    if (typeof entry === 'string') entry = { msg: entry, level: 'info' };
    var msg = escapeHtml(entry.msg || '');
    var level = entry.level || 'info';
    var color = LEVEL_COLORS[level] || LEVEL_COLORS.info;

    // User mode: minimal display (message only)
    if (role === 'user' || role === 'anonymous') {
      return '<div class="console-line" style="white-space:pre-wrap;word-break:break-word;color:' + color + ';">' + msg + '</div>';
    }

    // Dev/Admin mode: timestamp + app badge + colored message
    var parts = [];

    // Timestamp
    if (entry.ts) {
      parts.push('<span style="color:#6c757d;margin-right:6px;">[' + escapeHtml(entry.ts) + ']</span>');
    }

    // App badge (visible in all-apps mode or always for dev/admin)
    var appLabel = entry.app || 'system';
    var appColor = APP_COLORS[appLabel] || APP_COLORS.system;
    parts.push('<span style="color:' + appColor + ';font-weight:600;margin-right:6px;">[' + escapeHtml(appLabel) + ']</span>');

    // Message
    parts.push('<span style="color:' + color + ';">' + msg + '</span>');

    return '<div class="console-line" style="white-space:pre-wrap;word-break:break-word;">' + parts.join('') + '</div>';
  }

  function refreshConsole() {
    var url = buildUrl();
    fetch(url)
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })
      .then(function (data) {
        var lines = data.output || [];
        if (!lines.length) {
          container.innerHTML = '<p class="mb-0 text-muted">Aucun log disponible.</p>';
          return;
        }
        container.innerHTML = lines.map(renderLine).join('');
        // Auto-scroll to bottom
        var parent = container.parentElement;
        if (parent) parent.scrollTop = parent.scrollHeight;
      })
      .catch(function (error) {
        console.error('Console fetch error:', error);
        container.innerHTML = '<p class="text-danger mb-0">Erreur: ' + escapeHtml(error.message) + '</p>';
      });
  }

  // Event listeners on filter checkboxes (dev/admin)
  document.querySelectorAll('.console-level-filter').forEach(function (cb) {
    cb.addEventListener('change', refreshConsole);
  });
  var allAppsToggle = document.getElementById('filter-all-apps');
  if (allAppsToggle) {
    allAppsToggle.addEventListener('change', refreshConsole);
  }

  // Initial load + polling every 3 seconds
  refreshConsole();
  setInterval(refreshConsole, 3000);
});
