# -*- coding: utf-8 -*-
import logging
import time
from pathlib import Path

from flask import Flask, render_template_string, redirect, url_for, request, flash, jsonify

from db import list_orders, delete_order, toggle_star, upsert_order_with_pdf, add_links, update_notes
from delete_utils import move_to_trash
from checks_runner import run_checks_once

ROOT = Path(__file__).resolve().parent
TRASH_ROOT = ROOT / "storage" / "_TRASH"

_REFRESH_COOLDOWN_SECONDS = 5 * 60
_last_manual_refresh = 0.0

logger = logging.getLogger(__name__)

TEMPLATE = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ALS DODA Tracker</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <!-- Apply saved theme before CSS renders to prevent flash -->
  <script>(function(){var t=localStorage.getItem('dodaTheme')||'dark';document.documentElement.setAttribute('data-theme',t);})();</script>
  <style>
    /* ── THEME VARIABLES ──────────────────────── */
    :root {
      --bg:        #0D2137;
      --card:      #112A40;
      --accent:    #0066CC;
      --hl:        #00AAFF;
      --green:     #00C853;
      --red:       #FF3B30;
      --amber:     #FFB300;
      --text:      #FFFFFF;
      --muted:     #A0AEC0;
      --bd:        rgba(0,170,255,0.12);
      --bd-hi:     rgba(0,170,255,0.35);
      --shadow:    0 8px 32px rgba(0,0,0,0.35);
      --inp-bg:    rgba(255,255,255,0.05);
      --opt-bg:    #1a2a3a;
    }
    [data-theme="light"] {
      --bg:        #E8F0F7;
      --card:      #D0E4F0;
      --text:      #0D2137;
      --muted:     #4A6B8A;
      --bd:        rgba(13,33,55,0.15);
      --bd-hi:     rgba(0,102,204,0.40);
      --shadow:    0 8px 32px rgba(0,0,0,0.10);
      --inp-bg:    rgba(0,0,0,0.05);
      --opt-bg:    #c0d8ea;
    }

    /* ── RESET ────────────────────────────────── */
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
    body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;font-size:14px;}
    ::-webkit-scrollbar{width:6px;height:6px;}
    ::-webkit-scrollbar-track{background:transparent;}
    ::-webkit-scrollbar-thumb{background:rgba(0,170,255,.25);border-radius:3px;}
    [data-theme="light"] ::-webkit-scrollbar-thumb{background:rgba(13,33,55,.2);}

    /* ── HEADER ───────────────────────────────── */
    .header{background:var(--card);border-bottom:1px solid var(--bd);padding:0 28px;height:60px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:0 4px 24px rgba(0,0,0,0.25);}
    .brand{display:flex;align-items:center;gap:12px;}
    .brand-badge{background:var(--accent);border-radius:8px;padding:5px 10px;font-size:13px;font-weight:800;color:#fff;letter-spacing:.5px;}
    .brand-name{font-size:16px;font-weight:800;letter-spacing:-.3px;}
    .brand-name span{color:var(--hl);}
    .header-right{display:flex;align-items:center;gap:12px;}
    .refresh-meta{font-size:11px;color:var(--muted);white-space:nowrap;}
    .hdr-toggles{display:flex;gap:6px;align-items:center;}
    .hdr-toggle{background:var(--inp-bg);border:1px solid var(--bd);border-radius:6px;color:var(--muted);padding:4px 8px;font-size:11px;font-weight:600;font-family:inherit;cursor:pointer;transition:border-color .15s,color .15s;white-space:nowrap;line-height:1.4;}
    .hdr-toggle:hover{border-color:var(--hl);color:var(--text);}
    .hdr-toggle .on{font-weight:800;color:var(--text);}

    /* ── MAIN ─────────────────────────────────── */
    .main{max-width:1300px;margin:0 auto;padding:24px 20px 48px;}

    /* ── FLASH ────────────────────────────────── */
    .flash{border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:13px;font-weight:500;display:flex;align-items:center;gap:8px;}
    .flash-ok {background:rgba(0,200,83,.12); border:1px solid rgba(0,200,83,.3); color:#4ade80;}
    .flash-err{background:rgba(255,59,48,.12);border:1px solid rgba(255,59,48,.3);color:#ff7068;}

    /* ── DROP ZONE ────────────────────────────── */
    /* CRITICAL: position:relative so overlay input can cover it */
    .drop-zone-wrapper{margin-bottom:20px;}
    .drop-zone{
      position:relative;
      border:2px dashed var(--bd-hi);border-radius:8px;
      padding:22px 24px;
      display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;
      cursor:pointer;background:rgba(0,102,204,0.04);text-align:center;user-select:none;
      transition:border-color .2s,background .2s;
    }
    .drop-zone:hover,.drop-zone.dragover{border-color:var(--hl);background:rgba(0,170,255,0.07);}
    .drop-icon{width:36px;height:36px;color:var(--hl);opacity:.75;pointer-events:none;}
    .drop-title{font-size:15px;font-weight:600;pointer-events:none;}
    .drop-browse{color:var(--hl);font-weight:700;}
    /* Overlay file input covers entire drop zone — clicks naturally open dialog */
    #fileInput{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%;font-size:0;}

    /* ── UPLOAD SPLIT ─────────────────────────── */
    .upload-split{display:none;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:20px;}
    .upload-split.active{display:grid;}
    .form-panel{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:22px;display:flex;flex-direction:column;gap:18px;}
    .form-panel-hdr{font-size:14px;font-weight:700;padding-bottom:14px;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;}
    .file-chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--hl);font-weight:500;background:rgba(0,170,255,.1);border:1px solid rgba(0,170,255,.2);padding:5px 10px;border-radius:6px;word-break:break-all;}
    .form-group{display:flex;flex-direction:column;gap:5px;}
    .form-label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;}
    .form-input,.form-select{background:var(--inp-bg);border:1px solid var(--bd);border-radius:8px;color:var(--text);padding:9px 13px;font-size:14px;font-family:inherit;outline:none;transition:border-color .2s;width:100%;}
    .form-input::placeholder{color:var(--muted);opacity:.7;}
    .form-input:focus,.form-select:focus{border-color:var(--hl);}
    .form-input.err{border-color:var(--red);}
    .form-select{cursor:pointer;}
    .form-select option,.sort-sel option{background:var(--opt-bg);color:var(--text);}
    .form-error{font-size:11px;color:var(--red);display:none;margin-top:2px;}
    .form-error.show{display:block;}
    .id-row{display:grid;grid-template-columns:120px 1fr;gap:8px;}
    .id-row .form-select{width:auto;}
    .submit-btn{background:var(--accent);color:#fff;border:none;border-radius:8px;padding:11px 20px;font-size:15px;font-weight:700;font-family:inherit;cursor:pointer;transition:background .2s,transform .1s;width:100%;}
    .submit-btn:hover{background:var(--hl);}
    .submit-btn:active{transform:scale(.98);}
    .change-btn{background:transparent;border:1px solid rgba(255,255,255,.1);border-radius:8px;color:var(--muted);padding:8px 14px;font-size:13px;font-family:inherit;cursor:pointer;transition:border-color .2s,color .2s;width:100%;}
    .change-btn:hover{border-color:var(--red);color:var(--red);}
    [data-theme="light"] .change-btn{border-color:var(--bd);}
    .preview-panel{background:var(--card);border:1px solid var(--bd);border-radius:8px;overflow:hidden;min-height:480px;}
    .preview-panel iframe{width:100%;height:100%;min-height:480px;border:none;display:block;}

    /* ── DASH CARD ────────────────────────────── */
    .dash-card{background:var(--card);border:1px solid var(--bd);border-radius:8px;overflow:hidden;box-shadow:var(--shadow);}

    /* ── TOOLBAR ──────────────────────────────── */
    .toolbar{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;padding:12px 18px;border-bottom:1px solid var(--bd);}
    .tl,.tr{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
    .icon-btn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:8px;border:1px solid var(--bd);background:transparent;cursor:pointer;color:var(--muted);transition:border-color .2s,color .2s,background .2s;text-decoration:none;flex-shrink:0;}
    .icon-btn svg{width:15px;height:15px;fill:currentColor;pointer-events:none;}
    .icon-btn:hover{border-color:var(--hl);color:var(--hl);background:rgba(0,170,255,.08);}
    .icon-btn-del:hover{border-color:var(--red);color:var(--red);background:rgba(255,59,48,.08);}
    .sort-sel,.search-inp{background:var(--inp-bg);border:1px solid var(--bd);border-radius:8px;color:var(--text);padding:7px 11px;font-size:13px;font-family:inherit;outline:none;transition:border-color .2s;}
    .sort-sel{cursor:pointer;}
    .search-inp{min-width:210px;}
    .search-inp::placeholder{color:var(--muted);opacity:.7;}
    .search-inp:focus{border-color:var(--hl);}
    .export-btn{display:inline-flex;align-items:center;gap:5px;background:transparent;border:1px solid var(--bd);border-radius:8px;color:var(--muted);padding:7px 11px;font-size:12px;font-family:inherit;cursor:pointer;transition:border-color .2s,color .2s,background .2s;white-space:nowrap;}
    .export-btn:hover{border-color:var(--hl);color:var(--hl);background:rgba(0,170,255,.08);}
    .export-btn svg{width:13px;height:13px;fill:currentColor;}

    /* ── FILTER BAR ───────────────────────────── */
    .filter-bar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;padding:9px 18px;border-bottom:1px solid var(--bd);}
    .filter-btn{padding:4px 13px;border-radius:999px;font-size:12px;font-weight:700;border:1px solid transparent;cursor:pointer;background:rgba(255,255,255,.05);color:var(--muted);font-family:inherit;transition:all .15s;white-space:nowrap;}
    [data-theme="light"] .filter-btn{background:rgba(0,0,0,.05);}
    .filter-btn:hover{border-color:var(--bd-hi);color:var(--text);}
    .filter-all.on  {background:rgba(0,170,255,.15);border-color:rgba(0,170,255,.4);color:var(--hl);}
    .filter-verde.on{background:rgba(0,200,83,.15); border-color:rgba(0,200,83,.4); color:#3ddc84;}
    .filter-rojo.on {background:rgba(255,59,48,.15); border-color:rgba(255,59,48,.4); color:#ff7068;}
    .filter-pend.on {background:rgba(255,179,0,.15); border-color:rgba(255,179,0,.4); color:#fbbf24;}
    .showing-info{font-size:12px;color:var(--muted);margin-left:auto;white-space:nowrap;}

    /* ── TABLE ────────────────────────────────── */
    table{width:100%;border-collapse:collapse;}
    thead th{padding:9px 14px;font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;text-align:left;background:var(--card);border-bottom:1px solid var(--bd);}
    tbody tr{border-bottom:1px solid var(--bd);transition:background .15s;}
    tbody tr:last-child{border-bottom:none;}
    tbody tr:hover{background:rgba(0,170,255,.04);}
    [data-theme="light"] tbody tr:hover{background:rgba(0,102,204,.05);}
    tbody tr.st-verde  {box-shadow:inset 4px 0 0 var(--green);}
    tbody tr.st-rojo   {box-shadow:inset 4px 0 0 var(--red);}
    tbody tr.st-pending{box-shadow:inset 4px 0 0 var(--amber);}
    td{padding:11px 14px;vertical-align:middle;}
    .order-no{font-size:14px;font-weight:800;letter-spacing:.02em;}
    .trailer-no{font-size:13px;font-weight:600;color:var(--muted);font-variant-numeric:tabular-nums;}

    /* ── BADGES + PULSE ───────────────────────── */
    @keyframes pulse-red{0%,100%{box-shadow:0 0 0 0 rgba(255,112,104,0);}50%{box-shadow:0 0 7px 3px rgba(255,112,104,.38);}}
    @keyframes pulse-amb{0%,100%{box-shadow:0 0 0 0 rgba(251,191,36,0);}50%{box-shadow:0 0 7px 3px rgba(251,191,36,.38);}}
    @keyframes pulse-ins{0%,100%{box-shadow:0 0 0 0 rgba(255,112,104,0);}50%{box-shadow:0 0 9px 4px rgba(255,112,104,.30);}}
    .badge{display:inline-flex;align-items:center;gap:6px;padding:4px 11px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:.05em;white-space:nowrap;}
    .badge::before{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;background:currentColor;flex-shrink:0;}
    .b-verde{background:rgba(0,200,83,.14);  color:#3ddc84;border:1px solid rgba(0,200,83,.32);}
    .b-rojo {background:rgba(255,59,48,.14); color:#ff7068;border:1px solid rgba(255,59,48,.32); animation:pulse-red 2.5s ease-in-out infinite;}
    .b-pend {background:rgba(255,179,0,.14); color:#fbbf24;border:1px solid rgba(255,179,0,.32); animation:pulse-amb 2.5s ease-in-out infinite;}
    /* Inspeccionado: verde badge with red-tinged glow + siren prefix (no ::before dot — emoji acts as indicator) */
    .b-insp{background:rgba(255,59,48,.08);color:#3ddc84;border:1px solid rgba(255,59,48,.30);animation:pulse-ins 2.5s ease-in-out infinite;}
    .b-insp::before{display:none;}
    .status-detail{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.4;}

    /* ── NOTES ────────────────────────────────── */
    .notes-td{min-width:130px;max-width:210px;}
    .notes-view{display:flex;align-items:center;gap:4px;min-height:22px;}
    .notes-text{font-size:12px;color:var(--muted);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
    .note-pencil{background:transparent;border:none;cursor:pointer;color:var(--muted);padding:2px;border-radius:4px;opacity:0;transition:opacity .15s;display:inline-flex;align-items:center;flex-shrink:0;}
    .note-pencil svg{width:11px;height:11px;fill:currentColor;}
    tbody tr:hover .note-pencil{opacity:1;}
    .notes-edit-wrap{display:none;align-items:center;gap:4px;}
    .notes-input{background:rgba(255,255,255,.08);border:1px solid var(--hl);border-radius:6px;color:var(--text);padding:3px 7px;font-size:12px;font-family:inherit;outline:none;flex:1;min-width:70px;}
    [data-theme="light"] .notes-input{background:rgba(0,0,0,.07);}
    .note-save,.note-cancel{background:transparent;border:1px solid var(--bd);border-radius:6px;cursor:pointer;font-size:12px;padding:2px 6px;font-family:inherit;flex-shrink:0;}
    .note-save{color:#3ddc84;border-color:rgba(0,200,83,.35);}
    .note-cancel{color:#ff7068;border-color:rgba(255,59,48,.35);}
    .note-save:hover{background:rgba(0,200,83,.1);}
    .note-cancel:hover{background:rgba(255,59,48,.1);}

    /* ── ACTIONS ──────────────────────────────── */
    .actions{display:flex;gap:5px;justify-content:flex-end;align-items:center;}

    /* ── PAGINATION ───────────────────────────── */
    .table-footer{display:flex;align-items:center;justify-content:flex-end;padding:10px 18px;border-top:1px solid var(--bd);gap:8px;flex-wrap:wrap;}
    .page-btn{background:transparent;border:1px solid var(--bd);border-radius:8px;color:var(--muted);padding:5px 13px;font-size:12px;font-family:inherit;cursor:pointer;transition:border-color .2s,color .2s,background .2s;}
    .page-btn:hover:not(:disabled){border-color:var(--hl);color:var(--hl);background:rgba(0,170,255,.08);}
    .page-btn:disabled{opacity:.3;cursor:not-allowed;}
    .page-info{font-size:12px;color:var(--muted);white-space:nowrap;}

    /* ── EMPTY STATE ──────────────────────────── */
    .empty{padding:52px 24px;text-align:center;display:flex;flex-direction:column;align-items:center;gap:14px;}
    .empty-helmet{color:var(--hl);opacity:.45;}
    .empty-title{font-size:22px;font-weight:800;color:var(--text);}
    .empty-sub{font-size:14px;color:var(--muted);}

    /* ── RESPONSIVE ───────────────────────────── */
    @media(max-width:900px){.upload-split.active{grid-template-columns:1fr;}.preview-panel{display:none;}}
    @media(max-width:640px){
      .header{padding:0 14px;}.main{padding:14px 10px 40px;}
      .toolbar{flex-direction:column;align-items:stretch;}.tl,.tr{justify-content:space-between;}
      .search-inp{min-width:unset;width:100%;}
      thead th,td{padding:9px 10px;}
      .brand-name{display:none;}
      .notes-td,thead th.notes-col{display:none;}
    }
  </style>
</head>
<body>

<!-- ══ HEADER ══════════════════════════════════ -->
<header class="header">
  <div class="brand">
    <div class="brand-badge">ALS</div>
    <div class="brand-name">DODA <span>Tracker</span></div>
  </div>
  <div class="header-right">
    <span id="refreshMeta" class="refresh-meta"></span>
    <div class="hdr-toggles">
      <button id="langBtn" class="hdr-toggle" title="Toggle language"><span id="lEN">EN</span>&nbsp;/&nbsp;<span id="lES" style="font-weight:800">ES</span></button>
      <button id="themeBtn" class="hdr-toggle" title="Toggle dark/light mode">&#9790;</button>
    </div>
  </div>
</header>

<!-- ══ MAIN ════════════════════════════════════ -->
<main class="main">

  <!-- Flash messages -->
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="flash {{ 'flash-ok' if cat == 'success' else 'flash-err' }}">
        {% if cat == 'success' %}<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
        {% else %}<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>{% endif %}
        {{ msg }}
      </div>
    {% endfor %}
  {% endwith %}

  <!-- ══ FILE INPUT (outside drop zone — prevents click-bubble infinite loop) ══ -->
  <!-- This is the overlay input inside the drop zone; placed here via JS injection -->

  <!-- ══ DROP ZONE ════════════════════════════ -->
  <div class="drop-zone-wrapper" id="dropWrapper">
    <div class="drop-zone" id="dropZone" role="button" tabindex="0" aria-label="Upload PDF">
      <svg class="drop-icon" viewBox="0 0 64 64" fill="none">
        <circle cx="32" cy="32" r="30" fill="rgba(0,170,255,0.08)" stroke="currentColor" stroke-width="1.5"/>
        <path d="M22 38c-3.31 0-6-2.69-6-6 0-3.09 2.33-5.64 5.35-5.97C22.19 23.18 24.9 21 28 21c1.93 0 3.68.79 4.95 2.05A8 8 0 0148 30c0 4.42-3.58 8-8 8H22z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M32 37v10M28 43l4 4 4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <div class="drop-title" id="dropTitle">Arrastra &amp; Suelta tu DODA PDF aqu&iacute; o <span class="drop-browse">haz clic para buscar</span></div>
      <!-- Overlay file input — covers the entire drop zone, triggers dialog on click natively -->
      <input type="file" id="fileInput" accept=".pdf" title="" aria-label="Select PDF">
    </div>
  </div>

  <!-- ══ UPLOAD SPLIT ══════════════════════════ -->
  <div class="upload-split" id="uploadSplit">

    <!-- LEFT: Form panel -->
    <div class="form-panel">
      <div class="form-panel-hdr">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="var(--hl)"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zM14 2v6h6"/></svg>
        <span data-i18n="form_header">Subir DODA PDF</span>
      </div>

      <div class="file-chip">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zM14 2v6h6"/></svg>
        <span id="fileName"></span>
      </div>

      <form id="uploadForm" method="post" action="{{ url_for('upload_pdf') }}" enctype="multipart/form-data">
        <!-- Hidden real file input — populated via DataTransfer from the overlay or dialog -->
        <input type="file" id="realFileInput" name="pdf_file" accept=".pdf" style="display:none" tabindex="-1">

        <div class="form-group">
          <label class="form-label" for="order_no" data-i18n="order_label">N&uacute;mero de Orden</label>
          <input type="text" id="order_no" name="order_no" class="form-input"
                 data-i18n-ph="order_ph" placeholder="N&uacute;mero de 6 d&iacute;gitos"
                 maxlength="6" inputmode="numeric" autocomplete="off" />
          <span class="form-error" id="orderErr" data-i18n="order_err">Debe ser exactamente 6 d&iacute;gitos (solo n&uacute;meros).</span>
        </div>

        <div class="form-group">
          <label class="form-label" data-i18n="id_label">Identificador</label>
          <div class="id-row">
            <select name="identifier_type" id="idType" class="form-select">
              <option value="trailer" data-i18n="opt_trailer">Remolque</option>
              <option value="plates" data-i18n="opt_plates">Placas</option>
            </select>
            <input type="text" name="identifier_value" id="idValue" class="form-input"
                   data-i18n-ph="id_ph" placeholder="Ingresa el valor" autocomplete="off" />
          </div>
        </div>

        <button type="submit" class="submit-btn" data-i18n="submit">Enviar</button>
      </form>

      <button type="button" class="change-btn" id="changeBtn" data-i18n="change_file">&#8629; Cambiar archivo</button>
    </div>

    <!-- RIGHT: PDF preview -->
    <div class="preview-panel">
      <iframe id="pdfFrame" title="PDF Preview"></iframe>
    </div>

  </div>

  <!-- ══ DASHBOARD ════════════════════════════ -->
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
          <option value="PRIORITY" data-i18n="sort_priority">Prioridad</option>
          <option value="EVENT_DESC" data-i18n="sort_event">Evento (m&aacute;s reciente)</option>
          <option value="ADDED_DESC" data-i18n="sort_added">Fecha agregado</option>
          <option value="ORDER_ASC" data-i18n="sort_order">Orden (A&#8594;Z)</option>
          <option value="TRAILER_ASC" data-i18n="sort_trailer">Remolque (A&#8594;Z)</option>
        </select>
        <button id="exportBtn" class="export-btn">
          <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
          <span data-i18n="export_csv">Exportar CSV</span>
        </button>
      </div>
      <div class="tr">
        <input id="q" class="search-inp" data-i18n-ph="search_ph" placeholder="Buscar orden o remolque&hellip;" aria-label="Search" />
      </div>
    </div>

    <!-- Filter bar -->
    <div class="filter-bar">
      <button class="filter-btn filter-all on" data-f="all" data-i18n="filter_all">Todos</button>
      <button class="filter-btn filter-verde" data-f="verde">&#11044; VERDE</button>
      <button class="filter-btn filter-rojo"  data-f="rojo">&#11044; ROJO</button>
      <button class="filter-btn filter-pend"  data-f="pend">&#11044; PENDIENTE</button>
      <span id="showingInfo" class="showing-info"></span>
    </div>

    <!-- Table -->
    <table id="t">
      <thead>
        <tr>
          <th style="width:44px"></th>
          <th style="width:125px" data-i18n="col_order">Orden</th>
          <th style="width:145px" data-i18n="col_trailer">Remolque / Placas</th>
          <th data-i18n="col_status">Estatus</th>
          <th class="notes-col" style="width:170px" data-i18n="col_notes">Notas</th>
          <th style="width:95px;text-align:right" data-i18n="col_actions">Acciones</th>
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

          {% set sk  = last_code if last_code else 'PENDING' %}
          {% set et  = (o.links[0].last_event_ts if o.links|length > 0 else '') %}

          {% if sk == 'CLEARED' or any_clear or sk == 'MEX_RED_DONE' %}
            {% set rc = 'st-verde' %}
            {% set grp = 'verde' %}
          {% elif sk == 'MEX_RED' %}
            {% set rc = 'st-rojo' %}
            {% set grp = 'rojo' %}
          {% else %}
            {% set rc = 'st-pending' %}
            {% set grp = 'pend' %}
          {% endif %}

          {# Inspeccionado: currently verde AND previously had MEX_RED, OR is MEX_RED_DONE #}
          {% set is_insp = (sk == 'MEX_RED_DONE') or (grp == 'verde' and o.had_rojo) %}

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
            <td style="padding-left:18px">
              <form method="post" action="{{ url_for('toggle_star_route', order_no=o.order_no) }}" style="margin:0">
                <button class="icon-btn" type="submit" title="{{ 'Quitar destacado' if o.starred else 'Destacar' }}" aria-label="Toggle star">
                  <svg viewBox="0 0 24 24" style="fill:{{ '#f59e0b' if o.starred else 'var(--muted)' }}">
                    <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/>
                  </svg>
                </button>
              </form>
            </td>

            <!-- Order -->
            <td><div class="order-no">{{ o.order_no }}</div></td>

            <!-- Trailer / Plates -->
            <td><div class="trailer-no">{{ o.trailer_no or '&mdash;' }}</div></td>

            <!-- Status badge -->
            <td>
              {% if is_insp %}
                <span class="badge b-insp" data-badge-type="insp">&#128680; Inspeccionado</span>
              {% elif grp == 'verde' %}
                <span class="badge b-verde" data-badge-type="verde">VERDE / LIBERADO</span>
              {% elif sk == 'MEX_RED' %}
                <span class="badge b-rojo" data-badge-type="rojo">ROJO MEXICANO</span>
              {% else %}
                <span class="badge b-pend" data-badge-type="pend">PENDIENTE</span>
              {% endif %}
              {% if last_label %}
                <div class="status-detail">{{ last_label }}{% if last_crossed %} &middot; {{ last_crossed }}{% endif %}</div>
              {% endif %}
            </td>

            <!-- Notes -->
            <td class="notes-td">
              <div class="notes-view">
                <span class="notes-text">{{ o.notes or '' }}</span>
                <button class="note-pencil" data-order="{{ o.order_no }}" title="Editar nota" aria-label="Editar nota">
                  <svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
                </button>
              </div>
              <div class="notes-edit-wrap">
                <input type="text" class="notes-input" value="{{ o.notes|e }}" data-i18n-ph="notes_ph" placeholder="Agregar nota&hellip;" />
                <button class="note-save" data-order="{{ o.order_no }}" title="Guardar">&#10003;</button>
                <button class="note-cancel" title="Cancelar">&#10005;</button>
              </div>
            </td>

            <!-- Actions -->
            <td>
              <div class="actions">
                {% set lnk = (o.links[0].url if o.links|length > 0 else '') %}
                {% if lnk %}
                  <a class="icon-btn" href="{{ lnk }}" target="_blank" rel="noopener noreferrer" title="Abrir enlace">
                    <svg viewBox="0 0 24 24"><path d="M14 3h7v7h-2V6.41l-9.29 9.3-1.42-1.42 9.3-9.29H14V3z"/><path d="M5 5h6v2H7v10h10v-4h2v6H5V5z"/></svg>
                  </a>
                {% endif %}
                <form style="margin:0" method="post" action="{{ url_for('delete_order_route', order_no=o.order_no) }}"
                      onsubmit="return confirmDel('{{ o.order_no }}')">
                  <button class="icon-btn icon-btn-del" type="submit" title="Eliminar" aria-label="Eliminar">
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
                <svg class="empty-helmet" width="76" height="76" viewBox="0 0 80 80" fill="none">
                  <path d="M14 50C14 28 23 13 40 13 57 13 66 28 66 50" fill="rgba(0,170,255,0.07)" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                  <path d="M14 50L66 50" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                  <path d="M14 50L12 64Q19 68 27 66L31 52" stroke="currentColor" stroke-width="2" fill="rgba(0,170,255,0.05)" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M66 50L68 64Q61 68 53 66L49 52" stroke="currentColor" stroke-width="2" fill="rgba(0,170,255,0.05)" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M40 50L40 62" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                  <path d="M20 42L32 42" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                  <path d="M48 42L60 42" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                  <path d="M40 13C37 5 28 2 26 7 30 9 35 11 40 13 45 11 50 9 54 7 52 2 43 5 40 13Z" fill="rgba(255,179,0,0.22)" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <div class="empty-title" data-i18n="empty_title">&#161;Let&#39;s Go Kill It!</div>
                <div class="empty-sub" data-i18n="empty_sub">No hay DODAs en seguimiento &mdash; sube uno arriba.</div>
              </div>
            </td>
          </tr>
        {% endif %}

      </tbody>
    </table>

    <!-- Pagination footer -->
    <div class="table-footer" id="tableFooter" style="display:none">
      <button id="prevBtn" class="page-btn" disabled data-i18n="prev">&#8592; Anterior</button>
      <span id="pageInfo" class="page-info"></span>
      <button id="nextBtn" class="page-btn" data-i18n="next">Siguiente &#8594;</button>
    </div>

  </div>

</main>

<script>
/* ══════════════════════════════════════════════
   TRANSLATIONS
══════════════════════════════════════════════ */
var T = {
  es: {
    drag_title: 'Arrastra &amp; Suelta tu DODA PDF aqu\u00ed o <span class="drop-browse">haz clic para buscar</span>',
    form_header: 'Subir DODA PDF',
    order_label: 'N\u00famero de Orden', order_ph: 'N\u00famero de 6 d\u00edgitos',
    order_err: 'Debe ser exactamente 6 d\u00edgitos (solo n\u00fameros).',
    id_label: 'Identificador', id_ph: 'Ingresa el valor',
    opt_trailer: 'Remolque', opt_plates: 'Placas',
    submit: 'Enviar', change_file: '\u21a9 Cambiar archivo',
    export_csv: 'Exportar CSV', search_ph: 'Buscar orden o remolque\u2026',
    filter_all: 'Todos',
    col_order: 'Orden', col_trailer: 'Remolque / Placas', col_status: 'Estatus',
    col_notes: 'Notas', col_actions: 'Acciones',
    badge_verde: 'VERDE / LIBERADO', badge_rojo: 'ROJO MEXICANO',
    badge_pend: 'PENDIENTE', badge_insp: '\U0001F6A8 Inspeccionado',
    empty_title: '\u00a1Let\'s Go Kill It!',
    empty_sub: 'No hay DODAs en seguimiento \u2014 sube uno arriba.',
    no_match: 'Ninguna orden coincide con los filtros.',
    notes_ph: 'Agregar nota\u2026',
    prev: '\u2190 Anterior', next: 'Siguiente \u2192',
    sort_priority: 'Prioridad', sort_event: 'Evento (m\u00e1s reciente)',
    sort_added: 'Fecha agregado', sort_order: 'Orden (A\u2192Z)', sort_trailer: 'Remolque (A\u2192Z)',
    showing: 'Mostrando {0}\u2013{1} de {2}', no_found: 'Sin resultados',
    page_of: 'P\u00e1gina {0} de {1}',
    del_confirm: '\u00bfEliminar orden {0}?',
    refresh_ready: 'Verificaciones cada 15 min \u00b7 Listo',
    refresh_last: '\u00daltima actualiz. {0} \u00b7 Siguiente en {1}',
    refresh_ready2: '\u00daltima actualiz. {0} \u00b7 Listo',
  },
  en: {
    drag_title: 'Drag &amp; Drop DODA PDF here or <span class="drop-browse">click to browse</span>',
    form_header: 'Upload DODA PDF',
    order_label: 'Order Number', order_ph: '6-digit order number',
    order_err: 'Must be exactly 6 digits (numbers only).',
    id_label: 'Identifier', id_ph: 'Enter value',
    opt_trailer: 'Trailer', opt_plates: 'Plates',
    submit: 'Submit', change_file: '\u21a9 Change file',
    export_csv: 'Export CSV', search_ph: 'Search order or trailer\u2026',
    filter_all: 'All',
    col_order: 'Order', col_trailer: 'Trailer / Plates', col_status: 'Status',
    col_notes: 'Notes', col_actions: 'Actions',
    badge_verde: 'VERDE / LIBERADO', badge_rojo: 'ROJO MEXICANO',
    badge_pend: 'PENDING', badge_insp: '\uD83D\uDEA8 Inspected',
    empty_title: "Let's Go Kill It!",
    empty_sub: 'No DODAs being tracked yet \u2014 upload one above.',
    no_match: 'No orders match your current filters.',
    notes_ph: 'Add a note\u2026',
    prev: '\u2190 Prev', next: 'Next \u2192',
    sort_priority: 'Priority', sort_event: 'Event time (latest)',
    sort_added: 'Date added (latest)', sort_order: 'Order (A\u2192Z)', sort_trailer: 'Trailer (A\u2192Z)',
    showing: 'Showing {0}\u2013{1} of {2}', no_found: 'No orders found',
    page_of: 'Page {0} of {1}',
    del_confirm: 'Delete order {0}?',
    refresh_ready: 'Auto-checks every 15 min \u00b7 Ready',
    refresh_last: 'Last refresh {0} \u00b7 Next manual in {1}',
    refresh_ready2: 'Last refresh {0} \u00b7 Ready',
  }
};

var lang = localStorage.getItem('dodaLang') || 'es';

function fmt(tpl) {
  var args = Array.prototype.slice.call(arguments, 1);
  return tpl.replace(/\\{(\\d+)\\}/g, function(_, i){ return args[i] !== undefined ? args[i] : ''; });
}

function applyLang(l) {
  lang = l;
  localStorage.setItem('dodaLang', l);
  var t = T[l];
  // data-i18n text
  document.querySelectorAll('[data-i18n]').forEach(function(el){
    var k = el.dataset.i18n;
    if (t[k] !== undefined) el.textContent = t[k];
  });
  // data-i18n-ph placeholders
  document.querySelectorAll('[data-i18n-ph]').forEach(function(el){
    var k = el.dataset.i18nPh;
    if (t[k] !== undefined) el.placeholder = t[k];
  });
  // Drop title (contains HTML)
  var dt = document.getElementById('dropTitle');
  if (dt) dt.innerHTML = t.drag_title;
  // Badges (data-badge-type)
  document.querySelectorAll('[data-badge-type]').forEach(function(el){
    var k = 'badge_' + el.dataset.badgeType;
    if (t[k] !== undefined) el.textContent = t[k];
  });
  // Lang toggle indicator
  document.getElementById('lEN').style.fontWeight = l === 'en' ? '800' : '400';
  document.getElementById('lES').style.fontWeight = l === 'es' ? '800' : '400';
  apply(); // Re-render showing/page info with new lang
}

document.getElementById('langBtn').addEventListener('click', function(){
  applyLang(lang === 'es' ? 'en' : 'es');
});

/* ══════════════════════════════════════════════
   DARK / LIGHT THEME
══════════════════════════════════════════════ */
var theme = localStorage.getItem('dodaTheme') || 'dark';

function applyTheme(t) {
  theme = t;
  localStorage.setItem('dodaTheme', t);
  document.documentElement.setAttribute('data-theme', t);
  document.getElementById('themeBtn').innerHTML = t === 'dark' ? '&#9790;' : '&#9788;';
}

document.getElementById('themeBtn').addEventListener('click', function(){
  applyTheme(theme === 'dark' ? 'light' : 'dark');
});
// Sync button icon on load
document.getElementById('themeBtn').innerHTML = theme === 'dark' ? '&#9790;' : '&#9788;';

/* ══════════════════════════════════════════════
   UPLOAD — CRITICAL FIX
   fileInput is an overlay INSIDE the drop zone.
   The overlay naturally opens the dialog on click.
   For drag-and-drop we intercept drop on the zone,
   call e.preventDefault() + stopPropagation(), then
   use DataTransfer to populate realFileInput.
══════════════════════════════════════════════ */
var fileInput     = document.getElementById('fileInput');
var realFileInput = document.getElementById('realFileInput');
var dropZone      = document.getElementById('dropZone');
var dropWrapper   = document.getElementById('dropWrapper');
var uploadSplit   = document.getElementById('uploadSplit');
var pdfFrame      = document.getElementById('pdfFrame');
var changeBtn     = document.getElementById('changeBtn');
var uploadForm    = document.getElementById('uploadForm');
var blobURL       = null;
var droppedFile   = null;  // fallback if DataTransfer assignment fails

function showPDF(file) {
  if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
    alert('Por favor selecciona un archivo PDF.');
    return;
  }
  if (blobURL) { URL.revokeObjectURL(blobURL); }
  blobURL = URL.createObjectURL(file);
  pdfFrame.src = blobURL + '#pagemode=none&navpanes=0&toolbar=1';
  document.getElementById('fileName').textContent = file.name;
  droppedFile = null;
  // Attempt DataTransfer to make the file available in realFileInput
  try {
    var dt2 = new DataTransfer();
    dt2.items.add(file);
    realFileInput.files = dt2.files;
    // Verify it worked
    if (!realFileInput.files || !realFileInput.files.length) {
      droppedFile = file;
    }
  } catch(e) {
    droppedFile = file; // DataTransfer not supported — will use fetch fallback
  }
  dropWrapper.style.display = 'none';
  uploadSplit.classList.add('active');
}

// File selected via native dialog (overlay click)
fileInput.addEventListener('change', function(e) {
  var f = e.target.files && e.target.files[0];
  if (f) {
    // Copy to realFileInput
    try {
      var dt3 = new DataTransfer();
      dt3.items.add(f);
      realFileInput.files = dt3.files;
    } catch(_) { droppedFile = f; }
    showPDF(f);
  }
});

// Drag events on the drop zone
dropZone.addEventListener('dragenter', function(e) {
  e.preventDefault(); e.stopPropagation();
  dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragover', function(e) {
  e.preventDefault(); e.stopPropagation();
  dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', function(e) {
  e.stopPropagation();
  if (!dropZone.contains(e.relatedTarget)) {
    dropZone.classList.remove('dragover');
  }
});
dropZone.addEventListener('drop', function(e) {
  e.preventDefault();
  e.stopPropagation();
  dropZone.classList.remove('dragover');
  var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) showPDF(f);
});

// Prevent browser from opening files dropped anywhere else on the page
document.addEventListener('dragover', function(e) { e.preventDefault(); });
document.addEventListener('drop',     function(e) { e.preventDefault(); });

// Change file button
changeBtn.addEventListener('click', function() {
  uploadSplit.classList.remove('active');
  dropWrapper.style.display = '';
  if (blobURL) { URL.revokeObjectURL(blobURL); blobURL = null; }
  pdfFrame.src = '';
  fileInput.value = '';
  realFileInput.value = '';
  droppedFile = null;
  document.getElementById('order_no').value = '';
  document.getElementById('idValue').value = '';
  clearOrderErr();
});

/* ══════════════════════════════════════════════
   FORM VALIDATION + SUBMIT
══════════════════════════════════════════════ */
var orderInput = document.getElementById('order_no');
var orderErr   = document.getElementById('orderErr');

function clearOrderErr() {
  orderInput.classList.remove('err');
  orderErr.classList.remove('show');
}

function validateOrder(v) { return /^[0-9]{6}$/.test(v.trim()); }

orderInput.addEventListener('input', function() {
  var v = orderInput.value;
  if (v.length > 0 && !validateOrder(v)) {
    orderInput.classList.add('err'); orderErr.classList.add('show');
  } else { clearOrderErr(); }
});

uploadForm.addEventListener('submit', function(e) {
  if (!validateOrder(orderInput.value)) {
    e.preventDefault();
    orderInput.classList.add('err'); orderErr.classList.add('show'); orderInput.focus();
    return;
  }
  // If DataTransfer failed, use fetch with the stored droppedFile
  if (droppedFile && (!realFileInput.files || !realFileInput.files.length)) {
    e.preventDefault();
    var fd = new FormData(uploadForm);
    fd.set('pdf_file', droppedFile, droppedFile.name);
    fetch('/upload', { method: 'POST', body: fd })
      .then(function(r) { window.location.href = r.url || '/'; })
      .catch(function(err) { alert('Upload failed: ' + err.message); });
    return;
  }
  if (!realFileInput.files || !realFileInput.files.length) {
    e.preventDefault(); alert('Por favor selecciona un archivo PDF primero.');
  }
});

/* ══════════════════════════════════════════════
   CONFIRM DELETE (language-aware)
══════════════════════════════════════════════ */
function confirmDel(orderNo) {
  return confirm(fmt(T[lang].del_confirm, orderNo));
}

/* ══════════════════════════════════════════════
   REFRESH COUNTDOWN
══════════════════════════════════════════════ */
var lastManual = {{ last_manual_refresh|default(0) }};

function fmtTime(s) {
  return new Date(s * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function tick() {
  var el = document.getElementById('refreshMeta');
  if (!el) return;
  var now = Math.floor(Date.now() / 1000);
  var rem = lastManual ? Math.max(0, 300 - (now - lastManual)) : 0;
  var t = T[lang];
  if (!lastManual) {
    el.textContent = t.refresh_ready;
  } else if (rem > 0) {
    var m = Math.floor(rem/60), s = rem % 60;
    el.textContent = fmt(t.refresh_last, fmtTime(lastManual), m + ':' + String(s).padStart(2,'0'));
  } else {
    el.textContent = fmt(t.refresh_ready2, fmtTime(lastManual));
  }
}
tick();
setInterval(tick, 1000);

/* ══════════════════════════════════════════════
   SEARCH + FILTER + SORT + PAGINATE
══════════════════════════════════════════════ */
var tbody       = document.getElementById('tbody');
var allRows     = Array.from(document.querySelectorAll('tr.row'));
var tableFooter = document.getElementById('tableFooter');

var PAGE_SIZE     = 10;
var activeSort    = 'PRIORITY';
var query         = '';
var activeFilters = new Set();
var currentPage   = 1;
var currentList   = [];

var epoch    = function(iso) { var t = new Date(iso).getTime(); return isNaN(t) ? 0 : Math.floor(t/1000); };
var evEpoch  = function(r) { return epoch(r.dataset.event || ''); };
var addEpoch = function(r) { return epoch(r.dataset.added || ''); };
var isPend   = function(r) { var s = r.dataset.status||''; return !s||s==='PENDING'||s==='UNKNOWN'||s==='NOT_PRESENTED'; };
var isStar   = function(r) { return r.dataset.star === '1'; };

function apply() {
  var q = query.trim().toLowerCase();
  var list = allRows.filter(function(r) {
    if (q) {
      var hay = (r.dataset.order||'') + ' ' + (r.dataset.trailer||'') + ' ' + (r.dataset.notes||'');
      if (hay.toLowerCase().indexOf(q) === -1) return false;
    }
    if (activeFilters.size > 0 && !activeFilters.has(r.dataset.grp)) return false;
    return true;
  });

  list.sort(function(a, b) {
    switch (activeSort) {
      case 'PRIORITY': {
        var s = isStar(b) - isStar(a); if (s) return s;
        var p = isPend(a) - isPend(b); if (p) return p;
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
  var total      = list.length;
  var totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = 1;
  var start    = (currentPage - 1) * PAGE_SIZE;
  var end      = Math.min(start + PAGE_SIZE, total);
  var pageRows = list.slice(start, end);

  var t = T[lang];
  var info = document.getElementById('showingInfo');
  if (info) info.textContent = total === 0 ? t.no_found : fmt(t.showing, start+1, end, total);

  if (tableFooter) tableFooter.style.display = total > PAGE_SIZE ? '' : 'none';
  var pi = document.getElementById('pageInfo');
  if (pi) pi.textContent = fmt(t.page_of, currentPage, totalPages);
  var prev = document.getElementById('prevBtn');
  var next = document.getElementById('nextBtn');
  if (prev) prev.disabled = currentPage <= 1;
  if (next) next.disabled = currentPage >= totalPages;

  tbody.innerHTML = '';
  if (pageRows.length === 0 && allRows.length > 0) {
    var noMatch = document.createElement('tr');
    noMatch.innerHTML = '<td colspan="6"><div class="empty"><div class="empty-sub" style="padding:28px 0">' + t.no_match + '</div></div></td>';
    tbody.appendChild(noMatch);
  } else {
    pageRows.forEach(function(r) { tbody.appendChild(r); });
  }
}

document.getElementById('sort').addEventListener('change', function(e){ activeSort = e.target.value; currentPage = 1; apply(); });
document.getElementById('q').addEventListener('input',    function(e){ query = e.target.value; currentPage = 1; apply(); });
document.getElementById('prevBtn').addEventListener('click', function(){ currentPage--; apply(); });
document.getElementById('nextBtn').addEventListener('click', function(){ currentPage++; apply(); });

document.querySelectorAll('.filter-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    var f = btn.dataset.f;
    if (f === 'all') {
      activeFilters.clear();
      document.querySelectorAll('.filter-btn').forEach(function(b) { b.classList.remove('on'); });
      btn.classList.add('on');
    } else {
      document.querySelector('.filter-all').classList.remove('on');
      if (activeFilters.has(f)) { activeFilters.delete(f); btn.classList.remove('on'); }
      else                      { activeFilters.add(f);    btn.classList.add('on'); }
      if (activeFilters.size === 0) document.querySelector('.filter-all').classList.add('on');
    }
    currentPage = 1; apply();
  });
});

/* ══════════════════════════════════════════════
   EXPORT CSV
══════════════════════════════════════════════ */
document.getElementById('exportBtn').addEventListener('click', function() {
  var t = T[lang];
  var headers = [t.col_order, t.col_trailer, 'Status Code', t.col_status+' Detail', 'Date Added', t.col_notes];
  var csvRows = [headers];
  currentList.forEach(function(r) {
    csvRows.push([
      r.dataset.order   || '',
      r.dataset.trailer || '',
      r.dataset.status  || '',
      r.dataset.label   || '',
      r.dataset.added   || '',
      r.dataset.notes   || '',
    ]);
  });
  var csv  = csvRows.map(function(row){ return row.map(function(v){ return '"' + String(v).replace(/"/g,'""') + '"'; }).join(','); }).join('\n');
  var blob = new Blob([csv], {type:'text/csv'});
  var url  = URL.createObjectURL(blob);
  var a    = document.createElement('a');
  a.href = url; a.download = 'doda-tracker-' + new Date().toISOString().slice(0,10) + '.csv';
  a.click(); URL.revokeObjectURL(url);
});

/* ══════════════════════════════════════════════
   NOTES INLINE EDITING (event delegation)
══════════════════════════════════════════════ */
function openNote(row) {
  row.querySelector('.notes-view').style.display = 'none';
  var wrap = row.querySelector('.notes-edit-wrap');
  wrap.style.display = 'flex';
  var inp = wrap.querySelector('.notes-input');
  inp.value = row.querySelector('.notes-text').textContent;
  inp.focus(); inp.select();
}

function closeNote(row) {
  row.querySelector('.notes-edit-wrap').style.display = 'none';
  row.querySelector('.notes-view').style.display = 'flex';
}

function saveNote(row, orderNo) {
  var inp   = row.querySelector('.notes-input');
  var notes = inp.value;
  fetch('/notes/' + encodeURIComponent(orderNo), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({notes: notes}),
  }).then(function(res) {
    if (res.ok) {
      row.querySelector('.notes-text').textContent = notes;
      row.dataset.notes = notes;
    }
  }).catch(function(){}).finally(function(){ closeNote(row); });
}

document.addEventListener('click', function(e) {
  var pencil = e.target.closest('.note-pencil');
  if (pencil) { openNote(pencil.closest('tr')); return; }
  var saveBtn = e.target.closest('.note-save');
  if (saveBtn) { saveNote(saveBtn.closest('tr'), saveBtn.dataset.order); return; }
  var cancelBtn = e.target.closest('.note-cancel');
  if (cancelBtn) { closeNote(cancelBtn.closest('tr')); return; }
});

document.addEventListener('keydown', function(e) {
  var inp = e.target.closest && e.target.closest('.notes-input');
  if (!inp) return;
  var row = inp.closest('tr');
  var saveBtn = row.querySelector('.note-save');
  if (e.key === 'Enter')  { e.preventDefault(); saveNote(row, saveBtn.dataset.order); }
  if (e.key === 'Escape') { closeNote(row); }
});

/* ══════════════════════════════════════════════
   INIT
══════════════════════════════════════════════ */
applyLang(lang);   // Apply saved/default language
apply();           // Initial table render
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
            flash("Número de orden requerido.", "error")
            return redirect(url_for("index"))
        if not order_no.isdigit() or len(order_no) != 6:
            flash("El número de orden debe ser exactamente 6 dígitos.", "error")
            return redirect(url_for("index"))

        uploaded_file = request.files.get("pdf_file")
        if not uploaded_file or uploaded_file.filename == "":
            flash("Por favor selecciona un archivo PDF.", "error")
            return redirect(url_for("index"))
        filename = uploaded_file.filename
        if not filename.lower().endswith(".pdf"):
            flash("Solo se aceptan archivos PDF.", "error")
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
                tmp_path.replace(no_qr_dir / filename)
                flash(f"No se encontró código QR en '{filename}'. Archivo movido a _NO_QR.", "error")
                return redirect(url_for("index"))

            trailer = identifier_value if identifier_value else extract_trailer_or_plate_from_pdf(tmp_path)

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
            flash(f"Orden {order_no} agregada con {len(links)} enlace(s) QR{id_msg}.", "success")

        except Exception as e:
            logger.exception("Upload error for order %s: %s", order_no, e)
            flash(f"Error al subir: {e}", "error")
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
