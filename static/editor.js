/* Canon Editor — structured editing, conflict detection, AC checklists */

// ─── State ──────────────────────────────────────────────────────
var editorMode = 'source'; // 'source' or 'structured'
var parsedSections = [];    // populated by parse endpoint

// ─── DOM helpers ────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function getEditorVars() {
  return {
    org: $('editor-org').value,
    owner: $('editor-owner').value,
    repo: $('editor-repo').value,
    sha: $('editor-sha').value,
    mode: $('editor-mode').value,
  };
}

function getFilePath() {
  var v = getEditorVars();
  return v.mode === 'new' ? $('fm-file-path').value : $('editor-file-path').value;
}

function encodePath(p) {
  return p.split('/').map(encodeURIComponent).join('/');
}

function editorUrl(v, suffix) {
  return '/app/' + encodeURIComponent(v.org) + '/editor/' +
    encodeURIComponent(v.owner) + '/' + encodeURIComponent(v.repo) + '/' + suffix;
}

function _sanitizeHtml(html) {
  if (typeof DOMPurify !== 'undefined') return DOMPurify.sanitize(html);
  return html;
}

// ─── Frontmatter parse on load ──────────────────────────────────
(function initFrontmatter() {
  var content = $('editor-content').value;
  var m = content.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (m) {
    try {
      var fm = jsyaml.load(m[1]);
      if (fm.title) $('fm-title').value = fm.title;
      if (fm.status) $('fm-status').value = fm.status;
      if (fm.review_status) $('fm-review-status').value = fm.review_status;
      if (fm.owner) $('fm-owner').value = fm.owner;
      if (fm.team) $('fm-team').value = fm.team;
      if (fm.tags && Array.isArray(fm.tags)) $('fm-tags').value = fm.tags.join(', ');
      $('editor-content').value = m[2];
    } catch(e) { /* ignore parse errors */ }
  }
})();

// ─── Markdown building ──────────────────────────────────────────
function buildFrontmatter() {
  var fm = {
    title: $('fm-title').value || 'Untitled',
    status: $('fm-status').value || 'draft',
  };
  var owner = $('fm-owner').value;
  if (owner) fm.owner = owner;
  var team = $('fm-team').value;
  if (team) fm.team = team;
  var reviewStatus = $('fm-review-status').value;
  if (reviewStatus) fm.review_status = reviewStatus;
  var tags = $('fm-tags').value;
  if (tags) fm.tags = tags.split(',').map(function(t) { return t.trim(); }).filter(Boolean);
  return '---\n' + jsyaml.dump(fm, {lineWidth: -1}).trim() + '\n---\n\n';
}

function buildBodyFromSections() {
  var parts = [];
  parsedSections.forEach(function(sec) {
    parts.push(_buildSectionMarkdown(sec));
  });
  return parts.join('\n\n');
}

function _buildSectionMarkdown(sec) {
  var lines = [];
  var prefix = sec.depth === 2 ? '##' : '###';
  var heading = prefix + ' ' + (sec.section_number ? sec.section_number + '. ' : '') + sec.title;
  lines.push(heading);
  lines.push('');

  // Status comment
  if (sec.id && sec.status) {
    lines.push('<!-- specwright:system:' + sec.id + ' status:' + sec.status + ' -->');
  }

  // Ticket link comment (preserved)
  if (sec.ticket_link) {
    lines.push('<!-- specwright:ticket:' + sec.ticket_link.system + ':' + sec.ticket_link.ticket_id + ' -->');
  }

  // Prose content
  var prose = (sec.prose_content || '').trim();
  if (prose) {
    lines.push('');
    lines.push(prose);
  }

  // Acceptance criteria
  if (sec.acceptance_criteria && sec.acceptance_criteria.length > 0) {
    lines.push('');
    lines.push('### Acceptance Criteria');
    lines.push('');
    sec.acceptance_criteria.forEach(function(ac) {
      var check = ac.checked ? '[x]' : '[ ]';
      lines.push('- ' + check + ' ' + ac.text);
      if (ac.realized_in) {
        ac.realized_in.forEach(function(r) {
          var comment = '<!-- specwright:realized-in:PR#' + r.pr_number + ' file:' + r.file_path;
          if (r.lines) comment += ':' + r.lines;
          comment += ' -->';
          lines.push(comment);
        });
      }
    });
  }

  // Children (h3 subsections)
  if (sec.children && sec.children.length > 0) {
    sec.children.forEach(function(child) {
      lines.push('');
      lines.push(_buildSectionMarkdown(child));
    });
  }

  return lines.join('\n');
}

