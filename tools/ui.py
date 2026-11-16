"""本地网页界面：填邮件正文 → 调 AgentCore Runtime → 看报价。

只用标准库（http.server + urllib），不需要装任何依赖。
启动：python tools/ui.py   然后打开 http://127.0.0.1:8765

环境变量：
    RUNTIME_ARN  默认指向本项目部署的 runtime
    AWS_PROFILE  默认 aws
    AWS_REGION   默认 ap-southeast-2
    UI_PORT      默认 8765
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlparse

RUNTIME_ARN = os.environ.get(
    "RUNTIME_ARN",
    "arn:aws:bedrock-agentcore:ap-southeast-2:187133147869:runtime/quotation_agent-oPugo6Dgui",
)
GATEWAY_URL = os.environ.get(
    "GATEWAY_URL",
    "https://quotation-agent-gw-boa2n2neqb.gateway.bedrock-agentcore.ap-southeast-2.amazonaws.com/mcp",
)
REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
PROFILE = os.environ.get("AWS_PROFILE", "aws")

# 演示页用：日志组与公开单价（2026-11 官方定价页）
LAMBDA_FUNCTION = os.environ.get("LAMBDA_FUNCTION", "quotation-agent-tools")
RUNTIME_LOG_GROUP = os.environ.get(
    "RUNTIME_LOG_GROUP",
    "/aws/bedrock-agentcore/runtimes/quotation_agent-oPugo6Dgui-DEFAULT",
)
LAMBDA_LOG_GROUP = os.environ.get("LAMBDA_LOG_GROUP", f"/aws/lambda/{LAMBDA_FUNCTION}")

RATE = {
    "memory_per_event": 0.00025,     # $0.25 / 1k events
    "model_in_per_mtok": 0.27,       # DeepSeek input, $/M tokens
    "model_out_per_mtok": 1.10,      # DeepSeek output, $/M tokens
    "runtime_vcpu_hour": 0.0895,     # $/vCPU-hour
    "runtime_gb_hour": 0.00945,      # $/GB-hour
    "lambda_gb_second": 0.0000166667,
    "lambda_memory_gb": 0.5,
}

# 一次典型报价的用量（来自实测：3 附件 + 1 次模型兜底）
USAGE = {
    "memory_events": 3,
    "model_in_tokens": 900,
    "model_out_tokens": 250,
    "runtime_seconds": 8.7,
    "runtime_vcpu": 1.0,
    "runtime_gb": 2.0,
    "lambda_seconds": 8.0,      # 解析那一次
    "render_calls": 3,          # PDF / 复核 / 回信
    "render_seconds": 0.5,
    "s3_ops": 5,                # 3 写 2 读
}

LAST_QUOTE: dict = {}
NAV = """<div style="display:flex;gap:16px;align-items:center;font-size:12.5px;padding:10px 34px;background:#0f2b46;color:#cfe0f0">
  <b style="color:#fff;font-size:13px">Quotation agent</b>
  <a href="/" style="color:#cfe0f0;text-decoration:none">Workbench</a>
  <a href="/inbox" style="color:#cfe0f0;text-decoration:none">Inbox</a>
  <a href="/approvals" style="color:#cfe0f0;text-decoration:none">Approvals</a>
  <a href="/prices" style="color:#cfe0f0;text-decoration:none">Prices</a>
  <a href="/cost" style="color:#cfe0f0;text-decoration:none">Cost</a>
  <a href="/traces" style="color:#cfe0f0;text-decoration:none">Traces</a>
  <a href="/assumptions" style="color:#cfe0f0;text-decoration:none">Assumptions</a>
</div>"""

TRACE_HISTORY: list = []

PORT = int(os.environ.get("UI_PORT", "8765"))

DRAWER_JS = """function drawerEl(id) {
  return document.getElementById(id);
}

function renderOriginal(file) {
  const original = file.original || {};
  const kind = original.kind;

  if (kind === 'pdf') {
    return file.url
      ? '<iframe src="' + esc(file.url) + '#view=FitH" style="width:100%;height:64vh;border:1px solid #e3e6ea;border-radius:8px"></iframe>'
      : '<div class="warn">No link for this PDF.</div>';
  }

  if (kind === 'sheet') {
    let html = '';
    for (const sheet of original.sheets || []) {
      const width = Math.max(...sheet.rows.map(r => r.length));
      html += '<h2>' + esc(sheet.name) + ' <span class="muted">(' + sheet.rows.length + ' rows)</span></h2>' +
              '<div style="overflow:auto;max-height:58vh;border:1px solid #e3e6ea;border-radius:8px">' +
              '<table style="font-size:11.5px"><tr><th style="width:34px;background:#f4f7fb">#</th>';
      for (let c = 0; c < width; c++) html += '<th style="background:#f4f7fb">' + String.fromCharCode(65 + (c % 26)) + '</th>';
      html += '</tr>';
      sheet.rows.forEach((row, i) => {
        html += '<tr><td class="muted" style="background:#fafbfc">' + (i + 1) + '</td>';
        for (let c = 0; c < width; c++) html += '<td>' + esc(row[c] || '') + '</td>';
        html += '</tr>';
      });
      html += '</table></div>';
    }
    return html || '<p class="muted">Empty workbook.</p>';
  }

  if (kind === 'slides') {
    let html = '';
    for (const slide of original.slides || []) {
      html += '<div style="border:1px solid #e3e6ea;border-radius:8px;padding:10px 12px;margin-bottom:10px">' +
              '<div class="muted">Slide ' + slide.index + '</div>';
      for (const t of slide.texts || []) html += '<p style="margin:6px 0;font-size:13px">' + esc(t) + '</p>';
      for (const table of slide.tables || []) {
        html += '<table style="margin-top:6px;font-size:12px">';
        table.forEach((row, i) => {
          html += '<tr>' + row.map(cell => (i === 0 ? '<th>' : '<td>') + esc(cell) + (i === 0 ? '</th>' : '</td>')).join('') + '</tr>';
        });
        html += '</table>';
      }
      html += '</div>';
    }
    return html || '<p class="muted">No text on these slides.</p>';
  }

  if (kind === 'doc') {
    let html = '';
    for (const p of original.paragraphs || []) html += '<p style="margin:6px 0;font-size:13px">' + esc(p) + '</p>';
    for (const table of original.tables || []) {
      html += '<table style="margin-top:8px;font-size:12px">';
      table.forEach((row, i) => {
        html += '<tr>' + row.map(cell => (i === 0 ? '<th>' : '<td>') + esc(cell) + (i === 0 ? '</th>' : '</td>')).join('') + '</tr>';
      });
      html += '</table>';
    }
    return html || '<p class="muted">Empty document.</p>';
  }

  if (kind === 'unsupported' && original.error) {
    return '<div class="warn">' + esc(original.error) + '</div>';
  }

  return file.text ? '<pre>' + esc(file.text) + '</pre>' : '<p class="muted">No preview for this file type.</p>';
}

function openDrawer(index) {
  const file = SOURCES[index];
  if (!file) return;

  const titleEl = drawerEl('drawer-title');
  const bodyEl = drawerEl('drawer-body');
  const panel = drawerEl('drawer');
  if (!titleEl || !bodyEl || !panel) return;

  titleEl.textContent = file.filename;

  let html = '';
  if (file.url) {
    html += '<p><a href="' + esc(file.url) + '" target="_blank">Download the original &nearr;</a> ' +
            '<span class="muted">(presigned, 1 hour)</span></p>';
  }
  html += renderOriginal(file);
  html += '<details style="margin-top:14px"><summary style="cursor:pointer;font-size:12px;color:#5b6b7c">Show what the parser extracted</summary>';
  html += file.text ? '<pre style="margin-top:8px">' + esc(file.text) + '</pre>' : '<p class="muted" style="margin-top:8px">No text extracted.</p>';
  html += '</details>';

  bodyEl.innerHTML = html;
  panel.classList.add('open');
}

