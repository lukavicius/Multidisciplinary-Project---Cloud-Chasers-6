# CloudChasers logger dashboard

Reads the Mayfly, HOBO and Tempest logger files straight from the team's Google Drive
folder and opens an interactive dashboard in your browser. Works on Windows and Mac.

You run the launcher `analysis_tool.py`. It fetches the latest dashboard code
(`readplot.py`) and its `requirements.txt` from the `analysis_tool_code` folder on the
team Drive and runs it, so you always get the newest version. The logger data stay on
Drive; only the code is fetched, and packages are installed when that requirements
file changes.

## Before you start

You need two things from Tadas:

1. **Send him the Google account email you use for Drive.** He has to add you as a
   tester of the app, or Google will block your login.
2. **Get the file `credentials.json` from him.** It is not in this repository on purpose.
   Don't share it outside the team.

You also need access to the team's Drive data folder, which you should already have.

## Setup (one time)

### 1. Install Python 3.10 or newer

Download it from https://www.python.org/downloads/

- **Windows:** on the first screen of the installer, tick **"Add python.exe to PATH"**.
- **Mac:** run the installer. When it finishes, a Finder window opens. Double-click
  **Install Certificates.command** in it (this prevents SSL errors when connecting to Google).
  If you missed it, it's in Applications → Python 3.x.

### 2. Get the code

Either `git clone <repo-url>`, or download the ZIP and unzip it.

### 3. Open a terminal in the project folder

- **Windows:** open the folder in File Explorer, click the address bar, type `cmd`, press Enter.
- **Mac:** open the **Terminal** app, type `cd ` (with a space after it), drag the project
  folder from Finder into the Terminal window, and press Enter.

### 4. Create a virtual environment and install the packages

**Windows:**
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Mac:**
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

After activating, your terminal line starts with `(.venv)`.

### 5. Add the credentials

Put `credentials.json` in the project folder, next to `analysis_tool.py`.

## Running it

Every time:

1. Open a terminal in the project folder (step 3 above) and activate the environment:
   - **Windows:** `.venv\Scripts\activate`
   - **Mac:** `source .venv/bin/activate`
2. Run:
   - **Windows:** `python analysis_tool.py`
   - **Mac:** `python3 analysis_tool.py`
3. **First run only:** a browser window opens asking you to log in to Google.
   - Pick the account you gave Tadas.
   - Google will say it **hasn't verified this app**. That's expected for an internal
     tool: click **Advanced → Go to cloud chasers (unsafe)**.
   - Allow read-only access to Drive.

   A `token.json` file appears in the folder. That's your personal login; don't share it.
4. The script loads the data (takes a minute) and the dashboard opens at
   http://127.0.0.1:8050. To stop it, click in the terminal and press **Ctrl+C**
   (on Mac too: Control, not Command).

## Troubleshooting

| What you see | What to do |
|---|---|
| `Error 403: access_denied` / "has not completed the Google verification process" | You haven't been added as a tester yet. Ask Tadas, wait a few minutes, try again. |
| `invalid_grant` or `Token has been expired or revoked` | Delete `token.json` and run again to log back in. This happens about once a week. |
| `HttpError 404 ... File not found` | Your Google account doesn't have access to the Drive folder. Ask for it to be shared with you. |
| `FileNotFoundError: credentials.json` | `credentials.json` isn't in the project folder, or is named differently (e.g. `credentials (1).json`). On Mac, check Finder didn't save it as `credentials.json.txt`. |
| `CERTIFICATE_VERIFY_FAILED` (Mac) | Run **Install Certificates.command** from Applications → Python 3.x, then try again. |
| `'python' is not recognized` (Windows) | Python isn't on PATH. Reinstall it with the "Add to PATH" box ticked, then open a new terminal. |
| `command not found: python` (Mac) | Use `python3` instead of `python`. |
| `No module named ...` | The environment isn't active (no `(.venv)` at the start of the line). Activate it and run again. |
| `Address already in use` / port 8050 | The dashboard is already running in another terminal. Close that one first. |