function buildMarkdown() {
  var header = buildFrontmatter();
  var body;
  if (editorMode === 'structured') {
    syncSectionsFromDOM();
    body = buildBodyFromSections();
  } else {
    body = $('editor-content').value;
  }
  return header + body;
}

// ─── Status toast ───────────────────────────────────────────────
function showStatus(msg, isError) {
  var el = $('editor-status');
  el.textContent = msg;
  el.className = 'fixed bottom-4 right-4 px-4 py-2 rounded-md text-sm font-medium shadow-lg z-50 ' +
    (isError ? 'bg-red-500 text-white' : 'bg-accent-500 text-white');
  el.classList.remove('hidden');
  setTimeout(function() { el.classList.add('hidden'); }, 4000);
}

// ─── Conflict modal ─────────────────────────────────────────────
function showConflictModal(serverContent, serverSha, localContent) {
  $('conflict-server-content').textContent = serverContent || '(Unable to fetch server version)';
  $('conflict-local-content').textContent = localContent;
  // Store in data attributes for resolution
  var modal = $('conflict-modal');
  modal.dataset.serverContent = serverContent || '';
  modal.dataset.serverSha = serverSha || '';
  modal.classList.remove('hidden');
}

function hideConflictModal() {
  $('conflict-modal').classList.add('hidden');
}

function resolveConflictUseServer() {
  var modal = $('conflict-modal');
  var serverContent = modal.dataset.serverContent;
  var serverSha = modal.dataset.serverSha;
  if (serverContent) {
    // Re-parse frontmatter from server content and reload editor
    var m = serverContent.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
    if (m) {
      try {
        var fm = jsyaml.load(m[1]);
        if (fm.title) $('fm-title').value = fm.title;
        if (fm.status) $('fm-status').value = fm.status;
        if (fm.review_status) $('fm-review-status').value = fm.review_status || '';
        if (fm.owner) $('fm-owner').value = fm.owner;
        if (fm.team) $('fm-team').value = fm.team;
        if (fm.tags && Array.isArray(fm.tags)) $('fm-tags').value = fm.tags.join(', ');
        $('editor-content').value = m[2];
      } catch(e) {
        $('editor-content').value = serverContent;
      }
    } else {
      $('editor-content').value = serverContent;
    }
    $('editor-sha').value = serverSha;
    if (editorMode === 'structured') {
      switchToStructuredMode();
    }
  }
  hideConflictModal();
  showStatus('Loaded server version', false);
}

function resolveConflictOverwrite() {
  var modal = $('conflict-modal');
  var serverSha = modal.dataset.serverSha;
  $('editor-sha').value = serverSha;
  hideConflictModal();
  // Retry save with updated SHA
  saveSpec();
}

// ─── Save with conflict handling ────────────────────────────────
function saveSpec() {
  var v = getEditorVars();
  var filePath = getFilePath();
  var sha = $('editor-sha').value;
  var content = buildMarkdown();

  if (!filePath) { showStatus('Please enter a file path', true); return; }

  fetch(editorUrl(v, encodePath(filePath) + '/save'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content: content, sha: sha, message: 'docs: update ' + filePath})
  })
  .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
  .then(function(res) {
    if (res.data.ok) {
      $('editor-sha').value = res.data.sha || '';
      showStatus('Saved successfully!', false);
    } else if (res.status === 409 && res.data.error === 'conflict') {
      showConflictModal(res.data.server_content, res.data.server_sha, content);
    } else {
      showStatus(res.data.error || 'Save failed', true);
    }
  })
  .catch(function(e) { showStatus('Save failed: ' + e.message, true); });
}