(function bindDrawerClose() {
  const closeBtn = drawerEl('drawer-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      const panel = drawerEl('drawer');
      if (panel) panel.classList.remove('open');
    });
  }
})();"""




PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Quotation Agent</title>
<style>
  :root { color-scheme: light; }
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0; background: #f6f7f9; color: #1a1a1a; }
  header { background: #0f2b46; color: #fff; padding: 14px 22px; font-size: 15px; letter-spacing: .2px; }
  main { display: grid; grid-template-columns: 420px 1fr; gap: 18px; padding: 18px; align-items: start; }
  .card { background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 16px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: #5b6b7c; margin: 0 0 10px; }
  label { display: block; font-size: 12px; color: #5b6b7c; margin: 10px 0 4px; }
  input, textarea { width: 100%; box-sizing: border-box; border: 1px solid #cfd6dd; border-radius: 7px; padding: 8px 9px; font: inherit; font-size: 13px; }
  select { max-width: 100%; box-sizing: border-box; }
  #email { min-width: 0; text-overflow: ellipsis; }
  textarea { min-height: 230px; resize: vertical; line-height: 1.5; }
  button { margin-top: 14px; width: 100%; padding: 10px; border: 0; border-radius: 8px; background: #1266f1; color: #fff; font-size: 14px; cursor: pointer; }
  button.ghost { margin-top: 0; background: #eef2f7; color: #1a1a1a; font-size: 13px; }
  button.ghost:disabled { background: #f2f4f7; color: #a9b4c0; cursor: default; }
  #go-both { margin-top: 0; }
  button:disabled { background: #9db8e8; cursor: default; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid #eef1f4; }
  th { font-size: 11px; text-transform: uppercase; color: #6b7a89; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .total { font-size: 20px; font-weight: 600; margin: 12px 0 4px; }
  .muted { color: #6b7a89; font-size: 12px; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 11px; background: #eef4ff; color: #1266f1; margin-right: 6px; }
  .warn { background: #fff8e6; border: 1px solid #f3dfa8; border-radius: 8px; padding: 9px 11px; font-size: 12px; margin-bottom: 10px; }
  pre { white-space: pre-wrap; font-size: 12.5px; line-height: 1.55; background: #f8fafc; border: 1px solid #eef1f4; border-radius: 8px; padding: 12px; margin: 0; }
  a { color: #1266f1; }
  .hidden { display: none; }
  #drawer { position: fixed; top: 0; right: 0; width: 62vw; min-width: 520px; max-width: 96vw; height: 100vh; background: #fff;
            border-left: 1px solid #e3e6ea; box-shadow: -8px 0 24px rgba(20,40,70,.12); transform: translateX(100%);
            transition: transform .18s ease; display: flex; flex-direction: column; z-index: 20; }
  #drawer.open { transform: translateX(0); }
  #drawer header { background: #0f2b46; color: #fff; padding: 12px 16px; font-size: 13px; display: flex; justify-content: space-between; align-items: center; }
  #drawer header button { width: auto; margin: 0; padding: 2px 8px; background: transparent; border: 1px solid rgba(255,255,255,.35); color: #fff; font-size: 12px; }
  #drawer .body { padding: 14px 16px; overflow: auto; }
  #drawer pre { max-height: none; }
</style>
</head>
<body>{{NAV}}
<header style="display:flex;justify-content:space-between;align-items:center">
  <span>Quotation Agent &middot; AgentCore Runtime</span>
  <nav style="font-size:13px">
    <a href="/" style="color:#fff;font-weight:600;text-decoration:none">Quotation</a>
    <a href="/inbox" style="color:#cfe0f5;text-decoration:none;margin-left:18px">Inbox</a>
    <a href="/approvals" style="color:#cfe0f5;text-decoration:none;margin-left:18px">Approvals</a>
    <a href="/prices" style="color:#cfe0f5;text-decoration:none;margin-left:18px">Prices</a>
  </nav>
</header>
<main>
  <section class="card">
    <h2>Request</h2>
    <label>Filter</label>
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px">
      <select id="fdomain" style="padding:7px; border:1px solid #cfd6dd; border-radius:7px; font-size:12.5px">
        <option value="">All companies</option>
      </select>
      <select id="fcontact" style="padding:7px; border:1px solid #cfd6dd; border-radius:7px; font-size:12.5px">
        <option value="">All contacts</option>
      </select>
    </div>
    <input id="fsearch" placeholder="Search subject or file name" style="margin-top:8px">

    <label>Email</label>
    <div style="display:flex; gap:8px">
      <select id="email" style="flex:1; padding:8px; border:1px solid #cfd6dd; border-radius:7px; font-size:13px">
        <option value="">— loading —</option>
      </select>
      <button id="refresh" style="width:auto; margin:0; padding:0 12px; background:#eef2f7; color:#1a1a1a; font-size:13px">↻</button>
    </div>
    <p class="muted" id="emailmeta"></p>
    <div id="attlist" style="margin:4px 0 12px"></div>

    <div style="border:1px solid #e3e6ea;border-radius:8px;padding:10px 12px;margin-bottom:10px">
      <div class="muted" style="font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">What to read</div>
      <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:4px">
        <input type="checkbox" id="inc-body" checked style="width:auto;margin:0"> Email body
      </label>
      <div id="inc-attach" style="display:flex;flex-direction:column;gap:4px"></div>
    </div>
    <button id="go">Generate quotation</button>
    <p class="muted" id="status"></p>
  </section>

  <section class="card">
    <h2>Quotation</h2>
    <div id="out"><p class="muted">Nothing yet — pick an email and click a button.</p></div>
  </section>
</main>

<aside id="drawer">
  <header><span id="drawer-title">Attachment</span><button id="drawer-close">Close</button></header>
  <div class="body" id="drawer-body"></div>
</aside>
<script>
const go = document.getElementById('go');
const incAttach = document.getElementById('inc-attach');
const status = document.getElementById('status');
const out = document.getElementById('out');
const select = document.getElementById('email');
const emailMeta = document.getElementById('emailmeta');
const attList = document.getElementById('attlist');
const refresh = document.getElementById('refresh');
const fdomain = document.getElementById('fdomain');
const fcontact = document.getElementById('fcontact');
const fsearch = document.getElementById('fsearch');

const esc = (s) => String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const money = (n) => Number(n).toLocaleString('en-MY', {minimumFractionDigits: 2, maximumFractionDigits: 2});

let cache = [];
let companies = [];
let CURRENT_QUOTE = null;
let CURRENT_DISCOUNT = 0;

async function loadEmails() {
  select.innerHTML = '<option value="">— loading —</option>';
  try {
    const res = await fetch('/api/emails');
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    cache = data.emails || [];
    companies = data.companies || [];
    buildCompanyFilter();
    applyFilters();
  } catch (err) {
    select.innerHTML = '<option value="">— failed to load —</option>';
    emailMeta.textContent = err.message;
  }
}

function buildCompanyFilter() {
  const current = fdomain.value;
  fdomain.innerHTML = '<option value="">All companies (' + cache.length + ')</option>' +
    companies.map(c => '<option value="' + esc(c.domain) + '">' + esc(c.domain) + ' (' + c.count + ')</option>').join('');
  if (current && companies.some(c => c.domain === current)) fdomain.value = current;
}

function contactsFor(domain) {
  const set = new Set();
  cache.filter(e => !domain || e.domain === domain).forEach(e => { if (e.contact) set.add(e.contact); });
  return [...set].sort();
}

function applyFilters() {
  const domain = fdomain.value;
  const contact = fcontact.value;
  const needle = (fsearch.value || '').toLowerCase();

  const contacts = contactsFor(domain);
  fcontact.innerHTML = '<option value="">All contacts</option>' +
    contacts.map(c => '<option value="' + esc(c) + '">' + esc(c) + '</option>').join('');
  if (contact && contacts.includes(contact)) fcontact.value = contact;

  const visible = cache.filter(e =>
    (!domain || e.domain === domain) &&
    (!fcontact.value || e.contact === fcontact.value) &&
    (!needle || (e.subject || '').toLowerCase().includes(needle) || (e.name || '').toLowerCase().includes(needle))
  );

  if (!visible.length) {
    select.innerHTML = '<option value="">(no email matches the filter)</option>';
    showMeta();
    return;
  }
  const keep = select.value;
  select.innerHTML = visible.map(e =>
    '<option value="' + esc(e.key) + '">' + esc(e.subject || e.name) + '  ·  ' + esc(e.contact || '') + '</option>'
  ).join('');
  if (visible.some(e => e.key === keep)) select.value = keep;
  showMeta();
}

function showMeta() {
  const item = cache.find(e => e.key === select.value);
  if (!item) {
    emailMeta.textContent = '';
    attList.innerHTML = '';
    incAttach.innerHTML = '';
    return;
  }
  emailMeta.textContent = item.from + ' · ' + Math.round(item.size / 1024) + ' KB · ' + item.modified.replace('T', ' ');
  const files = item.attachments || [];
  attList.innerHTML = files.length
    ? files.map(f => '<span class="pill" style="background:#e8f2e8;color:#2f6b34">📎 ' + esc(f) + '</span>').join('')
    : '<span class="muted">No attachments — only the body path is available.</span>';

  // 勾选列表：正文 + 每个附件（默认全选）
  incAttach.innerHTML = files.length
    ? files.map((f, i) =>
        '<label style="display:flex;align-items:center;gap:8px;font-size:13px">' +
        '<input type="checkbox" class="inc-file" data-name="' + esc(f) + '" checked style="width:auto;margin:0"> ' +
        esc(f) + '</label>').join('')
    : '<span class="muted" style="font-size:11.5px">This email has no attachments.</span>';
}

select.addEventListener('change', showMeta);
refresh.addEventListener('click', loadEmails);
fdomain.addEventListener('change', applyFilters);
fcontact.addEventListener('change', applyFilters);
fsearch.addEventListener('input', applyFilters);

const PRESELECT = new URLSearchParams(location.search).get('key');
loadEmails().then(() => {
  if (!PRESELECT) return;
  select.value = PRESELECT;
  showMeta();
  if (select.value === PRESELECT) run();
});

async function run() {
  const key = select.value;
  if (!key) { out.innerHTML = '<div class="warn">Pick an email first.</div>'; return; }

  const includeBody = document.getElementById('inc-body').checked;
  const includeAttachments = Array.from(document.querySelectorAll('.inc-file'))
    .filter((box) => box.checked)
    .map((box) => box.dataset.name);

  if (!includeBody && !includeAttachments.length) {
    out.innerHTML = '<div class="warn">Tick the email body, at least one attachment, or both.</div>';
    return;
  }

  const summary = [includeBody ? 'body' : null]
    .concat(includeAttachments.length ? [includeAttachments.length + ' attachment(s)'] : [])
    .filter(Boolean).join(' + ');

  out.innerHTML = '<p class="muted">Working…</p>';
  status.textContent = 'Reading ' + summary + '…';
  go.disabled = true;
  try {
    const res = await fetch('/api/quote', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email_key: key, include_body: includeBody, include_attachments: includeAttachments}),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    render(data);
    status.textContent = 'Read ' + summary + ' · done in ' + (data.elapsed_ms / 1000).toFixed(1) + 's';
    if (includeAttachments.length) loadSources(key);
  } catch (err) {
    out.innerHTML = '<div class="warn">' + esc(err.message) + '</div>';
    status.textContent = '';
  } finally {
    go.disabled = false;
  }
}

go.addEventListener('click', run);

async function loadSources(key) {
  const box = document.getElementById('sources');
  if (!box) return;
  box.innerHTML = '<h2 style="margin-top:20px">Attachment contents</h2><p class="muted">Parsing…</p>';
  try {
    const res = await fetch('/api/attachments?key=' + encodeURIComponent(key));
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const files = data.attachments || [];
    if (!files.length) { box.innerHTML = ''; return; }
    SOURCES = files;

    let html = '<h2 style="margin-top:20px">Attachment contents</h2>';
    files.forEach((file, index) => {
      html += '<div style="border:1px solid #e3e6ea;border-radius:8px;padding:10px 12px;margin-bottom:10px">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">' +
              '<div><b>📎 ' + esc(file.filename) + '</b> <span class="muted">· ' + file.row_count + ' row(s)</span></div>' +
              '<div style="display:flex;gap:6px">' +
              '<button class="ghost" style="width:auto;padding:4px 10px" onclick="openDrawer(' + index + ')">View original</button>' +
              (file.url ? '<a class="ghost" style="width:auto;padding:4px 10px;text-decoration:none;border-radius:8px;background:#eef2f7;color:#1a1a1a" href="' + esc(file.url) + '" target="_blank">Download ↗</a>' : '') +
              '</div></div>';
      if (!file.ok) {
        html += '<div class="warn" style="margin-top:8px">' + esc(file.error) + '</div></div>';
        return;
      }
      if ((file.warnings || []).length) {
        html += '<div class="muted" style="margin-top:4px">' + file.warnings.map(esc).join(' · ') + '</div>';
      }
      if ((file.rows || []).length) {
        html += '<table style="margin-top:8px"><tr><th style="width:130px">Source</th><th>Values parsed</th></tr>';
        for (const row of file.rows) {
          const parts = Object.entries(row.values).filter(([k, v]) => v !== '' && v !== null && v !== undefined)
            .map(([k, v]) => '<span class="muted">' + esc(k) + '</span> ' + esc(v)).join(' &nbsp;·&nbsp; ');
          html += '<tr><td><code style="font-size:11px">' + esc(row.locator) + '</code></td><td style="font-size:12px">' + parts + '</td></tr>';
        }
        html += '</table>';
      } else {
        html += '<div class="muted" style="margin-top:6px">No table rows found — use View content for the raw text.</div>';
      }
      html += '</div>';
    });
    box.innerHTML = html;
  } catch (err) {
    box.innerHTML = '<h2 style="margin-top:20px">Attachment contents</h2><div class="warn">' + esc(err.message) + '</div>';
  }
}

let SOURCES = [];

""" + DRAWER_JS + """

function render(data) {
  const q = data.quote || {};
  CURRENT_QUOTE = q;
  let html = '';

  const src = q.source || {};
  if (src.subject || src.email_key) {
    html += '<div style="background:#f4f7fb;border:1px solid #e3ecf7;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:12.5px">' +
            '<div><b>' + esc(src.subject || '(no subject)') + '</b></div>' +
            '<div class="muted">From ' + esc(src.from || '—') + ' · ' + esc(src.email_key || '') + '</div>';
    const files = src.attachments || [];
    if (files.length) {
      html += '<div style="margin-top:6px">' + files.map(f =>
        '<span class="pill" style="background:#e8f2e8;color:#2f6b34">📎 ' + esc(f) + '</span>').join('') + '</div>';
    } else {
      html += '<div class="muted" style="margin-top:6px">No attachments in this email.</div>';
    }
    html += '</div>';
  }

  if (q.error) {
    out.innerHTML = '<div class="warn">' + esc(q.error) + '</div>';
    return;
  }

  if ((q.warnings || []).length) {
    html += '<div class="warn">' + q.warnings.map(esc).join('<br>') + '</div>';
  }

  const usage = q.model_usage || null;
  if (usage) {
    const purposes = Object.entries(usage.by_purpose || {})
      .map(([name, count]) => name + ' ×' + count).join(', ');
    html += '<p class="muted" style="margin:6px 0 0">Model calls this quote: <b>' + (usage.calls || 0) + '</b>' +
            (purposes ? ' (' + esc(purposes) + ')' : ' — pricing and parsing were fully deterministic') + '</p>';
  }

  if ((q.lines || []).length) {
    html += '<table><tr><th>Part</th><th>Material</th><th class="num">Qty</th>' +
            '<th class="num">Cost</th><th class="num">Unit</th><th class="num">Line total</th>' +
            '<th class="num" title="How much we trust the quantity / material / tolerance of this line">Confidence</th><th></th></tr>';
    q.lines.forEach((l, i) => {
      const label = l.confidence_label || 'high';
      const colour = label === 'high' ? 'background:#e8f2e8;color:#2f6b34'
                   : label === 'medium' ? 'background:#fff6e0;color:#8a6100'
                   : 'background:#fdeaea;color:#a12a2a';
      const title = (l.flags || []).join('; ') || 'sources agree';
      html += '<tr data-part="' + esc(l.part_no) + '"><td>' + esc(l.part_no) + '</td>' +
              '<td>' + esc(l.material) + '</td>' +
              '<td class="num">' + esc(l.qty) + '</td>' +
              '<td class="num">' + money(l.unit_cost) + '</td>' +
              '<td class="num unit">' + money(l.unit_price) + '</td>' +
              '<td class="num line-total">' + money(l.line_total) + '</td>' +
              '<td class="num"><span class="pill" style="' + colour + '" title="' + esc(title) + '">' +
              (l.confidence !== undefined ? Number(l.confidence).toFixed(2) + ' ' : '') + label + '</span></td>' +
              '<td style="white-space:nowrap"><a href="#" class="trace-link" data-i="' + i + '" style="font-size:11px">how?</a>' +
              ' · <a href="#" class="why-link" data-i="' + i + '" style="font-size:11px">why?</a></td></tr>';
      const sources = l.field_sources || {};
      const values = l.field_values || {};
      const FIELD_LABELS = { material: 'material', qty: 'quantity', tolerance: 'tolerance',
                             mass: 'mass', cycle: 'cycle time', finish: 'finish',
                             description: 'description' };
      const byOf = (origin) => {
        if (!origin) return { label: '—', colour: '#6b7a89' };
        if (origin.indexOf('llm line') >= 0 || /\bllm\b/.test(origin)) return { label: 'MODEL', colour: '#8a6100' };
        if (origin.indexOf('ocr') >= 0) return { label: 'OCR', colour: '#1f5f8b' };
        return { label: 'RULES', colour: '#2f6b34' };
      };
      const provenance = Object.keys(FIELD_LABELS).filter((key) => values[key] !== null && values[key] !== '' && values[key] !== undefined);
      const provenanceRows = provenance.map((key) => {
        const by = byOf(sources[key]);
        const badge = '<span class="pill" style="background:' + (by.label === 'MODEL' ? '#fdf1d8' : by.label === 'OCR' ? '#e6f0f8' : '#e8f2e8') +
                      ';color:' + by.colour + '">' + by.label + '</span>';
        return '<tr><td style="width:92px">' + esc(FIELD_LABELS[key]) + '</td>' +
               '<td style="max-width:180px;overflow:hidden;text-overflow:ellipsis">' + esc(String(values[key])) + '</td>' +
               '<td>' + badge + '</td>' +
               '<td class="muted" style="max-width:260px;overflow:hidden;text-overflow:ellipsis">' + esc(sources[key] || 'derived') + '</td></tr>';
      }).join('');

      const td = l.trace_data || [];
      const pick = (prefix) => td.filter((t) => (t.rule || '').indexOf(prefix) === 0);
      const componentRows = td.filter((t) => /^[MRFS]-/.test(t.rule || ''));
      const costRow = td.find((t) => t.rule === 'COST') || {};
      const marginRow = td.find((t) => (t.rule || '').indexOf('P-MARGIN') === 0) || {};
      const tierRow = td.find((t) => (t.rule || '').indexOf('D-QTY') === 0) || {};
      const left = (text) => String(text || '').split(' = ')[0];

      let formulaHtml = '';
      if (componentRows.length && costRow.amount !== undefined) {
        const sum = componentRows.map((t) => left(t.detail)).join(' + ');
        formulaHtml =
          '<div style="font-size:12px;line-height:1.7;font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap;color:#14212e">' +
          esc(sum) + ' = <b>' + esc(String(costRow.amount)) + '</b> unit cost' +
          (marginRow.detail ? '<br>' + esc(marginRow.detail) : '') +
          (tierRow.detail ? '<br>' + esc(tierRow.detail) : '') +
          '<br>' + esc(money(l.unit_price)) + ' × ' + esc(String(l.qty)) + ' pcs = <b>' + esc(money(l.line_total)) + '</b>' +
          '</div>';
      } else {
        formulaHtml = '<div style="font-size:12px;font-family:ui-monospace,Consolas,monospace">' +
                      esc((l.trace || []).join(' → ')) + '</div>';
      }

      const modelLines = (l.trace || []).filter((row) => /\bllm\b/.test(row));
      const stepsHtml = (l.trace || []).map((row) => {
        const isModel = /\bllm\b/.test(row);
        return '<div' + (isModel ? ' style="background:#fdf1d8;margin:0 -6px;padding:0 6px"' : '') + '>' +
               (isModel ? '▶ ' : '') + esc(row) + '</div>';
      }).join('');

      html += '<tr id="trace-' + i + '" style="display:none"><td colspan="8" style="background:#f8fafc">' +
              '<div style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#6b7a89;margin-bottom:4px">How this price was calculated</div>' +
              formulaHtml +
              '<div style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#6b7a89;margin:10px 0 4px">Where each field came from</div>' +
              '<table style="font-size:11.5px;max-width:760px">' +
              '<tr><th>Field</th><th>Value</th><th>Read by</th><th>Source</th></tr>' + provenanceRows + '</table>' +
              '<details style="margin-top:8px"><summary style="cursor:pointer;font-size:11px;color:#5b6b7c">' +
              'Show the eight steps with rule ids' + (modelLines.length ? ' (▶ = produced by the model)' : '') +
              '</summary><div style="font-size:11.5px;line-height:1.6;font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap;margin-top:6px">' +
              stepsHtml + '</div></details>' +
              '</td></tr>';
      const fc = l.field_confidence || {};
      const fieldRows = Object.entries(fc).map(([field, score]) => {
        const by = byOf(sources[field]);
        return '<tr><td style="width:110px">' + esc(field) + '</td><td class="num">' + Number(score).toFixed(2) + '</td>' +
               '<td><span class="pill" style="background:' + (by.label === 'MODEL' ? '#fdf1d8' : '#e8f2e8') + ';color:' + by.colour + '">' + by.label + '</span></td></tr>';
      }).join('');

      const notes = (q.conflict_notes || [])
        .map((n) => ({ field: n.part_no + '.' + n.field, preferred: (n.suggestion || {}).preferred, reason: (n.suggestion || {}).reason }))
        .filter((n) => n.preferred);
      const notesHtml = notes.length
        ? '<div style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#8a6100;margin:8px 0 4px">Model judgement on the conflict (advisory only)</div>' +
          notes.map((n) => '<div style="font-size:11.5px;color:#3d4a56;line-height:1.55;margin-bottom:6px">' +
            '<span class="muted">' + esc(n.field) + ' → </span><b>' + esc(n.preferred) + '</b><br>' + esc(n.reason || '') + '</div>').join('')
        : '';
      const modelFields = Object.keys(sources).filter((key) => /\bllm\b/.test(sources[key] || ''));

      html += '<tr id="why-' + i + '" style="display:none"><td colspan="8" style="background:#fbf7ef">' +
              '<div style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#8a6100;margin-bottom:4px">Why this confidence</div>' +
              '<table style="font-size:11.5px;max-width:520px">' +
              '<tr><th>Field</th><th class="num">Score</th><th>Read by</th></tr>' + fieldRows + '</table>' +
              notesHtml +
              (modelFields.length ? '<div style="font-size:11.5px;color:#8a6100;margin-top:6px">Fields the model filled: ' +
                 esc(modelFields.join(', ')) + ' — scored at the model weight (0.45), never above the document it came from.</div>' : '') +
              '<div style="font-size:11.5px;color:#3d4a56;margin-top:6px">Line score = lowest of these = <b>' +
              (l.confidence !== undefined ? Number(l.confidence).toFixed(2) : '—') + '</b>' +
              (((l.flags || []).length) ? ' · needs a look: <span style="color:#a12a2a">' + esc((l.flags || []).join('; ')) + '</span>' : '') +
              '</div></td></tr>';
    });
    html += '</table>';
    html += '<details style="margin-top:8px"><summary style="cursor:pointer;font-size:11.5px;color:#5b6b7c">' +
            'How confidence is scored</summary>' +
            '<div style="font-size:11.5px;line-height:1.7;margin-top:6px;color:#3d4a56">' +
            'Each field (quantity, material, tolerance) is scored by where it came from: ' +
            '<b>xlsx / pptx / docx 0.90</b> · <b>PDF 0.70</b> · <b>email body 0.60</b> · <b>model-extracted 0.45</b>. ' +
            'Several sources that agree add +0.05 each (cap 0.99); sources that disagree score 0.30 and are listed as a conflict; ' +
            'a missing value scores 0.40. The line score is the <b>lowest of the three</b>: ' +
            '<span class="pill" style="background:#e8f2e8;color:#2f6b34">high ≥ 0.85</span> ' +
            '<span class="pill" style="background:#fff6e0;color:#8a6100">medium 0.55–0.85</span> ' +
            '<span class="pill" style="background:#fdeaea;color:#a12a2a">low &lt; 0.55 → needs a person</span>' +
            '</div></details>';
    html += '<div class="total" id="quote-total">MYR ' + money(q.total) + '</div>';
    html += '<p class="muted">Valid 30 days. Cost comes from material, machine time and setup; then margin and volume discount are applied.</p>';
  }

  if ((q.lines || []).length) {
    html += '<div style="border:1px solid #e3e6ea;border-radius:10px;padding:12px 14px;margin-top:12px;background:#fbfcfe">' +
            '<div style="display:flex;justify-content:space-between;align-items:baseline">' +
            '<b style="font-size:13px">What if we discount?</b>' +
            '<span id="disc-val" style="font-size:13px;color:#1266f1;font-weight:600">0%</span></div>' +
            '<input id="disc" type="range" min="0" max="20" step="1" value="0" style="width:100%;margin-top:8px">' +
            '<div id="margin-out" style="margin-top:8px;font-size:12.5px;line-height:1.7">' +
            'Slide to see revenue, profit and margin. Above 8% needs manager sign-off.</div>' +
            '<p style="margin:10px 0 0"><button class="ghost" id="generate-discount" style="width:auto;margin:0;padding:7px 14px">' +
            'Generate quotation at this discount</button> <span class="muted" id="generate-status"></span></p>' +
            '</div>';
  }

  if ((q.held || []).length) {
    html += '<h2 style="margin-top:16px">Held — what we can already cost</h2><table>' +
            '<tr><th>Part</th><th class="num">Qty</th><th>Costed so far</th><th class="num">Subtotal</th><th>Still missing</th></tr>';
    for (const h of q.held) {
      const partial = h.partial || {};
      const known = Object.entries(partial.known || {})
        .map(([name, item]) => '<div><span class="muted">' + esc(name) + '</span> ' + money(item.amount) +
             ' <span class="muted">(' + esc(item.detail) + ')</span></div>').join('');
      const missing = (partial.missing || []).map(m => '<div style="color:#a12a2a">' + esc(m) + '</div>').join('');
      html += '<tr><td><b>' + esc(h.part_no) + '</b><div class="muted">' + esc(h.detail || h.reason) + '</div></td>' +
              '<td class="num">' + (h.qty ? esc(h.qty) : '<span class="muted">—</span>') + '</td>' +
              '<td>' + (known || '<span class="muted">nothing yet</span>') + '</td>' +
              '<td class="num">' + (partial.known_subtotal !== undefined ? money(partial.known_subtotal) : '—') + '</td>' +
              '<td>' + (missing || '<span class="muted">—</span>') + '</td></tr>';
    }
    html += '</table>';
  }

  if ((q.conflicts || []).length) {
    html += '<h2 style="margin-top:16px">Conflicts</h2><table>';
    for (const c of q.conflicts) html += '<tr><td class="muted">' + esc(c) + '</td></tr>';
    html += '</table>';
  }

  const approval = q.approval || {};
  html += '<h2 style="margin-top:16px">Approval</h2>';
  if (approval.required) {
    html += '<div class="warn"><b>Needs sign-off</b><br>' + (approval.reasons || []).map(esc).join('<br>') + '</div>' +
            '<p style="margin:10px 0 0"><button class="ghost" id="submit-approval" style="width:auto;margin:0;padding:7px 14px">Submit for approval</button>' +
            ' <span class="muted" id="approval-status"></span></p><div id="approval-reply"></div>';
  } else {
    html += '<p class="muted">No approval required (within delegated authority).</p>';
  }

  if (data.pdf_url) {
    html += '<p style="margin:14px 0 0"><a id="quote-pdf-link" href="' + esc(data.pdf_url) + '" target="_blank">Open quotation PDF</a>' +
            ' <span class="muted">(' + Math.round((data.pdf_bytes || 0) / 1024) + ' KB, link valid 1 hour)</span>';
    if (data.review_url) {
      html += ' &nbsp;·&nbsp; <a id="review-pdf-link" href="' + esc(data.review_url) + '" target="_blank">Review list PDF</a>' +
              ' <span class="muted">(what to check, why, approval status)</span>';
    }
    html += '</p>';
  }

  if (data.reply_email) {
    html += '<h2 style="margin-top:16px">Reply email</h2><div id="reply-panel"><pre>' + esc(data.reply_email) + '</pre></div>';
  }

  if ((data.tools || []).length) {
    html += '<h2 style="margin-top:16px">Tools used</h2><p>' +
            data.tools.map(t => '<span class="pill">' + esc(t) + '</span>').join('') + '</p>';
  }

  out.innerHTML = html || '<p class="muted">Empty response.</p>';
  const sources = document.createElement('div');
  sources.id = 'sources';
  out.appendChild(sources);

  // 用事件委托绑定，避免内联 onclick（有些浏览器/扩展会拦）
  out.querySelectorAll('.trace-link').forEach(link => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      toggleTrace(link.dataset.i);
    });
  });
  out.querySelectorAll('.why-link').forEach(link => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      toggleRow('why-' + link.dataset.i);
    });
  });

  const slider = document.getElementById('disc');
  if (slider) {
    let timer = null;
    slider.addEventListener('input', () => {
      document.getElementById('disc-val').textContent = slider.value + '%';
      clearTimeout(timer);
      timer = setTimeout(() => reprice(Number(slider.value) / 100), 180);
    });
  }

  const genBtn = document.getElementById('generate-discount');
  if (genBtn) {
    genBtn.addEventListener('click', async () => {
      const statusEl = document.getElementById('generate-status');
      genBtn.disabled = true;
      statusEl.textContent = 'Generating…';
      try {
        const res = await fetch('/api/regenerate', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({quote: CURRENT_QUOTE, discount_rate: CURRENT_DISCOUNT}),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        // 表格按当前折扣刷新
        for (const line of (CURRENT_QUOTE.lines || [])) {
          const row = out.querySelector('tr[data-part="' + CSS.escape(line.part_no) + '"]');
          if (!row) continue;
          const unit = row.querySelector('.unit');
          const total = row.querySelector('.line-total');
          if (unit) unit.textContent = money(line.unit_price);
          if (total) total.textContent = money(line.line_total);
        }
        const totalEl = document.getElementById('quote-total');
        if (totalEl) totalEl.textContent = 'MYR ' + money(CURRENT_QUOTE.total);

        const pdfLink = document.getElementById('quote-pdf-link');
        if (pdfLink && data.pdf_url) pdfLink.href = data.pdf_url;
        const reviewLink = document.getElementById('review-pdf-link');
        if (reviewLink && data.review_url) reviewLink.href = data.review_url;

        statusEl.innerHTML = (CURRENT_DISCOUNT > 0
          ? 'Table and PDF now show the <b>' + (CURRENT_DISCOUNT * 100).toFixed(0) + '%</b> version.'
          : 'Table and PDF show the list-price version.');
      } catch (err) {
        statusEl.textContent = err.message;
      } finally {
        genBtn.disabled = false;
      }
    });
  }

  const submit = document.getElementById('submit-approval');
  if (submit) {
    submit.addEventListener('click', async () => {
      submit.disabled = true;
      const label = document.getElementById('approval-status');
      label.textContent = 'Submitting…';
      try {
        const res = await fetch('/api/approve', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({quote: CURRENT_QUOTE, requested_by: 'sales', discount_rate: CURRENT_DISCOUNT}),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        let extra = '';
        if (data.pdf_url) {
          extra += ' · <a href="' + esc(data.pdf_url) + '" target="_blank">Quotation PDF (this version)</a>';
        }
        if (data.review_url) {
          extra += ' · <a href="' + esc(data.review_url) + '" target="_blank">Review list PDF</a>';
        }
        label.innerHTML = 'Status: <b>' + esc(data.status) + '</b>' + extra +
                          ' · <a href="/approvals">view queue →</a>';
        if (data.reply_email) {
          const box = document.getElementById('approval-reply');
          if (box) box.innerHTML = '<h2 style="margin-top:14px">Reply draft (submitted version)</h2><pre>' + esc(data.reply_email) + '</pre>';
        }
      } catch (err) {
        label.textContent = err.message;
        submit.disabled = false;
      }
    });
  }
}

function toggleTrace(index) {
  toggleRow('trace-' + index);
}

function toggleRow(id) {
  const row = document.getElementById(id);
  if (row) row.style.display = row.style.display === 'none' ? '' : 'none';
}

async function reprice(rate) {
  const box = document.getElementById('margin-out');
  if (!CURRENT_QUOTE || !box) return;
  box.innerHTML = 'Recalculating…';
  try {
    const res = await fetch('/api/reprice', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({quote: CURRENT_QUOTE, discount_rate: rate}),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    // 让滑杆结果成为"当前报价"：提交审批时提交的就是这一版
    CURRENT_DISCOUNT = rate;
    const byPart = {};
    (data.lines || []).forEach(l => { byPart[l.part_no] = l; });
    CURRENT_QUOTE = Object.assign({}, CURRENT_QUOTE, {
      total: data.total,
      approval: data.approval,
      proposed_discount: rate,
      lines: (CURRENT_QUOTE.lines || []).map(l => {
        const updated = byPart[l.part_no];
        return updated
          ? Object.assign({}, l, {unit_price: updated.unit_price, line_total: updated.line_total, discount_rate: rate})
          : l;
      }),
    });

    let html = '<table style="font-size:12.5px">' +
      '<tr><td>Revenue</td><td class="num">' + money(data.total) + '</td></tr>' +
      '<tr><td>Cost</td><td class="num">' + money(data.total_cost) + '</td></tr>' +
      '<tr><td><b>Gross profit</b></td><td class="num"><b>' + money(data.profit) + '</b></td></tr>' +
      '<tr><td>Gross margin</td><td class="num">' + (data.margin * 100).toFixed(1) + '%</td></tr></table>';
    const approval = data.approval || {};
    if (approval.required) {
      html += '<div class="warn" style="margin-top:8px">' + (approval.reasons || []).map(esc).join('<br>') + '</div>';
    } else {
      html += '<p class="muted" style="margin-top:6px">Within delegated authority.</p>';
    }
    if (rate > 0) {
      html += '<p class="muted" style="margin-top:6px">This is an extra discount on top of the volume tier. Submitting approval will submit this ' +
              (rate * 100).toFixed(0) + '% version.</p>';
    }
    box.innerHTML = html;

    // 回信正文跟着折扣走
    if (data.reply_email) {
      const replyBox = document.querySelector('#reply-panel pre');
      if (replyBox) replyBox.textContent = data.reply_email;
    }
  } catch (err) {
    box.innerHTML = '<div class="warn">' + esc(err.message) + '</div>';
  }
}
</script>
</body>
</html>
"""


