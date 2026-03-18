# DODA Tracker — Local install per teammate (Windows)

## What each teammate gets
A zip file containing a portable folder with the app:
- `DODA-Tracker\\DODA-Tracker.exe`
- `DODA-Tracker\\config.json`
- `DODA-Tracker\\status_map.json`

Runtime-created folders (created automatically on first run):
- `DODA-Tracker\\data` (SQLite DB)
- `DODA-Tracker\\storage` (PDF storage + quarantine + trash)

## Install (teammate)
1) Unzip `DODA-Tracker-win.zip`
2) Put the extracted **DODA-Tracker** folder somewhere like:
   - `C:\\Users\\<name>\\Documents\\DODA-Tracker`
3) Double-click `DODA-Tracker.exe`
4) Open dashboard:
   - http://127.0.0.1:8787

## Configure inbox folder
By default, the app watches:
- `C:\\Users\\jordi\\.openclaw\\workspace\\doda_inbox`

For coworkers, edit `config.json` and set `inboxDir` to something on THEIR laptop, e.g.:
- `C:/Users/<name>/Documents/DODA-Inbox`

Then create that folder and drop PDFs there.

## Updating the app later (keep their data)
When you ship an update zip:
- Tell teammates to **replace only**:
  - `DODA-Tracker.exe`
  - `_internal/`
  - `config.json` (only if you want to push new defaults)
  - `status_map.json`
- Tell them **DO NOT delete**:
  - `data/`
  - `storage/`

## Notes
- This runs locally. No IT/network changes.
- If Windows SmartScreen warns, they may need to click “More info” → “Run anyway”.