function saveAsPR() {
  var v = getEditorVars();
  var filePath = getFilePath();
  var sha = $('editor-sha').value;
  var content = buildMarkdown();
  var title = $('fm-title').value;

  if (!filePath) { showStatus('Please enter a file path', true); return; }

  fetch(editorUrl(v, encodePath(filePath) + '/save-pr'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      content: content, sha: sha,
      pr_title: 'docs: ' + (title || filePath),
      pr_body: 'Spec update via Canon editor.'
    })
  })
  .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
  .then(function(res) {
    if (res.data.ok) {
      showStatus('PR created!', false);
      if (res.data.pr_url) window.open(res.data.pr_url, '_blank');
    } else {
      showStatus(res.data.error || 'PR creation failed', true);
    }
  })
  .catch(function(e) { showStatus('PR creation failed: ' + e.message, true); });
}

function requestReview() {
  $('fm-review-status').value = 'in_review';
  var v = getEditorVars();
  var filePath = getFilePath();
  var sha = $('editor-sha').value;
  var content = buildMarkdown();
  var title = $('fm-title').value;

  if (!filePath) { showStatus('Please enter a file path', true); return; }

  fetch(editorUrl(v, encodePath(filePath) + '/save-pr'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      content: content, sha: sha,
      pr_title: 'docs: request review for ' + (title || filePath),
      pr_body: 'Spec submitted for review via Canon editor.\n\nReview status set to `in_review`.'
    })
  })
  .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
  .then(function(res) {
    if (res.data.ok) {
      showStatus('Review requested! PR created.', false);
      if (res.data.pr_url) window.open(res.data.pr_url, '_blank');
    } else {
      showStatus(res.data.error || 'Request review failed', true);
    }
  })
  .catch(function(e) { showStatus('Request review failed: ' + e.message, true); });
}

function previewSpec() {
  var v = getEditorVars();
  var content = buildMarkdown();
  var preview = $('preview-area');

  fetch(editorUrl(v, 'preview'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content: content})
  })
  .then(function(r) { return r.text(); })
  .then(function(html) {
    preview.innerHTML = _sanitizeHtml(html);
    preview.classList.remove('hidden');
    preview.scrollIntoView({behavior: 'smooth'});
  })
  .catch(function(e) { showStatus('Preview failed: ' + e.message, true); });
}

// ─── Mode toggle: Source ↔ Structured ───────────────────────────

var SECTION_STATUSES = ['draft', 'todo', 'in_progress', 'done', 'blocked', 'deprecated'];
var _modeTogglePending = false;

function toggleEditorMode() {
  if (_modeTogglePending) return;
  if (editorMode === 'source') {
    switchToStructuredMode();
  } else {
    switchToSourceMode();
  }
}

