# DODA Tracker (PDF → QR link → status dashboard)

MVP goals:
- Drop a PDF into an inbox folder
- Popup prompts for **Order Number** (identifier)
- Extract QR code link(s) from the PDF
- Re-check each link on a schedule (default: every 10 minutes)
- Show everything in a local **dashboard** (browser)

## Folders
- Inbox (drop PDFs): `C:\Users\jordi\.openclaw\workspace\doda_inbox`
- Storage (organized PDFs): `C:\Users\jordi\.openclaw\workspace\doda_tracker\storage`
- Database: `C:\Users\jordi\.openclaw\workspace\doda_tracker\data\doda.db`

## Setup

### Python version note (important)
This project uses `opencv-python`, which depends on `numpy` wheels. Your machine currently has **Python 3.14**, and many packages (especially numpy/opencv) may not have wheels for it yet, which can trigger slow/failed source builds.

**Recommendation:** install **Python 3.12.x** and use that for this project.

### Install
```powershell
cd C:\Users\jordi\.openclaw\workspace\doda_tracker
py -3.12 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Run
```powershell
python app.py
```

Then open the dashboard:
- http://127.0.0.1:8787

## How it works
1) Drop a PDF into the inbox folder
2) You’ll get a popup to enter an Order Number
3) The app moves/renames the PDF into storage and extracts QR links
4) The checker visits each link on a schedule and records whether it contains the target status phrase:
   - `Desaduanamento Libre`

## Notes
- Dashboard only by default.
- Email notifications can be added later.
