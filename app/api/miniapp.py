"""Telegram Mini App — single-page management dashboard.

Served as inline HTML at /mini-app. No build system, vanilla JS.
Authenticated via Telegram initData on every API call.
"""

MINIAPP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Media Manager</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root {
  --bg: #0a0a0a; --card: #1a1a1a; --border: #333; --text: #e0e0e0;
  --accent: #4fc3f7; --green: #66bb6a; --red: #ef5350; --yellow: #ffa726;
  --muted: #888;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); padding: 0; min-height: 100vh; }
.header { padding: 16px; background: var(--card); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px; }
.header h1 { font-size: 18px; color: #fff; flex: 1; }
.header select { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 14px; }
.conn { width: 8px; height: 8px; border-radius: 50%; background: var(--green); }
.conn.off { background: var(--red); }
.tabs { display: flex; background: var(--card); border-bottom: 1px solid var(--border); overflow-x: auto; }
.tab { padding: 12px 16px; color: var(--muted); font-size: 14px; cursor: pointer; white-space: nowrap; border-bottom: 2px solid transparent; }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.content { padding: 16px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 12px; }
.card h3 { color: var(--accent); margin-bottom: 8px; font-size: 15px; }
.card p { color: var(--muted); font-size: 13px; margin: 4px 0; }
.stat { display: inline-block; margin-right: 16px; }
.stat .num { font-size: 20px; font-weight: bold; color: #fff; }
.stat .label { font-size: 11px; color: var(--muted); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
.badge.ok { background: #1b3a1b; color: var(--green); }
.badge.warn { background: #3a2a1b; color: var(--yellow); }
.badge.err { background: #3a1b1b; color: var(--red); }
.btn { display: inline-block; padding: 10px 20px; background: var(--accent); color: #000; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; margin: 4px; }
.btn:active { opacity: 0.7; }
.btn.danger { background: var(--red); color: #fff; }
.btn.secondary { background: var(--border); color: var(--text); }
textarea, input { width: 100%; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-size: 14px; resize: vertical; }
.log-output { font-family: monospace; font-size: 12px; white-space: pre-wrap; background: #111; padding: 12px; border-radius: 8px; max-height: 400px; overflow-y: auto; color: #aaa; }
.empty { text-align: center; padding: 40px; color: var(--muted); }
.actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.hidden { display: none; }
.loading { text-align: center; padding: 20px; color: var(--muted); }
</style>
</head>
<body>

<div class="header">
  <h1>📡 Media Manager</h1>
  <select id="mediaSelect">
    <option value="all">All outlets</option>
    <option value="neromedia">NeroMedia</option>
    <option value="longlife">LongLife</option>
    <option value="pashtelka">Pashtelka</option>
  </select>
  <div class="conn" id="connDot"></div>
</div>

<div class="tabs" id="tabs">
  <div class="tab active" data-tab="status">Status</div>
  <div class="tab" data-tab="articles">Articles</div>
  <div class="tab" data-tab="editor">Editor</div>
  <div class="tab" data-tab="logs">Logs</div>
  <div class="tab" data-tab="agent">Agent</div>
</div>

<div class="content" id="content">
  <div class="loading">Loading...</div>
</div>

<script>
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const initData = tg?.initData || '';
let currentTab = 'status';
let currentMedia = 'all';

// API helper
async function api(path, opts = {}) {
  try {
    const r = await fetch('/api/mini-app' + path, {
      headers: { 'X-Telegram-Init-Data': initData, 'Content-Type': 'application/json', ...opts.headers },
      ...opts,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    document.getElementById('connDot').classList.remove('off');
    return await r.json();
  } catch (e) {
    document.getElementById('connDot').classList.add('off');
    throw e;
  }
}

// Tab switching
document.getElementById('tabs').addEventListener('click', e => {
  if (!e.target.classList.contains('tab')) return;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  e.target.classList.add('active');
  currentTab = e.target.dataset.tab;
  render();
});

document.getElementById('mediaSelect').addEventListener('change', e => {
  currentMedia = e.target.value;
  render();
});

// Renderers
async function render() {
  const c = document.getElementById('content');
  c.innerHTML = '<div class="loading">Loading...</div>';
  try {
    switch (currentTab) {
      case 'status': await renderStatus(c); break;
      case 'articles': await renderArticles(c); break;
      case 'editor': renderEditor(c); break;
      case 'logs': await renderLogs(c); break;
      case 'agent': renderAgent(c); break;
    }
  } catch (e) {
    c.innerHTML = `<div class="card"><p style="color:var(--red)">Error: ${e.message}</p></div>`;
  }
}

async function renderStatus(c) {
  const data = await api('/status');
  let html = '';
  for (const [slug, info] of Object.entries(data)) {
    if (currentMedia !== 'all' && slug !== currentMedia) continue;
    const healthBadge = info.last_run ? '<span class="badge ok">Active</span>' : '<span class="badge warn">No runs</span>';
    html += `<div class="card">
      <h3>${info.name} ${healthBadge}</h3>
      <div style="display:flex;gap:24px;margin:12px 0">
        <div class="stat"><div class="num">${info.articles_today}</div><div class="label">Articles today</div></div>
        <div class="stat"><div class="num">${info.tg_posts_today || 0}</div><div class="label">TG posts</div></div>
      </div>
      <p>🕐 Last run: ${info.last_run || 'never'}</p>
      <p>🌐 <a href="${info.site_url}" style="color:var(--accent)">${info.site_url}</a></p>
      <p>📱 @${info.tg_channel}</p>
      <div class="actions">
        <button class="btn" onclick="triggerAction('${slug}','generate')">Generate</button>
        <button class="btn secondary" onclick="triggerAction('${slug}','publish')">Publish</button>
        <button class="btn secondary" onclick="triggerAction('${slug}','digest')">Digest</button>
      </div>
    </div>`;
  }
  c.innerHTML = html || '<div class="empty">No outlets found</div>';
}

async function renderArticles(c) {
  const media = currentMedia === 'all' ? 'pashtelka' : currentMedia;
  const data = await api(`/articles/${media}`);
  if (!data.articles?.length) { c.innerHTML = '<div class="empty">No articles today</div>'; return; }
  let html = `<div class="card"><h3>${data.name} — Today's Articles</h3></div>`;
  for (const a of data.articles) {
    html += `<div class="card"><h3>${a.title}</h3><p>${a.type} · ${a.date}</p></div>`;
  }
  c.innerHTML = html;
}

function renderEditor(c) {
  c.innerHTML = `<div class="card">
    <h3>📝 Editorial Note</h3>
    <p style="margin-bottom:12px">Send a note to the editorial pipeline. Will be prioritized in the next content run.</p>
    <select id="noteMedia" style="margin-bottom:8px">
      <option value="all">All outlets</option>
      <option value="neromedia">NeroMedia</option>
      <option value="longlife">LongLife</option>
      <option value="pashtelka">Pashtelka</option>
    </select>
    <textarea id="noteText" rows="4" placeholder="Your editorial note..."></textarea>
    <div class="actions"><button class="btn" onclick="sendNote()">Send Note</button></div>
    <div id="noteResult" style="margin-top:8px"></div>
  </div>`;
}

async function renderLogs(c) {
  const media = currentMedia === 'all' ? 'pashtelka' : currentMedia;
  const data = await api(`/logs/${media}`);
  c.innerHTML = `<div class="card"><h3>${data.name} — Pipeline Logs</h3></div><div class="log-output">${escHtml(data.logs || 'No logs')}</div>`;
}

function renderAgent(c) {
  c.innerHTML = `<div class="card">
    <h3>🤖 Agent</h3>
    <p style="margin-bottom:12px">Ask the AI agent about the media system.</p>
    <input id="agentInput" type="text" placeholder="Ask a question..." />
    <div class="actions">
      <button class="btn" onclick="agentAsk()">Ask</button>
      <button class="btn secondary" onclick="agentAnalyze()">Analyze</button>
    </div>
    <div id="agentResult" style="margin-top:12px"></div>
  </div>`;
}

// Actions
async function triggerAction(media, mode) {
  if (!confirm(\`Trigger \${mode} for \${media}?\`)) return;
  try {
    const r = await api(\`/trigger/\${media}/\${mode}\`, { method: 'POST' });
    tg?.showAlert?.(\`\${mode} queued for \${media}\`) || alert(\`\${mode} queued\`);
  } catch (e) {
    tg?.showAlert?.(\`Error: \${e.message}\`) || alert(e.message);
  }
}

async function sendNote() {
  const media = document.getElementById('noteMedia').value;
  const text = document.getElementById('noteText').value.trim();
  if (!text) return;
  const el = document.getElementById('noteResult');
  try {
    const r = await api('/note', { method: 'POST', body: JSON.stringify({ media, text }) });
    el.innerHTML = '<span style="color:var(--green)">✅ Note saved</span>';
    document.getElementById('noteText').value = '';
  } catch (e) {
    el.innerHTML = `<span style="color:var(--red)">❌ ${e.message}</span>`;
  }
}

async function agentAsk() {
  const q = document.getElementById('agentInput').value.trim();
  if (!q) return;
  const el = document.getElementById('agentResult');
  el.innerHTML = '<div class="loading">🤖 Thinking...</div>';
  try {
    const r = await api('/agent/ask', { method: 'POST', body: JSON.stringify({ question: q, media: currentMedia }) });
    el.innerHTML = `<div class="card">${escHtml(r.result || r.error || 'No response')}</div>`;
  } catch (e) {
    el.innerHTML = `<div class="card" style="border-color:var(--red)">❌ ${e.message}</div>`;
  }
}

async function agentAnalyze() {
  const media = currentMedia === 'all' ? 'pashtelka' : currentMedia;
  const el = document.getElementById('agentResult');
  el.innerHTML = '<div class="loading">🔍 Analyzing...</div>';
  try {
    const r = await api(`/agent/analyze/${media}`, { method: 'POST' });
    const d = r.result || {};
    el.innerHTML = `<div class="card">
      <h3>Analysis: ${media}</h3>
      <p>📰 Total: ${d.total_articles || '?'} | Today: ${d.articles_today || '?'}</p>
      <p>Quality: ${d.content_quality || '?'} | Pipeline: ${d.pipeline_health || '?'}</p>
      ${d.recommendations ? '<p><b>Recommendations:</b></p>' + d.recommendations.map((r,i) => `<p>${i+1}. ${r}</p>`).join('') : ''}
    </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card" style="border-color:var(--red)">❌ ${e.message}</div>`;
  }
}

function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// Init
render();
</script>
</body>
</html>"""


def get_miniapp_html() -> str:
    """Return the Mini App HTML."""
    return MINIAPP_HTML