function switchToStructuredMode() {
  var v = getEditorVars();
  var body = $('editor-content').value;
  var fullContent = buildFrontmatter() + body;

  _modeTogglePending = true;
  $('mode-toggle-btn').disabled = true;
  $('mode-toggle-btn').textContent = 'Loading...';
  $('mode-toggle-btn').classList.remove('border-gray-300', 'dark:border-slate-600');
  $('mode-toggle-btn').classList.add('border-accent-400', 'dark:border-accent-500');

  fetch(editorUrl(v, 'parse'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content: fullContent})
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.ok) {
      parsedSections = data.sections;
      editorMode = 'structured';
      renderStructuredEditor();
      $('mode-toggle-btn').textContent = 'Switch to Source';
    } else {
      showStatus('Parse failed: ' + (data.error || 'unknown'), true);
      $('mode-toggle-btn').textContent = 'Switch to Structured';
      $('mode-toggle-btn').classList.remove('border-accent-400', 'dark:border-accent-500');
      $('mode-toggle-btn').classList.add('border-gray-300', 'dark:border-slate-600');
    }
  })
  .catch(function(e) {
    showStatus('Parse failed: ' + e.message, true);
    $('mode-toggle-btn').textContent = 'Switch to Structured';
    $('mode-toggle-btn').classList.remove('border-accent-400', 'dark:border-accent-500');
    $('mode-toggle-btn').classList.add('border-gray-300', 'dark:border-slate-600');
  })
  .finally(function() {
    _modeTogglePending = false;
    $('mode-toggle-btn').disabled = false;
  });
}

function switchToSourceMode() {
  if (editorMode === 'structured') {
    syncSectionsFromDOM();
    $('editor-content').value = buildBodyFromSections();
  }
  editorMode = 'source';
  $('source-editor').classList.remove('hidden');
  $('structured-editor').classList.add('hidden');
  $('mode-toggle-btn').textContent = 'Switch to Structured';
  $('mode-toggle-btn').classList.remove('border-accent-400', 'dark:border-accent-500');
  $('mode-toggle-btn').classList.add('border-gray-300', 'dark:border-slate-600');
}

function renderStructuredEditor() {
  $('source-editor').classList.add('hidden');
  var container = $('structured-editor');
  container.classList.remove('hidden');
  container.innerHTML = '';

  parsedSections.forEach(function(sec, idx) {
    container.appendChild(buildSectionCard(sec, idx, false));
  });

  // Add section button
  var addBtn = document.createElement('button');
  addBtn.className = 'mt-3 w-full px-3 py-2 text-sm font-medium rounded-md border border-dashed border-gray-300 dark:border-slate-600 text-slate-500 dark:text-slate-400 hover:border-accent-400 hover:text-accent-500 transition-colors';
  addBtn.textContent = '+ Add Section';
  addBtn.onclick = function() { addSection(); };
  container.appendChild(addBtn);
}