INBOX_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Inbox · Quotation Agent</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0; background: #f6f7f9; color: #1a1a1a; color-scheme: light; }
  header { background: #0f2b46; color: #fff; padding: 12px 22px; display: flex; justify-content: space-between; align-items: center; font-size: 15px; }
  header nav a { color: #cfe0f5; text-decoration: none; margin-left: 18px; font-size: 13px; }
  header nav a.active { color: #fff; font-weight: 600; }
  main { display: grid; grid-template-columns: 360px 1fr; gap: 16px; padding: 16px; align-items: start; }
  .card { background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 14px; }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: #5b6b7c; margin: 0 0 10px; }
  select, input { width: 100%; box-sizing: border-box; border: 1px solid #cfd6dd; border-radius: 7px; padding: 7px 8px; font: inherit; font-size: 12.5px; }
  .filters { display: grid; gap: 6px; margin-bottom: 10px; }
  .item { padding: 9px 10px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; }
  .item:hover { background: #f3f6fa; }
  .item.active { background: #eaf2fe; border-color: #cfe0fb; }
  .item .subj { font-size: 13px; font-weight: 600; margin-bottom: 2px; }
  .item .meta { font-size: 11.5px; color: #6b7a89; }
  .badge { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 99px; background: #e8f2e8; color: #2f6b34; margin-left: 4px; }
  .empty, .muted { color: #6b7a89; font-size: 13px; }
  .row { display: flex; gap: 8px; margin-top: 10px; }
  button { border: 0; border-radius: 8px; padding: 9px 14px; font-size: 13px; cursor: pointer; }
  button.primary { background: #1266f1; color: #fff; }
  button.ghost { background: #eef2f7; color: #1a1a1a; }
  button:disabled { opacity: .5; cursor: default; }
  .body-text { white-space: pre-wrap; font-size: 13px; line-height: 1.55; background: #fafbfc; border: 1px solid #eef1f4; border-radius: 8px; padding: 12px; max-height: 320px; overflow: auto; }
  .att { display: inline-flex; align-items: center; gap: 6px; background: #eef7ee; color: #2f6b34; border-radius: 99px; padding: 3px 10px; font-size: 12px; margin: 4px 6px 0 0; cursor: pointer; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eef1f4; }
  th { font-size: 11px; text-transform: uppercase; color: #6b7a89; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .total { font-size: 19px; font-weight: 600; margin: 10px 0 2px; }
  .warn { background: #fff8e6; border: 1px solid #f3dfa8; border-radius: 8px; padding: 9px 11px; font-size: 12px; margin: 10px 0; }
  pre { white-space: pre-wrap; font-size: 12.5px; background: #f8fafc; border: 1px solid #eef1f4; border-radius: 8px; padding: 12px; }
  #drawer { position: fixed; top: 0; right: 0; width: 62vw; min-width: 520px; max-width: 96vw; height: 100vh; background: #fff;
            border-left: 1px solid #e3e6ea; box-shadow: -8px 0 24px rgba(20,40,70,.12); transform: translateX(100%);
            transition: transform .18s ease; display: flex; flex-direction: column; z-index: 20; }
  #drawer.open { transform: translateX(0); }
  #drawer header { background: #0f2b46; color: #fff; padding: 12px 16px; font-size: 13px; display: flex; justify-content: space-between; align-items: center; }
  #drawer header button { width: auto; margin: 0; padding: 2px 8px; background: transparent; border: 1px solid rgba(255,255,255,.35); color: #fff; font-size: 12px; }
  #drawer .dbody { padding: 14px 16px; overflow: auto; }
</style>
</head>
<body>{{NAV}}
<header>
  <span>Quotation Agent · Inbox</span>
  <nav><a href="/">Quotation</a><a href="/inbox" class="active">Inbox</a><a href="/approvals">Approvals</a><a href="/prices">Prices</a></nav>
</header>

<main>
  <section class="card">
    <h2>Emails in S3</h2>
    <div class="filters">
      <select id="fdomain"><option value="">All companies</option></select>
      <select id="fcontact"><option value="">All contacts</option></select>
      <input id="fsearch" placeholder="Search subject or file name">
    </div>
    <div id="list"><p class="empty">Loading…</p></div>
  </section>

  <section class="card">
    <h2>Email</h2>
    <div id="detail"><p class="empty">Pick an email on the left.</p></div>
  </section>
</main>

<aside id="drawer">
  <header><span id="drawer-title">Attachment</span><button id="drawer-close">Close</button></header>
  <div class="dbody" id="drawer-body"></div>
</aside>

<script>
const esc = (s) => String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const money = (n) => Number(n).toLocaleString('en-MY', {minimumFractionDigits: 2, maximumFractionDigits: 2});

let cache = [], companies = [], current = null, SOURCES = [];
const listEl = document.getElementById('list');
const detailEl = document.getElementById('detail');
const fdomain = document.getElementById('fdomain');
const fcontact = document.getElementById('fcontact');
const fsearch = document.getElementById('fsearch');

async function loadEmails() {
  listEl.innerHTML = '<p class="empty">Loading…</p>';
  try {
    const data = await (await fetch('/api/emails')).json();
    if (data.error) throw new Error(data.error);
    cache = data.emails || [];
    companies = data.companies || [];
    fdomain.innerHTML = '<option value="">All companies (' + cache.length + ')</option>' +
      companies.map(c => '<option value="' + esc(c.domain) + '">' + esc(c.domain) + ' (' + c.count + ')</option>').join('');
    applyFilters();
  } catch (err) {
    listEl.innerHTML = '<p class="empty">' + esc(err.message) + '</p>';
  }
}

function contactsFor(domain) {
  const set = new Set();
  cache.filter(e => !domain || e.domain === domain).forEach(e => { if (e.contact) set.add(e.contact); });
  return [...set].sort();
}

function applyFilters() {
  const domain = fdomain.value;
  const contacts = contactsFor(domain);
  const keepContact = fcontact.value;
  fcontact.innerHTML = '<option value="">All contacts</option>' +
    contacts.map(c => '<option value="' + esc(c) + '">' + esc(c) + '</option>').join('');
  if (keepContact && contacts.includes(keepContact)) fcontact.value = keepContact;

  const needle = (fsearch.value || '').toLowerCase();
  const visible = cache.filter(e =>
    (!domain || e.domain === domain) &&
    (!fcontact.value || e.contact === fcontact.value) &&
    (!needle || (e.subject || '').toLowerCase().includes(needle) || (e.name || '').toLowerCase().includes(needle))
  );

  if (!visible.length) { listEl.innerHTML = '<p class="empty">No email matches the filter.</p>'; return; }
  listEl.innerHTML = visible.map(e =>
    '<div class="item' + (current === e.key ? ' active' : '') + '" data-key="' + esc(e.key) + '">' +
    '<div class="subj">' + esc(e.subject || e.name) + '</div>' +
    '<div class="meta">' + esc(e.contact || '') + ' · ' + esc(e.domain || '') + ' · ' + Math.round(e.size / 1024) + ' KB' +
    ((e.attachments || []).length ? '<span class="badge">' + e.attachments.length + ' files</span>' : '') +
    '</div></div>').join('');

  listEl.querySelectorAll('.item').forEach(el => el.addEventListener('click', () => openEmail(el.dataset.key)));
}

async function openEmail(key) {
  current = key;
  applyFilters();
  detailEl.innerHTML = '<p class="empty">Loading email…</p>';
  try {
    const data = await (await fetch('/api/email?key=' + encodeURIComponent(key))).json();
    if (data.error) throw new Error(data.error);
    let html = '<div style="font-size:15px;font-weight:600;margin-bottom:4px">' + esc(data.subject) + '</div>' +
      '<div class="meta" style="font-size:12px;color:#6b7a89">' + esc(data.from) + ' · ' +
      esc((data.date || '').slice(0, 16).replace('T', ' ')) + ' · ' + esc(data.key) + '</div>';
    if ((data.rfq_ids || []).length) {
      html += '<div style="margin-top:6px"><span class="badge">' + esc(data.rfq_ids.join(', ')) + '</span>' +
              (data.customer ? '<span class="badge">' + esc(data.customer) + '</span>' : '') + '</div>';
    }
    if ((data.attachments || []).length) {
      html += '<div style="margin-top:8px">' + data.attachments.map(a =>
        '<span class="att" data-file="' + esc(a.filename) + '">📎 ' + esc(a.filename) +
        ' <span style="opacity:.6">' + Math.round(a.size / 1024) + ' KB</span></span>').join('') + '</div>';
    } else {
      html += '<p class="empty" style="margin-top:8px">No attachments in this email.</p>';
    }
    html += '<h2 style="margin-top:14px">Body</h2><div class="body-text">' + esc(data.body_text || '') + '</div>';
    detailEl.innerHTML = html;
    detailEl.querySelectorAll('.att').forEach(el => el.addEventListener('click', () => loadSources(key, el.dataset.file)));
  } catch (err) {
    detailEl.innerHTML = '<div class="warn">' + esc(err.message) + '</div>';
  }
}

async function loadSources(key, focusName) {
  try {
    const data = await (await fetch('/api/attachments?key=' + encodeURIComponent(key))).json();
    if (data.error) throw new Error(data.error);
    SOURCES = data.attachments || [];
    const index = Math.max(0, SOURCES.findIndex(f => f.filename === focusName));
    if (SOURCES.length) openDrawer(index);
  } catch (err) {
    alert(err.message);
  }
}

""" + DRAWER_JS + """
fdomain.addEventListener('change', applyFilters);
fcontact.addEventListener('change', applyFilters);
fsearch.addEventListener('input', applyFilters);
loadEmails();
</script>
</body>
</html>
"""


APPROVALS_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Approvals · Quotation Agent</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0; background: #f6f7f9; color: #1a1a1a; color-scheme: light; }
  header { background: #0f2b46; color: #fff; padding: 12px 22px; display: flex; justify-content: space-between; align-items: center; font-size: 15px; }
  header nav a { color: #cfe0f5; text-decoration: none; margin-left: 18px; font-size: 13px; }
  header nav a.active { color: #fff; font-weight: 600; }
  main { padding: 16px; }
  .card { background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 14px; }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: #5b6b7c; margin: 0 0 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px; border-bottom: 1px solid #eef1f4; vertical-align: top; }
  th { font-size: 11px; text-transform: uppercase; color: #6b7a89; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .status { font-size: 11px; padding: 2px 8px; border-radius: 99px; }
  .pending_manager { background: #fff6e0; color: #8a6100; }
  .approved { background: #e8f2e8; color: #2f6b34; }
  .rejected { background: #fdeaea; color: #a12a2a; }
  .muted { color: #6b7a89; font-size: 12px; }
  button { border: 0; border-radius: 7px; padding: 5px 10px; font-size: 12px; cursor: pointer; }
  button.ok { background: #1266f1; color: #fff; }
  button.no { background: #eef2f7; color: #1a1a1a; }
  .reason { font-size: 12px; color: #7a5a00; }
</style>
</head>
<body>{{NAV}}
<header>
  <span>Quotation Agent · Approvals</span>
  <nav><a href="/">Quotation</a><a href="/inbox">Inbox</a><a href="/approvals" class="active">Approvals</a><a href="/prices">Prices</a></nav>
</header>
<main>
  <section class="card">
    <h2>Approval queue</h2>
    <div id="list"><p class="muted">Loading…</p></div>
  </section>
</main>
<script>
const esc = (s) => String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const money = (n) => Number(n || 0).toLocaleString('en-MY', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const listEl = document.getElementById('list');

async function load() {
  listEl.innerHTML = '<p class="muted">Loading…</p>';
  try {
    const data = await (await fetch('/api/approvals')).json();
    if (data.error) throw new Error(data.error);
    if (!data.items.length) { listEl.innerHTML = '<p class="muted">No approval record yet. Quote something large and submit it from the quotation page.</p>'; return; }
    let html = '<table><tr><th>RFQ</th><th>Customer</th><th class="num">Total</th><th>Status</th><th>Why</th><th></th></tr>';
    for (const item of data.items) {
      const reasons = (item.reasons || []).map(r => '<div class="reason">' + esc(r) + '</div>').join('');
      const flags = (item.flags || []).map(f => '<div class="muted">' + esc(f.part_no) + ': ' + esc((f.flags || []).join('; ')) + '</div>').join('');
      const actions = item.status === 'pending_manager'
        ? '<button class="ok" data-key="' + esc(item.s3_key) + '" data-decision="approved">Approve</button> ' +
          '<button class="no" data-key="' + esc(item.s3_key) + '" data-decision="rejected">Reject</button>'
        : '<span class="muted">' + esc(item.decided_by || '') + '</span>';
      html += '<tr><td><b>' + esc(item.rfq_no) + '</b><div class="muted">' + esc(item.id) + '</div></td>' +
              '<td>' + esc(item.customer || '') + '</td>' +
              '<td class="num">' + money(item.total) + '</td>' +
              '<td><span class="status ' + esc(item.status) + '">' + esc(item.status) + '</span>' +
              '<div class="muted">' + esc((item.submitted_at || '').replace('T', ' ')) + '</div></td>' +
              '<td>' + reasons + flags + '</td>' +
              '<td style="white-space:nowrap">' + actions + '</td></tr>';
    }
    html += '</table>';
    listEl.innerHTML = html;
    listEl.querySelectorAll('button[data-key]').forEach(btn => {
      btn.addEventListener('click', () => decide(btn.dataset.key, btn.dataset.decision));
    });
  } catch (err) {
    listEl.innerHTML = '<p class="muted">' + esc(err.message) + '</p>';
  }
}

async function decide(key, decision) {
  await fetch('/api/decision', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({s3_key: key, decision, decided_by: 'sales manager'}),
  });
  load();
}

load();
</script>
</body>
</html>
"""


ASSUMPTIONS_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Assumptions</title>
<style>
  body { margin:0; padding:0; font-family:"Segoe UI",-apple-system,sans-serif; background:#f7f9fc; color:#14212e; }
  .wrap { padding:24px 34px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:#5b6b7c; font-size:13px; margin-bottom:20px; }
  .card { background:#fff; border:1px solid #dde5ee; border-radius:12px; padding:14px 16px; margin-bottom:16px; }
  .card h2 { font-size:11.5px; text-transform:uppercase; letter-spacing:.06em; color:#6b7a89; margin:0 0 10px; }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th,td { text-align:left; padding:8px 8px; border-bottom:1px solid #eef2f7; vertical-align:top; }
  th { color:#6b7a89; font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
  td.item { width:170px; font-weight:600; }
  td.value { width:260px; font-family:ui-monospace,Consolas,monospace; font-size:12.5px; color:#1266f1; }
  td.why { color:#3d4a56; line-height:1.5; }
  .muted { color:#5b6b7c; font-size:12px; }
</style></head><body>__NAV__<div class="wrap">
<h1>Assumptions</h1>
<div class="sub">Every number the brief left open, with the reason. Values are read from the pricing code, not typed in twice.</div>
<div id="groups"><p class="muted">loading…</p></div>
<div class="card"><h2>What I did not assume</h2>
  <div class="muted" style="font-size:12.5px;line-height:1.6">
    Material prices, machine rates and setup cost come from the price list in the brief — not from me.<br>
    Whether a quote needs approval is computed from those numbers, not decided by the agent.<br>
    A missing value is never filled in: the line is held, with the missing field named.
  </div>
</div>
</div>
<script>
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
fetch('/api/assumptions').then(r => r.json()).then(data => {
  if (data.error) { document.getElementById('groups').innerHTML = '<div class="card">' + esc(data.error) + '</div>'; return; }
  document.getElementById('groups').innerHTML = data.groups.map(group => {
    const rows = group.rows.map(row =>
      '<tr><td class="item">' + esc(row.item) + '</td>' +
      '<td class="value">' + esc(row.value) + '</td>' +
      '<td class="why">' + esc(row.why) + '</td></tr>').join('');
    return '<div class="card"><h2>' + esc(group.title) + '</h2>' +
      '<table><thead><tr><th>Item</th><th>Value</th><th>Why</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  }).join('');
});
</script>
</body></html>
"""

COST_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Cost per quote</title>
<style>
  body { margin:0; padding:28px 34px; font-family:"Segoe UI",-apple-system,sans-serif; background:#f7f9fc; color:#14212e; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:#5b6b7c; font-size:13px; margin-bottom:22px; }
  .card { background:#fff; border:1px solid #dde5ee; border-radius:12px; padding:16px 18px; margin-bottom:16px; }
  .hero { display:flex; gap:28px; align-items:flex-end; }
  .big { font-size:44px; font-weight:700; line-height:1; }
  .unit { font-size:14px; color:#5b6b7c; margin-left:8px; }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th,td { text-align:left; padding:7px 6px; border-bottom:1px solid #eef2f7; }
  th { color:#6b7a89; font-weight:600; font-size:11.5px; text-transform:uppercase; letter-spacing:.05em; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .bar { height:9px; background:#1266f1; border-radius:5px; }
  .barwrap { background:#eef3f9; border-radius:5px; height:9px; width:180px; }
  .muted { color:#5b6b7c; font-size:12px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
</style></head><body>{{NAV}}
<h1>Cost per quote</h1>
<div class="sub">Live from CloudWatch for this account · published rates, measured durations</div>

<div class="card"><div class="hero">
  <div><div class="big" id="total">—</div><div class="muted" id="totalSub">calculating…</div></div>
  <div class="muted" id="measured"></div>
</div></div>

<div class="card">
  <table id="items"><thead><tr><th>Component</th><th>Usage</th><th class="num">USD</th><th>Share</th></tr></thead><tbody></tbody></table>
</div>

<div class="grid">
  <div class="card"><div class="muted" style="text-transform:uppercase;letter-spacing:.05em;font-size:11px">What it replaces</div>
    <div style="font-size:15px;margin-top:8px">≈ 20 minutes of an estimator's time per quote</div>
    <div class="muted" style="margin-top:6px">Manual: read 3 documents, look up 2 materials, compute 5 lines, write the reply.</div></div>
  <div class="card"><div class="muted" style="text-transform:uppercase;letter-spacing:.05em;font-size:11px">Where the money goes</div>
    <div class="muted" style="margin-top:8px" id="note">Memory events dominate; the model call is a fallback, and header mapping is cached per template.</div></div>
</div>

<script>
const fmt = (v, d=6) => '$' + Number(v).toFixed(d);
async function load() {
  const res = await fetch('/api/costs'); const d = await res.json();
  if (d.error) { document.getElementById('total').textContent = 'error'; document.getElementById('totalSub').textContent = d.error; return; }
  document.getElementById('total').innerHTML = '¥' + Number(d.total_cny).toFixed(4) + '<span class="unit">CNY per quote</span>';
  document.getElementById('totalSub').textContent = fmt(d.total_usd) + ' USD  ·  about ' + Number(d.per_document_cny_fen).toFixed(1) + ' Chinese fen';
  const m = d.measured || {};
  document.getElementById('measured').innerHTML = 'measured, last ' + (m.window_hours||24) + ' h<br>' +
    '<b>' + (m.invocations||0) + '</b> Lambda invocations<br>avg <b>' + (m.avg_ms||0) + ' ms</b> · max <b>' + (m.max_ms||0) + ' ms</b>';
  const max = Math.max(...d.items.map(i => i.usd));
  document.querySelector('#items tbody').innerHTML = d.items.map(i =>
    '<tr><td>' + i.name + '</td><td class="muted">' + i.detail + '</td>' +
    '<td class="num">' + fmt(i.usd) + '</td>' +
    '<td><div class="barwrap"><div class="bar" style="width:' + Math.max(3, i.usd / max * 100) + '%"></div></div></td></tr>'
  ).join('');
}
load();
</script>
</body></html>
"""

TRACES_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Traces and logs</title>
<style>
  body { margin:0; padding:0; font-family:"Segoe UI",-apple-system,sans-serif; background:#f7f9fc; color:#14212e; }
  .wrap { padding:24px 34px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:#5b6b7c; font-size:13px; margin-bottom:18px; }
  .grid { display:grid; grid-template-columns:270px 1fr; gap:16px; }
  .card { background:#fff; border:1px solid #dde5ee; border-radius:12px; padding:14px 16px; margin-bottom:16px; }
  .card h2 { font-size:11.5px; text-transform:uppercase; letter-spacing:.06em; color:#6b7a89; margin:0 0 10px; }
  .item { padding:8px 9px; border-radius:8px; cursor:pointer; border:1px solid transparent; }
  .item:hover { background:#f4f8fd; }
  .item.on { background:#eaf2ff; border-color:#b9d4ff; }
  .item .t { font-family:ui-monospace,Consolas,monospace; font-size:11.5px; color:#5b6b7c; }
  .item .n { font-size:13px; font-weight:600; }
  table { border-collapse:collapse; width:100%; font-size:12px; }
  th,td { text-align:left; padding:6px 7px; border-bottom:1px solid #eef2f7; vertical-align:top; }
  th { color:#6b7a89; font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .mono { font-family:ui-monospace,Consolas,monospace; font-size:11.5px; }
  .io { max-width:420px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .rule { color:#8a6100; font-family:ui-monospace,Consolas,monospace; font-size:11.5px; }
  pre { background:#0f1b26; color:#d7e3ee; padding:12px 14px; border-radius:9px; overflow:auto; font-size:11.5px; line-height:1.55; margin:0; }
  .muted { color:#5b6b7c; font-size:12px; }
  .pill { display:inline-block; background:#eef3f9; border-radius:99px; padding:1px 8px; font-size:11px; color:#3d4a56; }
</style></head><body>{{NAV}}<div class="wrap">
<h1>Traces</h1>
<div class="sub">Left: each quote this session, newest first. Right: the Gateway tools it called, with input and output.</div>

<div class="grid">
  <div>
    <div class="card"><h2>Quotes this session</h2><div id="history"><p class="muted">Run a quote first.</p></div></div>
    <div class="card"><h2>Runtime invocations (3 h)</h2><div id="runs"></div></div>
  </div>
  <div>
    <div class="card"><h2>Tool calls</h2><div id="calls"><p class="muted">Pick a quote on the left.</p></div></div>
    <div class="card"><h2>Price rule chain</h2><div id="chain"></div></div>
    <div class="card"><h2>Raw log (latest)</h2><pre id="raw">loading…</pre></div>
  </div>
</div>
</div>
<script>
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let DATA = null, SELECTED = 0;

function renderHistory() {
  const list = (DATA && DATA.history) || [];
  document.getElementById('history').innerHTML = list.length ? list.map((h, i) =>
    '<div class="item' + (i === SELECTED ? ' on' : '') + '" data-i="' + i + '">' +
    '<div class="n">' + esc(h.rfq_no || '(no RFQ)') + ' · MYR ' + esc(h.total) + '</div>' +
    '<div class="t">' + esc(h.at) + ' · ' + (h.tool_calls || []).length + ' tool calls · ' +
    Math.round((h.elapsed_ms || 0) / 100) / 10 + 's</div></div>').join('')
    : '<p class="muted">Run a quote first.</p>';
  document.querySelectorAll('.item').forEach(el => el.onclick = () => { SELECTED = Number(el.dataset.i); renderHistory(); renderDetail(); });
}

function renderDetail() {
  const list = (DATA && DATA.history) || [];
  const item = list[SELECTED];
  if (!item) { document.getElementById('calls').innerHTML = '<p class="muted">Pick a quote.</p>'; return; }
  const calls = item.tool_calls || [];
  document.getElementById('calls').innerHTML = calls.length ? '<table><thead><tr><th>#</th><th>Tool</th><th class="num">ms</th><th>Input</th><th>Output</th></tr></thead><tbody>' +
    calls.map((c, i) => '<tr><td class="num">' + (i + 1) + '</td><td class="mono">' + esc(c.tool) + '</td>' +
      '<td class="num">' + esc(c.ms) + '</td>' +
      '<td class="io mono" title="' + esc(c.input) + '">' + esc(c.input) + '</td>' +
      '<td class="io mono" title="' + esc(c.output) + '">' + esc(c.output) + '</td></tr>').join('') +
    '</tbody></table>'
    : '<p class="muted">No tool calls recorded for this quote.</p>';

  const lines = item.lines || [];
  document.getElementById('chain').innerHTML = lines.length ? lines.map(l =>
    '<div style="margin-bottom:10px"><span class="pill">' + esc(l.part_no) + '</span> unit ' + esc(l.unit_price) +
    '<div class="rule" style="margin-top:4px">' + (l.trace || []).map(esc).join('<br>') + '</div></div>').join('')
    : '<p class="muted">No priced lines.</p>';
}

function renderRuns() {
  const runs = (DATA && DATA.runtime) || [];
  const max = Math.max(0.1, ...runs.map(r => r.seconds || 0));
  document.getElementById('runs').innerHTML = runs.slice(0, 8).map(r =>
    '<div style="font-size:11.5px;margin-bottom:5px"><span class="mono">' + esc(r.at) + '</span> ' +
    '<span class="muted">' + (r.seconds == null ? '—' : r.seconds.toFixed(2) + 's') + '</span>' +
    '<div style="height:5px;background:#eef3f9;border-radius:3px;margin-top:2px">' +
    '<div style="height:5px;background:#1266f1;border-radius:3px;width:' + Math.max(4, (r.seconds || 0) / max * 100) + '%"></div></div></div>'
  ).join('') || '<p class="muted">no invocations in the last 3 h</p>';
}

async function load() {
  const res = await fetch('/api/traces');
  DATA = await res.json();
  if (DATA.error) { document.getElementById('raw').textContent = DATA.error; return; }
  renderHistory(); renderDetail(); renderRuns();
  const runs = DATA.runtime || [];
  document.getElementById('raw').textContent = runs.slice(0, 5).map(r => r.at + '  ' + r.session + '  ' + r.message).join(String.fromCharCode(10)) || 'no log events';
}
load();
</script>
</body></html>
"""


PRICES_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Prices · Quotation Agent</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0; background: #f6f7f9; color: #1a1a1a; color-scheme: light; }
  header { background: #0f2b46; color: #fff; padding: 12px 22px; display: flex; justify-content: space-between; align-items: center; font-size: 15px; }
  header nav a { color: #cfe0f5; text-decoration: none; margin-left: 18px; font-size: 13px; }
  header nav a.active { color: #fff; font-weight: 600; }
  main { padding: 16px; display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 16px; align-items: start; }
  .card { background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 14px; }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: #5b6b7c; margin: 0 0 10px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid #eef1f4; }
  th { font-size: 11px; text-transform: uppercase; color: #6b7a89; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .muted { color: #6b7a89; font-size: 12px; }
  .formula { font-family: ui-monospace, Consolas, monospace; font-size: 12.5px; background: #f8fafc; border: 1px solid #eef1f4; border-radius: 8px; padding: 10px; white-space: pre-wrap; }
</style>
</head>
<body>{{NAV}}
<header>
  <span>Quotation Agent · Price list</span>
  <nav><a href="/">Quotation</a><a href="/inbox">Inbox</a><a href="/approvals">Approvals</a><a href="/prices" class="active">Prices</a></nav>
</header>
<main>
  <section class="card">
    <h2>Material (per kg)</h2>
    <div id="materials"><p class="muted">Loading…</p></div>
  </section>
  <section class="card">
    <h2>Machining (per minute, by tolerance)</h2>
    <div id="machines"><p class="muted">Loading…</p></div>
  </section>
  <section class="card">
    <h2>Finishing (per piece)</h2>
    <div id="finishes"><p class="muted">Loading…</p></div>
  </section>
  <section class="card">
    <h2>Rules</h2>
    <div id="rules"><p class="muted">Loading…</p></div>
  </section>
  <section class="card" style="grid-column: 1 / -1">
    <h2>How a price is built</h2>
    <div class="formula">unit cost  = mass x material rate + cycle x machine rate + finish + setup / qty
selling    = unit cost / (1 - margin)
discount   = volume tier by quantity (applied on selling price)
line total = unit price x qty

Missing inputs do not become assumptions: the line is held and the known
components are still shown, so procurement only has to fill the gap.</div>
  </section>
</main>
<script>
const esc = (s) => String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const num = (n, digits = 2) => Number(n).toLocaleString('en-MY', {minimumFractionDigits: digits, maximumFractionDigits: digits});
const pct = (n) => (Number(n) * 100).toFixed(0) + '%';

(async () => {
  try {
    const data = await (await fetch('/api/prices')).json();
    if (data.error) throw new Error(data.error);

    document.getElementById('materials').innerHTML =
      '<table><tr><th>Material</th><th class="num">MYR / kg</th></tr>' +
      (data.materials || []).map(m => '<tr><td>' + esc(m.material) + '</td><td class="num">' + num(m.price_per_kg) + '</td></tr>').join('') +
      '</table>';

    document.getElementById('machines').innerHTML =
      '<table><tr><th>Process</th><th class="num">Tolerance up to</th><th class="num">MYR / min</th></tr>' +
      (data.machine_rates || []).map(r => '<tr><td>' + esc(r.process) + '</td><td class="num">+/-' + esc(r.tolerance_upto_mm) + ' mm</td><td class="num">' + num(r.rate_per_min) + '</td></tr>').join('') +
      '</table>';

    document.getElementById('finishes').innerHTML =
      '<table><tr><th>Finish</th><th class="num">MYR / pc</th></tr>' +
      (data.finishes || []).map(f => '<tr><td>' + esc(f.finish) + '</td><td class="num">' + num(f.price_per_piece) + '</td></tr>').join('') +
      '</table>';

    document.getElementById('rules').innerHTML =
      '<table>' +
      '<tr><td>Setup per line</td><td class="num">' + num(data.setup_per_line) + ' MYR</td></tr>' +
      '<tr><td>Target margin</td><td class="num">' + pct(data.margin) + '</td></tr>' +
      '<tr><td>Volume discount</td><td class="num">' + (data.discount_tiers || []).map(t => pct(t.rate) + ' from ' + t.from_qty + ' pcs').join('<br>') + '</td></tr>' +
      '<tr><td>Approval above</td><td class="num">' + num(data.approval_threshold_myr, 0) + ' MYR</td></tr>' +
      '<tr><td>Max discount without approval</td><td class="num">' + pct(data.policy_max_discount) + '</td></tr>' +
      '</table>';
  } catch (err) {
    for (const id of ['materials', 'machines', 'finishes', 'rules']) {
      document.getElementById(id).innerHTML = '<p class="muted">' + esc(err.message) + '</p>';
    }
  }
})();
</script>
</body>
</html>
"""


def invoke_agent(payload: dict) -> dict:
    """调 AgentCore Runtime，返回解析后的结果。"""
    import boto3

    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    client = session.client("bedrock-agentcore")
    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=f"ui-{uuid.uuid4().hex}",
        payload=json.dumps(payload).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )
    raw = response["response"].read() if hasattr(response.get("response"), "read") else response["payload"]
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    return json.loads(raw)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # 安静一点
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.replace("{{NAV}}", NAV).encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/inbox"):
            self._send(200, INBOX_PAGE.replace("{{NAV}}", NAV).encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/approvals"):
            self._send(200, APPROVALS_PAGE.replace("{{NAV}}", NAV).encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/prices"):
            self._send(200, PRICES_PAGE.replace("{{NAV}}", NAV).encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/cost"):
            self._send(200, COST_PAGE.replace("{{NAV}}", NAV).encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/traces"):
            self._send(200, TRACES_PAGE.replace("{{NAV}}", NAV).encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/api/costs"):
            self._costs()
        elif self.path.startswith("/assumptions"):
            self._send(200, ASSUMPTIONS_PAGE.replace("__NAV__", NAV).encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/api/assumptions"):
            self._assumptions()
        elif self.path.startswith("/api/traces"):
            self._traces()
        elif self.path.startswith("/api/emails"):
            self._list_emails()
        elif self.path.startswith("/api/email"):
            self._read_email()
        elif self.path.startswith("/api/attachments"):
            self._preview_attachments()
        elif self.path.startswith("/api/approvals"):
            self._list_approvals()
        elif self.path.startswith("/api/prices"):
            self._get_prices()
        else:
            self._send(404, b"not found", "text/plain")

    def _assumptions(self) -> None:
        """假设表：数值直接读代码常量，不手写。"""
        try:
            from quotation_agent.quote.pricing import (
                APPROVAL_TOTAL_THRESHOLD, DISCOUNT_TIERS, MARGIN, POLICY_MAX_DISCOUNT,
                SETUP_PER_LINE,
            )
            from quotation_agent.quote.confidence import WEIGHTS

            margin = MARGIN
            threshold = APPROVAL_TOTAL_THRESHOLD
            cap = POLICY_MAX_DISCOUNT
            setup = SETUP_PER_LINE
            tiers = [(int(qty), rate) for qty, rate in DISCOUNT_TIERS]
            weights = dict(WEIGHTS)
        except Exception as exc:  # noqa: BLE001
            self._send(500, json.dumps({"error": f"cannot read constants: {exc}"}).encode(), "application/json")
            return

        groups = [
            {
                "title": "Pricing",
                "rows": [
                    {"item": "Margin", "value": f"{margin:.0%}",
                     "why": "The brief says margin about 25%; I treat it as a gross margin, so price = cost / (1 - 25%), not cost x 1.25."},
                    {"item": "Volume tiers", "value": " · ".join(f"{qty}+ pcs → {rate:.0%}" for qty, rate in tiers),
                     "why": "The brief says 5% from 500 and up to 8% from 1,000. Applied per line, from that line's quantity."},
                    {"item": "Setup cost", "value": f"{setup:,.0f} MYR per line",
                     "why": "Spread over the order quantity; if the quantity is unknown the line is held."},
                    {"item": "Quotation validity", "value": "30 days",
                     "why": "The brief lists validity as 30 days; written into the PDF and the reply."},
                ],
            },
            {
                "title": "Approval policy",
                "rows": [
                    {"item": "Amount threshold", "value": f"{threshold:,.0f} MYR",
                     "why": "The brief only says \"large quotes\". I set a number a manager can defend."},
                    {"item": "Discount ceiling", "value": f"{cap:.0%}",
                     "why": "\"Anything outside the usual discounts\" = above the standard tier, so above 8%."},
                    {"item": "Other triggers", "value": "held lines · source conflicts · low confidence",
                     "why": "If a person must fix or confirm something, the quote cannot be approved on its own."},
                ],
            },
            {
                "title": "Data policy",
                "rows": [
                    {"item": "Missing value", "value": "hold, never guess",
                     "why": "A wrong price costs more than a line that waits for a person."},
                    {"item": "Source authority", "value": "drawing > spreadsheet > email > model",
                     "why": "The brief says the files are the source of truth; the controlled drawing outranks a typed summary."},
                    {"item": "Confidence weights",
                     "value": " · ".join(f"{k} {v:.2f}" for k, v in weights.items()),
                     "why": "Judgement, not trained. Agreement only counts across different documents, never twice from the same file."},
                ],
            },
        ]
        self._send(200, json.dumps({"groups": groups}, ensure_ascii=False).encode("utf-8"), "application/json")

    def _costs(self) -> None:
        """算一份报价的成本：CloudWatch 实测调用量 + 公开单价。"""
        from datetime import datetime, timedelta, timezone

        import boto3

        try:
            session = boto3.Session(profile_name=PROFILE, region_name=REGION)
            cloudwatch = session.client("cloudwatch")
            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=24)

            def metric(name: str) -> dict:
                response = cloudwatch.get_metric_statistics(
                    Namespace="AWS/Lambda",
                    MetricName=name,
                    Dimensions=[{"Name": "FunctionName", "Value": LAMBDA_FUNCTION}],
                    StartTime=start,
                    EndTime=end,
                    Period=86400,
                    Statistics=["Average", "Maximum", "Sum", "SampleCount"],
                )
                points = response.get("Datapoints") or []
                return points[0] if points else {}

        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return

        duration = metric("Duration")
        invocations = metric("Invocations")

        lambda_gb_seconds = (
            USAGE["lambda_seconds"] + USAGE["render_calls"] * USAGE["render_seconds"]
        ) * RATE["lambda_memory_gb"]

        items = [
            {
                "name": "AgentCore Memory",
                "detail": f"{USAGE['memory_events']} events per quote",
                "usd": round(USAGE["memory_events"] * RATE["memory_per_event"], 6),
            },
            {
                "name": "Model (one fallback call)",
                "detail": f"{USAGE['model_in_tokens']} in / {USAGE['model_out_tokens']} out tokens",
                "usd": round(
                    USAGE["model_in_tokens"] / 1e6 * RATE["model_in_per_mtok"]
                    + USAGE["model_out_tokens"] / 1e6 * RATE["model_out_per_mtok"],
                    6,
                ),
            },
            {
                "name": "AgentCore Runtime",
                "detail": f"{USAGE['runtime_seconds']} s active, 1 vCPU / 2 GB",
                "usd": round(
                    USAGE["runtime_seconds"] / 3600 * USAGE["runtime_vcpu"] * RATE["runtime_vcpu_hour"]
                    + USAGE["runtime_seconds"] / 3600 * USAGE["runtime_gb"] * RATE["runtime_gb_hour"],
                    6,
                ),
            },
            {
                "name": "Lambda",
                "detail": f"{lambda_gb_seconds:.1f} GB-seconds",
                "usd": round(lambda_gb_seconds * RATE["lambda_gb_second"], 6),
            },
            {
                "name": "S3",
                "detail": f"{USAGE['s3_ops']} requests",
                "usd": 0.00002,
            },
        ]
        total = round(sum(item["usd"] for item in items), 6)

        payload = {
            "items": items,
            "total_usd": total,
            "total_cny": round(total * 7.1, 4),
            "per_document_cny_fen": round(total * 7.1 * 100, 3),
            "measured": {
                "invocations": int(invocations.get("SampleCount") or 0),
                "avg_ms": round(float(duration.get("Average") or 0), 1),
                "max_ms": round(float(duration.get("Maximum") or 0), 1),
                "window_hours": 24,
            },
            "rates": RATE,
            "usage": USAGE,
        }
        self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

    def _traces(self) -> None:
        """最近调用：Runtime 的完成日志 + Lambda 的 REPORT 行 + 最后一次报价的推导链。"""
        from datetime import datetime, timedelta, timezone

        import time as _time

        import boto3

        try:
            session = boto3.Session(profile_name=PROFILE, region_name=REGION)
            logs = session.client("logs")
            start_ms = int((_time.time() - 3 * 3600) * 1000)

            def events(group: str, pattern: str, limit: int) -> list[dict]:
                response = logs.filter_log_events(
                    logGroupName=group,
                    startTime=start_ms,
                    filterPattern=pattern,
                    limit=limit,
                    interleaved=True,
                )
                return response.get("events") or []

            runtime_events = events(RUNTIME_LOG_GROUP, '"Invocation completed"', 40)
            lambda_events = events(LAMBDA_LOG_GROUP, "REPORT", 60)
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return

        runs = []
        for event in runtime_events:
            message = event.get("message") or ""
            try:
                body = json.loads(message)
            except Exception:  # noqa: BLE001
                continue
            text = body.get("message") or ""
            seconds = None
            if "(" in text and text.endswith("s)"):
                try:
                    seconds = float(text[text.rindex("(") + 1 : -2])
                except ValueError:
                    seconds = None
            runs.append({
                "at": datetime.fromtimestamp(event["timestamp"] / 1000, timezone.utc).astimezone().strftime("%H:%M:%S"),
                "session": body.get("sessionId", ""),
                "request": body.get("requestId", ""),
                "seconds": seconds,
                "message": text,
            })
        runs.reverse()

        lambdas = []
        for event in lambda_events[-40:]:
            message = event.get("message") or ""
            duration = None
            billed = None
            memory = None
            for part in message.split("	"):
                if part.startswith("Duration:"):
                    duration = part.split(":")[1].strip().split(" ")[0]
                elif part.startswith("Billed Duration:"):
                    billed = part.split(":")[1].strip().split(" ")[0]
                elif part.startswith("Max Memory Used:"):
                    memory = part.split(":")[1].strip().split(" ")[0]
                elif part.startswith("Memory Size:"):
                    memory = memory or part.split(":")[1].strip().split(" ")[0]
            lambdas.append({
                "at": datetime.fromtimestamp(event["timestamp"] / 1000, timezone.utc).astimezone().strftime("%H:%M:%S"),
                "duration_ms": duration,
                "billed_ms": billed,
                "memory": memory,
                "raw": message[:160],
            })

        quote = LAST_QUOTE or {}
        lines = []
        for line in (quote.get("lines") or [])[:3]:
            lines.append({
                "part_no": line.get("part_no"),
                "unit_price": line.get("unit_price"),
                "line_total": line.get("line_total"),
                "trace": line.get("trace") or [],
            })

        payload = {
            "history": TRACE_HISTORY[:20],
            "runtime": runs[:15],
            "lambda": lambdas[-12:],
            "quote": {
                "rfq_no": quote.get("rfq_no"),
                "quote_no": quote.get("quote_no"),
                "total": quote.get("total"),
                "lines": lines,
            },
            "log_groups": {"runtime": RUNTIME_LOG_GROUP, "lambda": LAMBDA_LOG_GROUP},
        }
        self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

    def _get_prices(self) -> None:
        try:
            result = self._gateway_tool("tools___get_prices", {"prices": True})
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")

    def _list_approvals(self) -> None:
        try:
            result = self._gateway_tool("tools___list_approvals", {"list_approvals": True, "limit": 50})
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")

    def _gateway_tool(self, tool: str, arguments: dict) -> dict:
        """经 Gateway 调一个 MCP 工具（SigV4 签名）。"""
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        body = json.dumps({"jsonrpc": "2.0", "id": "1", "method": "tools/call",
                           "params": {"name": tool, "arguments": arguments}}).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        request = AWSRequest(method="POST", url=GATEWAY_URL, data=body, headers=headers)
        credentials = boto3.Session(profile_name=PROFILE, region_name=REGION).get_credentials().get_frozen_credentials()
        SigV4Auth(credentials, "bedrock-agentcore", REGION).add_auth(request)
        http = urlrequest.Request(GATEWAY_URL, data=body, headers=dict(request.headers))
        with urlrequest.urlopen(http, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if "error" in payload:
            raise RuntimeError(f"gateway error: {payload['error']}")
        return json.loads(payload["result"]["content"][0]["text"])

    def _list_emails(self) -> None:
        """列 S3 里的邮件（走 Gateway 的 list_emails 工具，保持和 agent 同一条路）。"""
        try:
            result = self._gateway_tool("tools___list_emails", {"prefix": "inbox/"})
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")

    def _preview_attachments(self) -> None:
        # 把一封邮件的附件内容解析出来，作为报价的证据
        query = parse_qs(urlparse(self.path).query)
        key = (query.get("key") or [""])[0]
        if not key:
            self._send(400, json.dumps({"error": "key is required"}).encode(), "application/json")
            return
        try:
            result = self._gateway_tool("tools___preview_attachments", {"key": key, "preview": True, "max_rows": 40})
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")

    def _read_email(self) -> None:
        # 读一封邮件的信封 + 正文（收件箱详情页用）
        query = parse_qs(urlparse(self.path).query)
        key = (query.get("key") or [""])[0]
        if not key:
            self._send(400, json.dumps({"error": "key is required"}).encode(), "application/json")
            return
        try:
            result = self._gateway_tool("tools___read_email", {"key": key, "read": True})
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")

    def _reprice(self) -> None:
        # 按新的折扣重算报价（利润、毛利率、审批影响都来自同一套定价代码）
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:  # noqa: BLE001
            self._send(400, json.dumps({"error": f"bad request: {exc}"}).encode(), "application/json")
            return

        quote = payload.get("quote")
        if not isinstance(quote, dict):
            self._send(400, json.dumps({"error": "quote is required"}).encode(), "application/json")
            return

        try:
            result = self._gateway_tool("tools___reprice_quote", {
                "quote": quote,
                "discount_rate": float(payload.get("discount_rate") or 0.0),
            })
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return

        # 折扣变了，回信正文也要跟着变：用同一份新报价重新渲染回信
        try:
            updated = dict(quote)
            updated["total"] = result.get("total", quote.get("total"))
            updated["approval"] = result.get("approval", quote.get("approval"))
            updated["proposed_discount"] = result.get("discount_rate", payload.get("discount_rate"))
            by_part = {line["part_no"]: line for line in result.get("lines", [])}
            updated["lines"] = [
                ({**line, "unit_price": by_part[line["part_no"]]["unit_price"],
                  "line_total": by_part[line["part_no"]]["line_total"],
                  "discount_rate": by_part[line["part_no"]].get("discount_rate")}
                 if line.get("part_no") in by_part else line)
                for line in quote.get("lines", [])
            ]
            reply = self._gateway_tool("tools___render_reply", {"quote": updated})
            result["reply_email"] = reply.get("reply_email") or reply.get("reply") or ""
        except Exception as exc:  # noqa: BLE001
            result["reply_error"] = f"{type(exc).__name__}: {exc}"

        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")

    def _regenerate(self) -> None:
        """按当前折扣重新生成报价单与复核清单。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:  # noqa: BLE001
            self._send(400, json.dumps({"error": f"bad request: {exc}"}).encode(), "application/json")
            return

        quote = payload.get("quote")
        if not isinstance(quote, dict):
            self._send(400, json.dumps({"error": "quote is required"}).encode(), "application/json")
            return

        status = "pending_manager" if (quote.get("approval") or {}).get("required") else "not_required"
        result: dict = {"discount_rate": float(payload.get("discount_rate") or 0.0)}
        for tool, args, key in (
            ("tools___render_quote_pdf", {"quote": quote, "output": "pdf"}, "pdf_url"),
            ("tools___render_review_pdf", {"quote": quote, "output": "review",
                                           "approval_status": status}, "review_url"),
        ):
            try:
                rendered = self._gateway_tool(tool, args)
                result[key] = rendered.get("pdf_url", "")
                if key == "pdf_url":
                    result["pdf_bytes"] = rendered.get("bytes", 0)
            except Exception as exc:  # noqa: BLE001
                result[f"{key}_error"] = f"{type(exc).__name__}: {exc}"
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")

    def _submit_approval(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:  # noqa: BLE001
            self._send(400, json.dumps({"error": f"bad request: {exc}"}).encode(), "application/json")
            return
        quote = payload.get("quote")
        if not isinstance(quote, dict):
            self._send(400, json.dumps({"error": "quote is required"}).encode(), "application/json")
            return
        try:
            result = self._gateway_tool("tools___submit_approval", {
                "quote": quote,
                "submit": True,
                "requested_by": payload.get("requested_by") or "sales",
                "discount_rate": float(payload.get("discount_rate") or 0.0),
            })
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return

        # 提交审批时把"这一版"的报价单 / 复核清单 / 回信一起生成，避免文件与提交内容不一致
        for tool, args, key in (
            ("tools___render_quote_pdf", {"quote": quote, "output": "pdf"}, "pdf_url"),
            ("tools___render_review_pdf", {"quote": quote, "output": "review",
                                           "approval_status": "pending_manager"}, "review_url"),
            ("tools___render_reply", {"quote": quote}, "reply_email"),
        ):
            try:
                rendered = self._gateway_tool(tool, args)
                if key == "reply_email":
                    result["reply_email"] = rendered.get("reply_email", "")
                    result["quote_text"] = rendered.get("quote_text", "")
                else:
                    result[key] = rendered.get("pdf_url", "")
            except Exception as exc:  # noqa: BLE001
                result[f"{key}_error"] = f"{type(exc).__name__}: {exc}"

        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")

    def _decide_approval(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:  # noqa: BLE001
            self._send(400, json.dumps({"error": f"bad request: {exc}"}).encode(), "application/json")
            return
        try:
            result = self._gateway_tool("tools___decide_approval", {
                "s3_key": payload.get("s3_key"),
                "decision": payload.get("decision"),
                "decided_by": payload.get("decided_by") or "sales manager",
            })
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/reprice":
            self._reprice()
            return
        if self.path == "/api/regenerate":
            self._regenerate()
            return
        if self.path == "/api/approve":
            self._submit_approval()
            return
        if self.path == "/api/decision":
            self._decide_approval()
            return
        if self.path != "/api/quote":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:  # noqa: BLE001
            self._send(400, json.dumps({"error": f"bad request: {exc}"}).encode(), "application/json")
            return

        if not payload.get("body_text") and not payload.get("email_key"):
            self._send(400, json.dumps({"error": "body_text or email_key is required"}).encode(), "application/json")
            return

        import time

        started = time.time()
        try:
            if payload.get("email_key"):
                request_payload = {"email_key": payload["email_key"]}
                if payload.get("mode"):
                    request_payload["mode"] = payload["mode"]
                # 勾选式选择：正文 + 指定附件
                if payload.get("include_body") is not None:
                    request_payload["include_body"] = bool(payload["include_body"])
                if payload.get("include_attachments") is not None:
                    request_payload["include_attachments"] = list(payload["include_attachments"])
            else:
                request_payload = {
                    "rfq_no": payload.get("rfq_no") or "RFQ-UNKNOWN",
                    "customer": payload.get("customer") or "",
                    "body_text": payload["body_text"],
                }
            result = invoke_agent(request_payload)
            if isinstance(result, dict) and isinstance(result.get("quote"), dict):
                global LAST_QUOTE
                LAST_QUOTE = result["quote"]
                from datetime import datetime as _dt
                TRACE_HISTORY.insert(0, {
                    "at": _dt.now().strftime("%H:%M:%S"),
                    "rfq_no": LAST_QUOTE.get("rfq_no"),
                    "total": LAST_QUOTE.get("total"),
                    "elapsed_ms": result.get("elapsed_ms"),
                    "model_usage": LAST_QUOTE.get("model_usage"),
                    "tool_calls": result.get("tool_calls") or [],
                    "lines": [
                        {"part_no": l.get("part_no"), "unit_price": l.get("unit_price"),
                         "line_total": l.get("line_total"), "trace": l.get("trace") or []}
                        for l in (LAST_QUOTE.get("lines") or [])[:4]
                    ],
                })
                del TRACE_HISTORY[20:]
        except Exception as exc:  # noqa: BLE001
            self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
            return

        result["elapsed_ms"] = int((time.time() - started) * 1000)
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Quotation UI: http://127.0.0.1:{PORT}  (runtime {RUNTIME_ARN.split('/')[-1]})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
