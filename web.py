import logging
import time
from pathlib import Path

from flask import Flask, render_template_string, redirect, url_for, request, flash, jsonify

from db import list_orders, delete_order, toggle_star, upsert_order_with_pdf, add_links, update_notes
from delete_utils import move_to_trash
from checks_runner import run_checks_once

ROOT = Path(__file__).resolve().parent
TRASH_ROOT = ROOT / "storage" / "_TRASH"

# Rate-limit manual refreshes (in-memory; per running instance)
_REFRESH_COOLDOWN_SECONDS = 5 * 60
_last_manual_refresh = 0.0

logger = logging.getLogger(__name__)

TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ALS DODA Tracker</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg:        #0D2137;
      --card:      #112A40;
      --accent:    #0066CC;
      --highlight: #00AAFF;
      --green:     #00C853;
      --red:       #FF3B30;
      --amber:     #FFB300;
      --text:      #FFFFFF;
      --muted:     #A0AEC0;
      --border:    rgba(0, 170, 255, 0.12);
      --border-hi: rgba(0, 170, 255, 0.35);
      --shadow:    0 8px 32px rgba(0, 0, 0, 0.35);
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      font-size: 14px;
    }

    /* ── SCROLLBAR ─────────────────────────────── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(0,170,255,.25); border-radius: 3px; }

    /* ── HEADER ────────────────────────────────── */
    .header {
      background: var(--card);
      border-bottom: 1px solid var(--border);
      padding: 0 32px;
      height: 60px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 100;
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
    }

    .brand { display: flex; align-items: center; gap: 12px; }

    .brand-badge {
      background: var(--accent);
      border-radius: 8px;
      padding: 5px 10px;
      font-size: 13px;
      font-weight: 800;
      color: #fff;
      letter-spacing: 0.5px;
    }

    .brand-name { font-size: 16px; font-weight: 800; letter-spacing: -0.3px; }
    .brand-name span { color: var(--highlight); }

    .header-right { display: flex; align-items: center; gap: 16px; }

    .refresh-meta { font-size: 12px; color: var(--muted); white-space: nowrap; }

    /* ── MAIN ──────────────────────────────────── */
    .main { max-width: 1280px; margin: 0 auto; padding: 28px 24px 48px; }

    /* ── FLASH ─────────────────────────────────── */
    .flash {
      border-radius: 8px; padding: 12px 16px; margin-bottom: 20px;
      font-size: 13px; font-weight: 500; display: flex; align-items: center; gap: 8px;
    }
    .flash-ok  { background: rgba(0,200,83,.12);  border: 1px solid rgba(0,200,83,.3);  color: #4ade80; }
    .flash-err { background: rgba(255,59,48,.12); border: 1px solid rgba(255,59,48,.3); color: #ff7068; }

    /* ── DROP ZONE ─────────────────────────────── */
    .drop-zone-wrapper { margin-bottom: 24px; }

    .drop-zone {
      border: 2px dashed var(--border-hi);
      border-radius: 8px;
      padding: 32px 24px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
      cursor: pointer;
      transition: border-color 0.2s ease, background 0.2s ease;
      background: rgba(0, 102, 204, 0.04);
      text-align: center;
      user-select: none;
    }

    .drop-zone:hover, .drop-zone.dragover {
      border-color: var(--highlight);
      background: rgba(0, 170, 255, 0.07);
    }

    .drop-icon { width: 40px; height: 40px; color: var(--highlight); opacity: 0.75; }

    .drop-title { font-size: 15px; font-weight: 600; }
    .drop-browse { color: var(--highlight); font-weight: 700; }
    .drop-sub { font-size: 12px; color: var(--muted); }

    /* ── UPLOAD SPLIT ──────────────────────────── */
    .upload-split { display: none; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
    .upload-split.active { display: grid; }

    .form-panel {
      background: var(--card); border: 1px solid var(--border); border-radius: 8px;
      padding: 24px; display: flex; flex-direction: column; gap: 20px;
    }

    .form-panel-header {
      font-size: 14px; font-weight: 700; padding-bottom: 16px;
      border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px;
    }

    .file-chip {
      display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
      color: var(--highlight); font-weight: 500; background: rgba(0,170,255,0.1);
      border: 1px solid rgba(0,170,255,0.2); padding: 6px 10px; border-radius: 6px;
      word-break: break-all;
    }

    .form-group { display: flex; flex-direction: column; gap: 6px; }

    .form-label {
      font-size: 11px; font-weight: 700; color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.06em;
    }

    .form-input, .form-select {
      background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 8px;
      color: var(--text); padding: 10px 14px; font-size: 14px; font-family: inherit;
      outline: none; transition: border-color 0.2s; width: 100%;
    }
    .form-input::placeholder { color: var(--muted); opacity: 0.7; }
    .form-input:focus, .form-select:focus { border-color: var(--highlight); }
    .form-input.err { border-color: var(--red); }
    .form-select { cursor: pointer; }
    .form-select option { background: #1a2a3a; color: var(--text); }

    .form-error { font-size: 11px; color: var(--red); display: none; margin-top: 2px; }
    .form-error.show { display: block; }

    .id-row { display: grid; grid-template-columns: 130px 1fr; gap: 8px; }
    .id-row .form-select { width: auto; }

    .submit-btn {
      background: var(--accent); color: #fff; border: none; border-radius: 8px;
      padding: 12px 24px; font-size: 15px; font-weight: 700; font-family: inherit;
      cursor: pointer; transition: background 0.2s, transform 0.1s; width: 100%;
    }
    .submit-btn:hover  { background: var(--highlight); }
    .submit-btn:active { transform: scale(0.98); }

    .change-btn {
      background: transparent; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px;
      color: var(--muted); padding: 9px 14px; font-size: 13px; font-family: inherit;
      cursor: pointer; transition: border-color 0.2s, color 0.2s; width: 100%;
    }
    .change-btn:hover { border-color: var(--red); color: var(--red); }

    .preview-panel {
      background: var(--card); border: 1px solid var(--border); border-radius: 8px;
      overflow: hidden; min-height: 520px;
    }
    .preview-panel iframe { width: 100%; height: 100%; min-height: 520px; border: none; display: block; }

    /* ── DASHBOARD CARD ────────────────────────── */
    .dash-card {
      background: var(--card); border: 1px solid var(--border);
      border-radius: 8px; overflow: hidden; box-shadow: var(--shadow);
    }

    /* ── TOOLBAR ───────────────────────────────── */
    .toolbar {
      display: flex; gap: 12px; align-items: center; justify-content: space-between;
      flex-wrap: wrap; padding: 14px 20px; border-bottom: 1px solid var(--border);
    }
    .tl { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .tr { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

    .icon-btn {
      display: inline-flex; align-items: center; justify-content: center;
      width: 36px; height: 36px; border-radius: 8px; border: 1px solid var(--border);
      background: transparent; cursor: pointer; color: var(--muted);
      transition: border-color 0.2s, color 0.2s, background 0.2s;
      text-decoration: none; flex-shrink: 0;
    }
    .icon-btn svg { width: 16px; height: 16px; fill: currentColor; pointer-events: none; }
    .icon-btn:hover {
      border-color: var(--highlight); color: var(--highlight);
      background: rgba(0,170,255,0.08);
    }
    .icon-btn-del:hover {
      border-color: var(--red); color: var(--red); background: rgba(255,59,48,0.08);
    }

    .sort-sel, .search-inp {
      background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 8px;
      color: var(--text); padding: 8px 12px; font-size: 13px; font-family: inherit;
      outline: none; transition: border-color 0.2s;
    }
    .sort-sel { cursor: pointer; }
    .sort-sel option { background: #1a2a3a; }
    .search-inp { min-width: 220px; }
    .search-inp::placeholder { color: var(--muted); opacity: 0.7; }
    .search-inp:focus { border-color: var(--highlight); }

    .export-btn {
      display: inline-flex; align-items: center; gap: 6px; background: transparent;
      border: 1px solid var(--border); border-radius: 8px; color: var(--muted);
      padding: 8px 12px; font-size: 13px; font-family: inherit; cursor: pointer;
      transition: border-color 0.2s, color 0.2s, background 0.2s; white-space: nowrap;
    }
    .export-btn:hover {
      border-color: var(--highlight); color: var(--highlight); background: rgba(0,170,255,0.08);
    }
    .export-btn svg { width: 14px; height: 14px; fill: currentColor; }

    /* ── FILTER BAR ────────────────────────────── */
    .filter-bar {
      display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
      padding: 10px 20px; border-bottom: 1px solid var(--border);
    }

    .filter-btn {
      padding: 4px 14px; border-radius: 999px; font-size: 12px; font-weight: 700;
      border: 1px solid transparent; cursor: pointer; background: rgba(255,255,255,0.05);
      color: var(--muted); font-family: inherit; transition: all 0.15s; white-space: nowrap;
    }
    .filter-btn:hover { border-color: var(--border-hi); color: var(--text); }

    .filter-all.on   { background: rgba(0,170,255,0.15); border-color: rgba(0,170,255,0.4); color: var(--highlight); }
    .filter-verde.on { background: rgba(0,200,83,0.15);  border-color: rgba(0,200,83,0.4);  color: #3ddc84; }
    .filter-rojo.on  { background: rgba(255,59,48,0.15); border-color: rgba(255,59,48,0.4); color: #ff7068; }
    .filter-pend.on  { background: rgba(255,179,0,0.15); border-color: rgba(255,179,0,0.4); color: #fbbf24; }

    .showing-info { font-size: 12px; color: var(--muted); margin-left: auto; white-space: nowrap; }

    /* ── TABLE ─────────────────────────────────── */
    table { width: 100%; border-collapse: collapse; }

    thead th {
      padding: 10px 16px; font-size: 11px; font-weight: 700; color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.08em; text-align: left;
      background: var(--card); border-bottom: 1px solid var(--border);
    }

    tbody tr { border-bottom: 1px solid var(--border); transition: background 0.15s; }
    tbody tr:last-child { border-bottom: none; }
    tbody tr:hover { background: rgba(0,170,255,0.04); }

    tbody tr.st-verde   { box-shadow: inset 4px 0 0 var(--green); }
    tbody tr.st-rojo    { box-shadow: inset 4px 0 0 var(--red); }
    tbody tr.st-pending { box-shadow: inset 4px 0 0 var(--amber); }

    td { padding: 12px 16px; vertical-align: middle; }

    .order-no  { font-size: 14px; font-weight: 800; letter-spacing: 0.02em; }
    .trailer-no { font-size: 13px; font-weight: 600; color: var(--muted); font-variant-numeric: tabular-nums; }

    /* ── BADGES + PULSE ────────────────────────── */
    @keyframes pulse-rojo {
      0%, 100% { box-shadow: 0 0 0 0 rgba(255,112,104,0); }
      50%       { box-shadow: 0 0 7px 2px rgba(255,112,104,0.4); }
    }
    @keyframes pulse-amber {
      0%, 100% { box-shadow: 0 0 0 0 rgba(251,191,36,0); }
      50%       { box-shadow: 0 0 7px 2px rgba(251,191,36,0.4); }
    }

    .badge {
      display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px;
      border-radius: 999px; font-size: 11px; font-weight: 800; letter-spacing: 0.05em; white-space: nowrap;
    }
    .badge::before {
      content: ''; display: inline-block; width: 6px; height: 6px;
      border-radius: 50%; background: currentColor; flex-shrink: 0;
    }

    .b-verde   { background: rgba(0,200,83,0.14);  color: #3ddc84; border: 1px solid rgba(0,200,83,0.32); }
    .b-rojo    { background: rgba(255,59,48,0.14);  color: #ff7068; border: 1px solid rgba(255,59,48,0.32);  animation: pulse-rojo  2.5s ease-in-out infinite; }
    .b-pending { background: rgba(255,179,0,0.14);  color: #fbbf24; border: 1px solid rgba(255,179,0,0.32);  animation: pulse-amber 2.5s ease-in-out infinite; }

    .status-detail { font-size: 11px; color: var(--muted); margin-top: 4px; line-height: 1.4; }

    /* ── NOTES ─────────────────────────────────── */
    .notes-td { min-width: 140px; max-width: 220px; }

    .notes-view { display: flex; align-items: center; gap: 5px; min-height: 24px; }

    .notes-text {
      font-size: 12px; color: var(--muted); flex: 1;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }

    .note-pencil {
      background: transparent; border: none; cursor: pointer; color: var(--muted);
      padding: 3px; border-radius: 4px; opacity: 0; transition: opacity 0.15s;
      display: inline-flex; align-items: center; flex-shrink: 0;
    }
    .note-pencil svg { width: 12px; height: 12px; fill: currentColor; }
    tbody tr:hover .note-pencil { opacity: 1; }

    .notes-edit-wrap { display: none; align-items: center; gap: 4px; }

    .notes-input {
      background: rgba(255,255,255,0.08); border: 1px solid var(--highlight);
      border-radius: 6px; color: var(--text); padding: 4px 8px; font-size: 12px;
      font-family: inherit; outline: none; flex: 1; min-width: 80px;
    }

    .note-save, .note-cancel {
      background: transparent; border: 1px solid var(--border); border-radius: 6px;
      cursor: pointer; font-size: 12px; padding: 3px 7px; font-family: inherit; flex-shrink: 0;
    }
    .note-save   { color: #3ddc84; border-color: rgba(0,200,83,0.35); }
    .note-cancel { color: #ff7068; border-color: rgba(255,59,48,0.35); }
    .note-save:hover   { background: rgba(0,200,83,0.1); }
    .note-cancel:hover { background: rgba(255,59,48,0.1); }

    /* ── ACTIONS ───────────────────────────────── */
    .actions { display: flex; gap: 6px; justify-content: flex-end; align-items: center; }

    /* ── TABLE FOOTER / PAGINATION ─────────────── */
    .table-footer {
      display: flex; align-items: center; justify-content: flex-end;
      padding: 12px 20px; border-top: 1px solid var(--border);
      gap: 10px; flex-wrap: wrap;
    }

    .page-btn {
      background: transparent; border: 1px solid var(--border); border-radius: 8px;
      color: var(--muted); padding: 6px 14px; font-size: 12px; font-family: inherit;
      cursor: pointer; transition: border-color 0.2s, color 0.2s, background 0.2s;
    }
    .page-btn:hover:not(:disabled) {
      border-color: var(--highlight); color: var(--highlight); background: rgba(0,170,255,0.08);
    }
    .page-btn:disabled { opacity: 0.3; cursor: not-allowed; }
    .page-info { font-size: 12px; color: var(--muted); white-space: nowrap; }

    /* ── EMPTY STATE ───────────────────────────── */
    .empty {
      padding: 56px 24px; text-align: center;
      display: flex; flex-direction: column; align-items: center; gap: 16px;
    }
    .empty-helmet { color: var(--highlight); opacity: 0.5; }
    .empty-title { font-size: 22px; font-weight: 800; color: var(--text); }
    .empty-sub { font-size: 14px; color: var(--muted); }

    /* ── RESPONSIVE ────────────────────────────── */
    @media (max-width: 900px) {
      .upload-split.active { grid-template-columns: 1fr; }
      .preview-panel { display: none; }
    }
    @media (max-width: 640px) {
      .header { padding: 0 16px; }
      .main { padding: 16px 12px 40px; }
      .toolbar { flex-direction: column; align-items: stretch; }
      .tl, .tr { justify-content: space-between; }
      .search-inp { min-width: unset; width: 100%; }
      thead th, td { padding: 10px 12px; }
      .brand-name { display: none; }
      .notes-td { display: none; }
      thead th.notes-col { display: none; }
    }
  </style>
</head>
<body>

  <!-- ════════════ HEADER ════════════ -->
  <header class="header">
    <div class="brand">
      <div class="brand-badge">ALS</div>
      <div class="brand-name">DODA <span>Tracker</span></div>
    </div>
    <div class="header-right">
      <span id="refreshMeta" class="refresh-meta"></span>
    </div>
  </header>

  <!-- ════════════ MAIN ════════════ -->
  <main class="main">

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in messages %}
        <div class="flash {{ 'flash-ok' if cat == 'success' else 'flash-err' }}">
          {% if cat == 'success' %}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
          {% else %}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
          {% endif %}
          {{ msg }}
        </div>
      {% endfor %}
    {% endwith %}

    <!-- ════ DROP ZONE ════ -->
    <div class="drop-zone-wrapper" id="dropWrapper">
      <div class="drop-zone" id="dropZone" role="button" tabindex="0" aria-label="Upload PDF">
        <svg class="drop-icon" viewBox="0 0 64 64" fill="none">
          <circle cx="32" cy="32" r="30" fill="rgba(0,170,255,0.08)" stroke="currentColor" stroke-width="1.5"/>
          <path d="M22 38c-3.31 0-6-2.69-6-6 0-3.09 2.33-5.64 5.35-5.97C22.19 23.18 24.9 21 28 21c1.93 0 3.68.79 4.95 2.05A8 8 0 0148 30c0 4.42-3.58 8-8 8H22z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M32 37v10M28 43l4 4 4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div class="drop-title">Drag &amp; Drop DODA PDF here or <span class="drop-browse">click to browse</span></div>
        <div class="drop-sub">PDF files only &middot; QR codes extracted automatically</div>
        <input type="file" id="fileInput" accept=".pdf" style="display:none" tabindex="-1" />
      </div>
    </div>

    <!-- ════ UPLOAD SPLIT ════ -->
    <div class="upload-split" id="uploadSplit">

      <div class="form-panel">
        <div class="form-panel-header">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--highlight)">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zM14 2v6h6"/>
          </svg>
          Upload DODA PDF
        </div>

        <div class="file-chip" id="fileChip">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zM14 2v6h6"/>
          </svg>
          <span id="fileName"></span>
        </div>

        <form id="uploadForm" method="post" action="{{ url_for('upload_pdf') }}" enctype="multipart/form-data">
          <input type="file" id="realFileInput" name="pdf_file" accept=".pdf" style="display:none" tabindex="-1" />

          <div class="form-group">
            <label class="form-label" for="order_no">Order Number</label>
            <input type="text" id="order_no" name="order_no" class="form-input"
                   placeholder="6-digit order number" maxlength="6" inputmode="numeric" autocomplete="off" />
            <span class="form-error" id="orderErr">Must be exactly 6 digits (numbers only).</span>
          </div>

          <div class="form-group">
            <label class="form-label">Identifier</label>
            <div class="id-row">
              <select name="identifier_type" id="idType" class="form-select">
                <option value="trailer">Trailer</option>
                <option value="plates">Plates</option>
              </select>
              <input type="text" name="identifier_value" id="idValue" class="form-input"
                     placeholder="Enter value" autocomplete="off" />
            </div>
          </div>

          <button type="submit" class="submit-btn">Submit</button>
        </form>

        <button type="button" class="change-btn" id="changeBtn">&#8629; Change file</button>
      </div>

      <div class="preview-panel">
        <iframe id="pdfFrame" title="PDF Preview"></iframe>
      </div>

    </div>

    <!-- ════ DASHBOARD ════ -->
    <div class="dash-card">

      <!-- Toolbar -->
      <div class="toolbar">
        <div class="tl">
          <form method="post" action="{{ url_for('refresh_now') }}" style="margin:0">
            <button class="icon-btn" type="submit" title="Refresh now" aria-label="Refresh now">
              <svg viewBox="0 0 24 24"><path d="M17.65 6.35A7.95 7.95 0 0012 4V1L7 6l5 5V7a5 5 0 11-4.9 6h-2.02A7 7 0 1017.65 6.35z"/></svg>
            </button>
          </form>
          <select id="sort" class="sort-sel" aria-label="Sort">
            <option value="PRIORITY" selected>Priority</option>
            <option value="EVENT_DESC">Event time (latest)</option>
            <option value="ADDED_DESC">Date added (latest)</option>
            <option value="ORDER_ASC">Order (A&rarr;Z)</option>
            <option value="TRAILER_ASC">Trailer (A&rarr;Z)</option>
          </select>
          <button id="exportBtn" class="export-btn" title="Export filtered rows to CSV">
            <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
            Export CSV
          </button>
        </div>
        <div class="tr">
          <input id="q" class="search-inp" placeholder="Search order or trailer&hellip;" aria-label="Search" />
        </div>
      </div>

      <!-- Filter bar -->
      <div class="filter-bar">
        <button class="filter-btn filter-all on" data-f="all">All</button>
        <button class="filter-btn filter-verde" data-f="verde">&#11044; VERDE</button>
        <button class="filter-btn filter-rojo"  data-f="rojo">&#11044; ROJO</button>
        <button class="filter-btn filter-pend"  data-f="pend">&#11044; PENDIENTE</button>
        <span id="showingInfo" class="showing-info"></span>
      </div>

      <!-- Table -->
      <table id="t">
        <thead>
          <tr>
            <th style="width:48px"></th>
            <th style="width:130px">Order</th>
            <th style="width:150px">Trailer / Plates</th>
            <th>Status</th>
            <th class="notes-col" style="width:180px">Notes</th>
            <th style="width:100px; text-align:right">Actions</th>
          </tr>
        </thead>
        <tbody id="tbody">

          {% for o in orders %}
            {% set last_status = '' %}
            {% set last_code = '' %}
            {% set last_label = '' %}
            {% set last_crossed = '' %}
            {% set any_clear = false %}

            {% if o.links|length > 0 %}
              {% set last_status = (o.links[0].last_status or '') %}
              {% if '|' in last_status %}
                {% set parts = last_status.split('|') %}
                {% set last_code    = parts[0].strip() %}
                {% set last_label   = parts[1].strip() if parts|length > 1 else '' %}
                {% set last_crossed = parts[2].strip() if parts|length > 2 else '' %}
              {% else %}
                {% set last_code = last_status %}
              {% endif %}
              {% for l in o.links %}
                {% if l.is_clear %}{% set any_clear = true %}{% endif %}
              {% endfor %}
            {% endif %}

            {% set sk = last_code if last_code else 'PENDING' %}
            {% set et = (o.links[0].last_event_ts if o.links|length > 0 else '') %}

            {% if sk == 'CLEARED' or any_clear %}
              {% set rc = 'st-verde' %}
              {% set grp = 'verde' %}
            {% elif sk == 'MEX_RED' %}
              {% set rc = 'st-rojo' %}
              {% set grp = 'rojo' %}
            {% elif sk == 'MEX_RED_DONE' %}
              {% set rc = 'st-verde' %}
              {% set grp = 'verde' %}
            {% else %}
              {% set rc = 'st-pending' %}
              {% set grp = 'pend' %}
            {% endif %}

            <tr class="row {{ rc }}"
                data-status="{{ sk }}"
                data-order="{{ o.order_no }}"
                data-trailer="{{ o.trailer_no or '' }}"
                data-event="{{ et or '' }}"
                data-added="{{ o.created_at_raw or '' }}"
                data-star="{{ o.starred or 0 }}"
                data-grp="{{ grp }}"
                data-label="{{ last_label }}"
                data-notes="{{ o.notes|e }}">

              <!-- Star -->
              <td style="padding-left:20px">
                <form method="post" action="{{ url_for('toggle_star_route', order_no=o.order_no) }}" style="margin:0">
                  <button class="icon-btn" type="submit" title="{{ 'Unstar' if o.starred else 'Star' }}" aria-label="Toggle star">
                    <svg viewBox="0 0 24 24" style="fill:{{ '#f59e0b' if o.starred else 'var(--muted)' }}">
                      <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/>
                    </svg>
                  </button>
                </form>
              </td>

              <!-- Order -->
              <td><div class="order-no">{{ o.order_no }}</div></td>

              <!-- Trailer -->
              <td><div class="trailer-no">{{ o.trailer_no or '&mdash;' }}</div></td>

              <!-- Status -->
              <td>
                {% if sk == 'CLEARED' or any_clear %}
                  <span class="badge b-verde">VERDE / LIBERADO</span>
                {% elif sk == 'MEX_RED' %}
                  <span class="badge b-rojo">ROJO MEXICANO</span>
                {% elif sk == 'MEX_RED_DONE' %}
                  <span class="badge b-verde">ROJO / LIBERADO</span>
                {% else %}
                  <span class="badge b-pending">PENDIENTE</span>
                {% endif %}
                {% if last_label %}
                  <div class="status-detail">{{ last_label }}{% if last_crossed %} &middot; {{ last_crossed }}{% endif %}</div>
                {% endif %}
              </td>

              <!-- Notes -->
              <td class="notes-td">
                <div class="notes-view">
                  <span class="notes-text">{{ o.notes or '' }}</span>
                  <button class="note-pencil" data-order="{{ o.order_no }}" title="Edit note" aria-label="Edit note">
                    <svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
                  </button>
                </div>
                <div class="notes-edit-wrap">
                  <input type="text" class="notes-input" value="{{ o.notes|e }}" placeholder="Add a note&hellip;" />
                  <button class="note-save" data-order="{{ o.order_no }}" title="Save">&#10003;</button>
                  <button class="note-cancel" title="Cancel">&#10005;</button>
                </div>
              </td>

              <!-- Actions -->
              <td>
                <div class="actions">
                  {% set url = (o.links[0].url if o.links|length > 0 else '') %}
                  {% if url %}
                    <a class="icon-btn" href="{{ url }}" target="_blank" rel="noopener noreferrer" title="Open tracking link">
                      <svg viewBox="0 0 24 24"><path d="M14 3h7v7h-2V6.41l-9.29 9.3-1.42-1.42 9.3-9.29H14V3z"/><path d="M5 5h6v2H7v10h10v-4h2v6H5V5z"/></svg>
                    </a>
                  {% endif %}
                  <form style="margin:0" method="post" action="{{ url_for('delete_order_route', order_no=o.order_no) }}"
                        onsubmit="return confirm('Delete order {{ o.order_no }}?');">
                    <button class="icon-btn icon-btn-del" type="submit" title="Delete" aria-label="Delete">
                      <svg viewBox="0 0 24 24"><path d="M9 3h6l1 2h5v2H3V5h5l1-2zm1 6h2v10h-2V9zm4 0h2v10h-2V9zM7 9h2v10H7V9z"/></svg>
                    </button>
                  </form>
                </div>
              </td>
            </tr>
          {% endfor %}

          {% if orders|length == 0 %}
            <tr id="dbEmptyRow">
              <td colspan="6">
                <div class="empty">
                  <svg class="empty-helmet" width="80" height="80" viewBox="0 0 80 80" fill="none">
                    <path d="M15 50 C15 28 24 14 40 14 C56 14 65 28 65 50" fill="rgba(0,170,255,0.07)" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    <path d="M15 50 L65 50" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    <path d="M15 50 L13 64 Q20 68 28 66 L32 52" stroke="currentColor" stroke-width="2" fill="rgba(0,170,255,0.05)" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M65 50 L67 64 Q60 68 52 66 L48 52" stroke="currentColor" stroke-width="2" fill="rgba(0,170,255,0.05)" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M40 50 L40 62" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    <path d="M20 43 L32 43" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                    <path d="M48 43 L60 43" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                    <path d="M40 14 C37 6 28 3 26 8 C30 10 35 12 40 14 C45 12 50 10 54 8 C52 3 43 6 40 14 Z" fill="rgba(255,179,0,0.2)" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  <div class="empty-title">Let's Go Kill It!</div>
                  <div class="empty-sub">No DODAs being tracked yet &mdash; upload one above.</div>
                </div>
              </td>
            </tr>
          {% endif %}

        </tbody>
      </table>

      <!-- Pagination footer -->
      <div class="table-footer" id="tableFooter" style="display:none">
        <button id="prevBtn" class="page-btn" disabled>&larr; Prev</button>
        <span id="pageInfo" class="page-info">Page 1 of 1</span>
        <button id="nextBtn" class="page-btn">Next &rarr;</button>
      </div>

    </div>

  </main>

  <script>
    /* ══════════ FILE UPLOAD / DRAG & DROP ══════════ */
    const dropWrapper   = document.getElementById('dropWrapper');
    const dropZone      = document.getElementById('dropZone');
    const fileInput     = document.getElementById('fileInput');
    const uploadSplit   = document.getElementById('uploadSplit');
    const pdfFrame      = document.getElementById('pdfFrame');
    const fileName      = document.getElementById('fileName');
    const realFileInput = document.getElementById('realFileInput');
    const changeBtn     = document.getElementById('changeBtn');
    let blobURL = null;

    function showPDF(file) {
      if (!file || !file.name.toLowerCase().endsWith('.pdf')) { alert('Please select a PDF file.'); return; }
      if (blobURL) { URL.revokeObjectURL(blobURL); blobURL = null; }
      blobURL = URL.createObjectURL(file);
      pdfFrame.src = blobURL + '#pagemode=none&navpanes=0&toolbar=1';
      fileName.textContent = file.name;
      const dt = new DataTransfer();
      dt.items.add(file);
      realFileInput.files = dt.files;
      dropWrapper.style.display = 'none';
      uploadSplit.classList.add('active');
    }

    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });
    fileInput.addEventListener('change', (e) => { if (e.target.files[0]) showPDF(e.target.files[0]); });

    ['dragenter', 'dragover'].forEach(ev => dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.add('dragover'); }));
    ['dragleave', 'dragend'].forEach(ev  => dropZone.addEventListener(ev, ()  => dropZone.classList.remove('dragover')));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault(); dropZone.classList.remove('dragover');
      const f = e.dataTransfer.files[0]; if (f) showPDF(f);
    });
    document.addEventListener('dragover', (e) => e.preventDefault());
    document.addEventListener('drop', (e) => {
      e.preventDefault();
      const f = e.dataTransfer.files[0];
      if (f && f.name.toLowerCase().endsWith('.pdf') && !uploadSplit.classList.contains('active')) showPDF(f);
    });

    changeBtn.addEventListener('click', () => {
      uploadSplit.classList.remove('active');
      dropWrapper.style.display = '';
      if (blobURL) { URL.revokeObjectURL(blobURL); blobURL = null; }
      pdfFrame.src = '';
      fileInput.value = '';
      realFileInput.value = '';
      document.getElementById('order_no').value = '';
      document.getElementById('idValue').value = '';
      clearOrderErr();
    });

    /* ══════════ FORM VALIDATION ══════════ */
    const orderInput = document.getElementById('order_no');
    const orderErr   = document.getElementById('orderErr');
    const uploadForm = document.getElementById('uploadForm');

    function clearOrderErr() { orderInput.classList.remove('err'); orderErr.classList.remove('show'); }
    function validateOrder(v) { return /^[0-9]{6}$/.test(v.trim()); }

    orderInput.addEventListener('input', () => {
      const v = orderInput.value;
      if (v.length > 0 && !validateOrder(v)) { orderInput.classList.add('err'); orderErr.classList.add('show'); }
      else clearOrderErr();
    });

    uploadForm.addEventListener('submit', (e) => {
      if (!validateOrder(orderInput.value)) {
        e.preventDefault(); orderInput.classList.add('err'); orderErr.classList.add('show'); orderInput.focus(); return;
      }
      if (!realFileInput.files || !realFileInput.files.length) {
        e.preventDefault(); alert('Please select a PDF file first.');
      }
    });

    /* ══════════ REFRESH COUNTDOWN ══════════ */
    const lastManual = {{ last_manual_refresh|default(0) }};
    function fmtTime(s) { return new Date(s * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }
    function tick() {
      const el = document.getElementById('refreshMeta');
      if (!el) return;
      const now = Math.floor(Date.now() / 1000);
      const rem = lastManual ? Math.max(0, 300 - (now - lastManual)) : 0;
      if (!lastManual) { el.textContent = 'Auto-checks every 15 min \u00b7 Ready to refresh'; }
      else if (rem > 0) { el.textContent = `Last refresh ${fmtTime(lastManual)} \u00b7 Next manual in ${Math.floor(rem/60)}:${String(rem%60).padStart(2,'0')}`; }
      else { el.textContent = `Last refresh ${fmtTime(lastManual)} \u00b7 Ready`; }
    }
    tick(); setInterval(tick, 1000);

    /* ══════════ SEARCH + FILTER + SORT + PAGINATE ══════════ */
    const tbody       = document.getElementById('tbody');
    const allRows     = Array.from(document.querySelectorAll('tr.row'));
    const tableFooter = document.getElementById('tableFooter');

    const PAGE_SIZE = 10;
    let activeSort    = 'PRIORITY';
    let query         = '';
    let activeFilters = new Set();   // empty = All
    let currentPage   = 1;
    let currentList   = [];          // filtered+sorted, used for CSV export

    const epoch    = (iso) => { const t = new Date(iso).getTime(); return isNaN(t) ? 0 : Math.floor(t/1000); };
    const evEpoch  = (r)   => epoch(r.dataset.event || '');
    const addEpoch = (r)   => epoch(r.dataset.added || '');
    const isPending = (r)  => { const s = r.dataset.status || ''; return !s || s==='PENDING' || s==='UNKNOWN' || s==='NOT_PRESENTED'; };
    const isStar    = (r)  => r.dataset.star === '1';

    function apply() {
      const q = query.trim().toLowerCase();

      // 1. Filter by search
      let list = allRows.filter(r => {
        if (!q) return true;
        const hay = (r.dataset.order||'') + ' ' + (r.dataset.trailer||'') + ' ' + (r.dataset.notes||'');
        return hay.toLowerCase().includes(q);
      });

      // 2. Filter by status group
      if (activeFilters.size > 0) {
        list = list.filter(r => activeFilters.has(r.dataset.grp));
      }

      // 3. Sort
      list.sort((a, b) => {
        switch (activeSort) {
          case 'PRIORITY': {
            const s = isStar(b) - isStar(a); if (s) return s;
            const p = isPending(a) - isPending(b); if (p) return p;
            return evEpoch(b) - evEpoch(a);
          }
          case 'EVENT_DESC':  return evEpoch(b)  - evEpoch(a);
          case 'ADDED_DESC':  return addEpoch(b) - addEpoch(a);
          case 'ORDER_ASC':   return (a.dataset.order||'').localeCompare(b.dataset.order||'');
          case 'TRAILER_ASC': return (a.dataset.trailer||'').localeCompare(b.dataset.trailer||'');
          default: return 0;
        }
      });

      currentList = list;
      const total      = list.length;
      const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
      if (currentPage > totalPages) currentPage = 1;

      const start    = (currentPage - 1) * PAGE_SIZE;
      const end      = Math.min(start + PAGE_SIZE, total);
      const pageRows = list.slice(start, end);

      // 4. Update showing info
      const info = document.getElementById('showingInfo');
      if (info) {
        info.textContent = total === 0
          ? 'No orders found'
          : `Showing ${start+1}\u2013${end} of ${total} order${total!==1?'s':''}`;
      }

      // 5. Pagination controls
      if (tableFooter) tableFooter.style.display = total > PAGE_SIZE ? '' : 'none';
      const pi = document.getElementById('pageInfo');
      if (pi) pi.textContent = `Page ${currentPage} of ${totalPages}`;
      const prev = document.getElementById('prevBtn');
      const next = document.getElementById('nextBtn');
      if (prev) prev.disabled = currentPage <= 1;
      if (next) next.disabled = currentPage >= totalPages;

      // 6. Render
      tbody.innerHTML = '';
      if (pageRows.length === 0 && allRows.length > 0) {
        // Orders exist but filters produce no results
        const noMatch = document.createElement('tr');
        noMatch.innerHTML = '<td colspan="6"><div class="empty"><div class="empty-sub" style="padding:32px 0">No orders match your current filters.</div></div></td>';
        tbody.appendChild(noMatch);
      } else {
        pageRows.forEach(r => tbody.appendChild(r));
      }
    }

    document.getElementById('sort')?.addEventListener('change', (e) => { activeSort = e.target.value; currentPage = 1; apply(); });
    document.getElementById('q')?.addEventListener('input',    (e) => { query = e.target.value;       currentPage = 1; apply(); });
    document.getElementById('prevBtn')?.addEventListener('click', () => { currentPage--; apply(); });
    document.getElementById('nextBtn')?.addEventListener('click', () => { currentPage++; apply(); });

    /* ══════════ STATUS FILTER BUTTONS ══════════ */
    document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const f = btn.dataset.f;
        if (f === 'all') {
          activeFilters.clear();
          document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('on'));
          btn.classList.add('on');
        } else {
          document.querySelector('.filter-all').classList.remove('on');
          if (activeFilters.has(f)) {
            activeFilters.delete(f);
            btn.classList.remove('on');
          } else {
            activeFilters.add(f);
            btn.classList.add('on');
          }
          // If nothing selected, revert to All
          if (activeFilters.size === 0) {
            document.querySelector('.filter-all').classList.add('on');
          }
        }
        currentPage = 1;
        apply();
      });
    });

    /* ══════════ EXPORT CSV ══════════ */
    document.getElementById('exportBtn')?.addEventListener('click', () => {
      const headers = ['Order Number', 'Trailer/Plates', 'Status', 'Last Status Text', 'Date Added', 'Notes'];
      const rows = [headers];
      currentList.forEach(r => {
        rows.push([
          r.dataset.order  || '',
          r.dataset.trailer || '',
          r.dataset.status  || '',
          r.dataset.label   || '',
          r.dataset.added   || '',
          r.dataset.notes   || '',
        ]);
      });
      const csv  = rows.map(row => row.map(v => '"' + String(v).replace(/"/g, '""') + '"').join(',')).join('\n');
      const blob = new Blob([csv], { type: 'text/csv' });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = 'doda-tracker-' + new Date().toISOString().slice(0, 10) + '.csv';
      a.click();
      URL.revokeObjectURL(url);
    });

    /* ══════════ NOTES INLINE EDITING ══════════ */
    function openNote(row) {
      row.querySelector('.notes-view').style.display = 'none';
      const wrap = row.querySelector('.notes-edit-wrap');
      wrap.style.display = 'flex';
      const inp = wrap.querySelector('.notes-input');
      inp.value = row.querySelector('.notes-text').textContent;
      inp.focus(); inp.select();
    }

    function closeNote(row) {
      row.querySelector('.notes-edit-wrap').style.display = 'none';
      row.querySelector('.notes-view').style.display = 'flex';
    }

    async function saveNote(row, orderNo) {
      const inp   = row.querySelector('.notes-input');
      const notes = inp.value;
      try {
        const res = await fetch('/notes/' + encodeURIComponent(orderNo), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ notes }),
        });
        if (res.ok) {
          row.querySelector('.notes-text').textContent = notes;
          row.dataset.notes = notes;
        }
      } catch (_) { /* fail silently */ }
      closeNote(row);
    }

    // Event delegation — works after pagination rerenders tbody
    document.addEventListener('click', (e) => {
      const pencil = e.target.closest('.note-pencil');
      if (pencil) { openNote(pencil.closest('tr')); return; }

      const saveBtn = e.target.closest('.note-save');
      if (saveBtn) { saveNote(saveBtn.closest('tr'), saveBtn.dataset.order); return; }

      const cancelBtn = e.target.closest('.note-cancel');
      if (cancelBtn) { closeNote(cancelBtn.closest('tr')); return; }
    });

    document.addEventListener('keydown', (e) => {
      const inp = e.target.closest('.notes-input');
      if (!inp) return;
      const row     = inp.closest('tr');
      const saveBtn = row.querySelector('.note-save');
      if (e.key === 'Enter')  { e.preventDefault(); saveNote(row, saveBtn.dataset.order); }
      if (e.key === 'Escape') { closeNote(row); }
    });

    // Initial render
    apply();
  </script>
</body>
</html>
"""


def create_app():
    app = Flask(__name__)
    app.secret_key = "doda-tracker-secret"

    @app.get("/")
    def index():
        orders = list_orders()
        now = time.time()
        remaining = max(0, int(_REFRESH_COOLDOWN_SECONDS - (now - _last_manual_refresh))) if _last_manual_refresh else 0
        return render_template_string(
            TEMPLATE,
            orders=orders,
            remaining=remaining,
            last_manual_refresh=int(_last_manual_refresh) if _last_manual_refresh else 0,
            just_refreshed=(request.args.get('refreshed') == '1'),
        )

    @app.post("/refresh")
    def refresh_now():
        global _last_manual_refresh
        now = time.time()
        if _last_manual_refresh and (now - _last_manual_refresh) < _REFRESH_COOLDOWN_SECONDS:
            return redirect(url_for("index"))
        _last_manual_refresh = now
        try:
            run_checks_once()
        except Exception:
            pass
        return redirect(url_for("index", refreshed=1))

    @app.post("/upload")
    def upload_pdf():
        from qr_extract import extract_qr_links_from_pdf
        from trailer_extract import extract_trailer_or_plate_from_pdf
        import tempfile

        order_no = (request.form.get("order_no") or "").strip()
        if not order_no:
            flash("Order number is required.", "error")
            return redirect(url_for("index"))

        if not order_no.isdigit() or len(order_no) != 6:
            flash("Order number must be exactly 6 digits.", "error")
            return redirect(url_for("index"))

        uploaded_file = request.files.get("pdf_file")
        if not uploaded_file or uploaded_file.filename == "":
            flash("Please select a PDF file to upload.", "error")
            return redirect(url_for("index"))

        filename = uploaded_file.filename
        if not filename.lower().endswith(".pdf"):
            flash("Only PDF files are accepted.", "error")
            return redirect(url_for("index"))

        identifier_type  = (request.form.get("identifier_type")  or "trailer").strip()
        identifier_value = (request.form.get("identifier_value") or "").strip()

        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
                uploaded_file.save(tmp_path)

            tmp_path = Path(tmp_path)

            links = extract_qr_links_from_pdf(tmp_path)
            if not links:
                no_qr_dir = ROOT / "storage" / "_NO_QR"
                no_qr_dir.mkdir(parents=True, exist_ok=True)
                dest = no_qr_dir / filename
                tmp_path.replace(dest)
                flash(f"No QR code found in '{filename}'. File moved to _NO_QR for review.", "error")
                return redirect(url_for("index"))

            if identifier_value:
                trailer = identifier_value
            else:
                trailer = extract_trailer_or_plate_from_pdf(tmp_path)

            storage_dir = ROOT / "storage" / order_no
            storage_dir.mkdir(parents=True, exist_ok=True)
            dest = storage_dir / filename
            try:
                tmp_path.replace(dest)
            except Exception:
                dest.write_bytes(tmp_path.read_bytes())
                tmp_path.unlink(missing_ok=True)

            order_id = upsert_order_with_pdf(order_no=order_no, pdf_path=str(dest), trailer_no=trailer)
            add_links(order_id, links)

            id_msg = f" ({identifier_type}: {trailer})" if trailer else ""
            flash(f"Order {order_no} added with {len(links)} QR link(s){id_msg}.", "success")

        except Exception as e:
            logger.exception("Upload error for order %s: %s", order_no, e)
            flash(f"Upload failed: {e}", "error")
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

        return redirect(url_for("index"))

    @app.post("/notes/<order_no>")
    def save_notes(order_no: str):
        data  = request.get_json(silent=True) or {}
        notes = str(data.get("notes", "")).strip()
        ok    = update_notes(order_no, notes)
        return jsonify({"ok": ok})

    @app.post("/star/<order_no>")
    def toggle_star_route(order_no: str):
        try:
            toggle_star(order_no)
        except Exception:
            pass
        return redirect(url_for("index"))

    @app.post("/delete/<order_no>")
    def delete_order_route(order_no: str):
        info     = delete_order(order_no)
        pdf_path = info.get("pdf_path")
        try:
            if pdf_path:
                p = Path(pdf_path)
                if p.exists() and p.parent.exists() and p.parent.is_dir():
                    if p.parent.name == str(order_no):
                        move_to_trash(p.parent, TRASH_ROOT)
                    else:
                        move_to_trash(p, TRASH_ROOT)
        except Exception:
            pass
        return redirect(url_for("index"))

    return app