function buildSectionCard(sec, idx, isChild, parentIdx) {
  var card = document.createElement('div');
  card.className = 'section-card bg-gray-50 dark:bg-[#0d1321] rounded-lg border border-gray-200 dark:border-slate-700 p-4 ' + (isChild ? 'ml-4 mt-3' : 'mb-4');
  card.dataset.sectionIndex = idx;
  card.dataset.isChild = isChild ? '1' : '0';

  // Header row: title + controls
  var header = document.createElement('div');
  header.className = 'flex items-center gap-2 mb-3';

  var depthLabel = document.createElement('span');
  depthLabel.className = 'text-xs font-mono text-slate-400 dark:text-slate-500';
  depthLabel.textContent = sec.depth === 2 ? 'H2' : 'H3';
  header.appendChild(depthLabel);

  var titleInput = document.createElement('input');
  titleInput.type = 'text';
  titleInput.value = sec.title;
  titleInput.className = 'section-title flex-1 rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-[#0a0f1a] text-slate-800 dark:text-slate-200 px-2 py-1 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-accent-500';
  header.appendChild(titleInput);

  // Status dropdown
  var statusSel = document.createElement('select');
  statusSel.className = 'section-status rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-[#0a0f1a] text-slate-800 dark:text-slate-200 px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent-500';
  SECTION_STATUSES.forEach(function(s) {
    var opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s.replace('_', ' ');
    if (s === sec.status) opt.selected = true;
    statusSel.appendChild(opt);
  });
  header.appendChild(statusSel);

  // Move/delete buttons
  if (!isChild) {
    var moveUp = document.createElement('button');
    moveUp.className = 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-sm px-1';
    moveUp.innerHTML = '&#9650;';
    moveUp.title = 'Move up';
    moveUp.onclick = function() { moveSectionUp(idx); };
    header.appendChild(moveUp);

    var moveDown = document.createElement('button');
    moveDown.className = 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-sm px-1';
    moveDown.innerHTML = '&#9660;';
    moveDown.title = 'Move down';
    moveDown.onclick = function() { moveSectionDown(idx); };
    header.appendChild(moveDown);
  }

  var delBtn = document.createElement('button');
  delBtn.className = 'text-red-400 hover:text-red-600 text-sm px-1';
  delBtn.innerHTML = '&#10005;';
  delBtn.title = 'Delete section';
  delBtn.onclick = function() { deleteSection(idx, isChild, parentIdx); };
  header.appendChild(delBtn);

  card.appendChild(header);

  // Prose textarea
  var proseLabel = document.createElement('label');
  proseLabel.className = 'block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1';
  proseLabel.textContent = 'Content';
  card.appendChild(proseLabel);

  var proseArea = document.createElement('textarea');
  proseArea.className = 'section-prose w-full rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-[#0a0f1a] text-slate-800 dark:text-slate-200 px-2 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent-500 resize-y';
  proseArea.rows = 4;
  proseArea.value = sec.prose_content || '';
  card.appendChild(proseArea);

  // Acceptance criteria
  var acSection = document.createElement('div');
  acSection.className = 'ac-container mt-3';
  var acLabel = document.createElement('div');
  acLabel.className = 'flex items-center justify-between mb-2';
  acLabel.innerHTML = '<span class="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Acceptance Criteria</span>';
  var addAcBtn = document.createElement('button');
  addAcBtn.className = 'text-xs text-accent-500 hover:text-accent-600 font-medium';
  addAcBtn.textContent = '+ Add';
  addAcBtn.onclick = function() { addAC(acSection); };
  acLabel.appendChild(addAcBtn);
  acSection.appendChild(acLabel);

  if (sec.acceptance_criteria) {
    sec.acceptance_criteria.forEach(function(ac, acIdx) {
      acSection.appendChild(buildACItem(ac, acIdx));
    });
  }
  card.appendChild(acSection);

  // Child sections (h3 inside h2)
  if (sec.children && sec.children.length > 0) {
    var childContainer = document.createElement('div');
    childContainer.className = 'children-container mt-3';
    sec.children.forEach(function(child, childIdx) {
      childContainer.appendChild(buildSectionCard(child, childIdx, true, idx));
    });
    card.appendChild(childContainer);
  }

  return card;
}

function buildACItem(ac, idx) {
  var row = document.createElement('div');
  row.className = 'ac-item flex items-start gap-2 mb-1.5';

  var cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = ac.checked;
  cb.className = 'ac-check mt-1 rounded border-gray-300 dark:border-slate-600 text-accent-500 focus:ring-accent-500';
  row.appendChild(cb);

  var textInput = document.createElement('input');
  textInput.type = 'text';
  textInput.value = ac.text;
  textInput.className = 'ac-text flex-1 rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-[#0a0f1a] text-slate-800 dark:text-slate-200 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500';
  row.appendChild(textInput);

  // Store realized_in as a data attribute
  if (ac.realized_in && ac.realized_in.length > 0) {
    textInput.dataset.realizedIn = JSON.stringify(ac.realized_in);
    var badge = document.createElement('span');
    badge.className = 'text-xs text-green-500 dark:text-green-400 mt-1 whitespace-nowrap';
    badge.textContent = 'PR#' + ac.realized_in[0].pr_number;
    row.appendChild(badge);
  }

  var delBtn = document.createElement('button');
  delBtn.className = 'text-red-400 hover:text-red-600 text-sm mt-0.5';
  delBtn.innerHTML = '&#10005;';
  delBtn.onclick = function() { row.remove(); };
  row.appendChild(delBtn);

  return row;
}

