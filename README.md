# 🔎 Campus Lost & Found

One place for students to post lost or found items with photos. AI matches lost and found reports by description, photo and location.

## Features
- **Post lost or found items** with a photo, category, color, campus location and date. This works on a phone.
- **AI photo tagging (Claude):** upload a photo and the AI fills in the title, category, color, brand and identifying details. You don't need to type anything.
- **AI matching (Claude):** each new report is compared with all open reports of the opposite type. Each match gets a **% score and a plain-English reason**. The AI understands messy text like "specs", "airdopes" and "calc", and it checks that a found date isn't before the lost date.
- **Location-aware:** campus places are grouped into zones, so Library and Computer Lab count as nearby.
- **Works without internet or an API key:** a local matcher uses synonyms, colors, location zones and dates, so the demo always works.
- **Trust:** each post gets a private item code. Only the poster or security staff can mark an item as returned.
- **Security desk dashboard** (`/desk`, PIN `1234`): see items held at the desk and strong matches to act on, with the owner's contact details.
- Search and filter by type, category and keyword. The board shows counts of lost, found and returned items.

## Run it
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # optional: enables Claude AI
python seed.py                        # optional: demo data
python app.py                         # open http://localhost:5000
```

### Windows (PowerShell)
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY="sk-ant-..."   # optional: enables Claude AI
python seed.py                        # optional: demo data
python app.py                         # open http://localhost:5000
```
In Command Prompt (cmd), activate with `.venv\Scripts\activate.bat` and set the key with `set ANTHROPIC_API_KEY=sk-ant-...`.

Don't copy the `.venv` folder from Linux or Mac to Windows. Delete it and create a new one with the commands above.

## Demo script (2 min)
1. Open the board. It already has 10 messy, realistic reports with match badges.
2. Open **"boAt airdopes"** (lost). It shows a 75%+ match with "Wireless earbuds in case" at the library, with the reason.
3. Click **I found something**, upload a photo of any bottle, earphones or ID card, and leave the text empty. The AI fills in the details and finds the matching lost report right away.
4. Open **Security desk** (PIN 1234) to see the strong matches staff should act on.
5. Mark an item as **returned** with its item code. The returned counter goes up.

## Stack
Flask + SQLite + Pillow, with Claude (`claude-opus-5-5`) using vision and structured JSON output. Files: `app.py` (routes and database), `ai.py` (Claude and fallback matcher), `templates/`, `static/style.css`.