// ─── Section operations ─────────────────────────────────────────

function _nextSectionNumber() {
  var max = 0;
  parsedSections.forEach(function(s) {
    var n = parseInt(s.section_number, 10);
    if (!isNaN(n) && n > max) max = n;
  });
  return String(max + 1);
}

function addSection() {
  syncSectionsFromDOM();
  var num = _nextSectionNumber();
  var newSec = {
    id: null,
    section_number: num,
    title: 'New Section',
    depth: 2,
    content: '',
    prose_content: '',
    status: 'draft',
    acceptance_criteria: [],
    children: [],
    ticket_link: null,
  };
  parsedSections.push(newSec);
  renderStructuredEditor();
}

function deleteSection(idx, isChild, parentIdx) {
  if (!confirm('Delete this section?')) return;
  syncSectionsFromDOM();
  if (isChild && parentIdx !== undefined) {
    parsedSections[parentIdx].children.splice(idx, 1);
  } else {
    parsedSections.splice(idx, 1);
  }
  renderStructuredEditor();
}

function moveSectionUp(idx) {
  if (idx <= 0) return;
  syncSectionsFromDOM();
  var tmp = parsedSections[idx];
  parsedSections[idx] = parsedSections[idx - 1];
  parsedSections[idx - 1] = tmp;
  renderStructuredEditor();
}

function moveSectionDown(idx) {
  if (idx >= parsedSections.length - 1) return;
  syncSectionsFromDOM();
  var tmp = parsedSections[idx];
  parsedSections[idx] = parsedSections[idx + 1];
  parsedSections[idx + 1] = tmp;
  renderStructuredEditor();
}

function addAC(acContainer) {
  var newAc = {text: '', checked: false, realized_in: []};
  acContainer.appendChild(buildACItem(newAc, acContainer.querySelectorAll('.ac-item').length));
}

// ─── Sync DOM → state ───────────────────────────────────────────

function syncSectionsFromDOM() {
  var container = $('structured-editor');
  if (!container || container.classList.contains('hidden')) return;

  var cards = container.querySelectorAll(':scope > .section-card');
  var updated = [];
  cards.forEach(function(card, idx) {
    if (idx < parsedSections.length) {
      updated.push(_readSectionFromCard(card, parsedSections[idx]));
    }
  });
  parsedSections = updated;
}

function _readSectionFromCard(card, original) {
  var sec = Object.assign({}, original);
  sec.title = card.querySelector('.section-title').value;
  sec.status = card.querySelector('.section-status').value;
  sec.prose_content = card.querySelector('.section-prose').value;

  // Read ACs
  var acItems = card.querySelector('.ac-container').querySelectorAll('.ac-item');
  sec.acceptance_criteria = [];
  acItems.forEach(function(row) {
    var cb = row.querySelector('.ac-check');
    var textEl = row.querySelector('.ac-text');
    var realizedIn = [];
    if (textEl.dataset.realizedIn) {
      try { realizedIn = JSON.parse(textEl.dataset.realizedIn); } catch(e) {}
    }
    sec.acceptance_criteria.push({
      text: textEl.value,
      checked: cb.checked,
      realized_in: realizedIn,
    });
  });

  // Read children
  var childContainer = card.querySelector('.children-container');
  if (childContainer) {
    var childCards = childContainer.querySelectorAll(':scope > .section-card');
    var children = [];
    childCards.forEach(function(cc, ci) {
      var origChild = (sec.children && sec.children[ci]) || {
        id: 'child-' + Date.now() + '-' + ci,
        section_number: null,
        title: '',
        depth: 3,
        content: '',
        prose_content: '',
        status: 'draft',
        acceptance_criteria: [],
        children: [],
        ticket_link: null,
      };
      children.push(_readSectionFromCard(cc, origChild));
    });
    sec.children = children;
  }

  return sec;
}
