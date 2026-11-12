"""
Launcher for the CloudChasers logger dashboard.

Downloads the latest analysis code from the team Drive folder
analysis_tool_code (readplot.py) and runs it, so you always
get the newest version without anyone sending you files.

If requirements.txt in that Drive folder changes, the needed packages are
installed automatically.

Run:  python analysis_tool.py      (Mac: python3 analysis_tool.py)
"""
import hashlib
import io
import subprocess
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ID of the analysis_tool_code folder itself (from its address in Drive:
# drive.google.com/drive/folders/<ID>). The ID of a folder that contains it also works.
FOLDER_ID = "1MQBSL-8QmLWaVhFp15757nuAuu7JCY0A"
CODE_FOLDER = "analysis_tool_code"
CODE_FILE = "readplot.py"
REQUIREMENTS = "requirements.txt"

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
TOKEN = Path("token.json")
CREDS = Path("credentials.json")
INSTALLED_MARKER = Path(".requirements_installed")  # remembers which requirements were installed
FOLDER_MIME = "application/vnd.google-apps.folder"


def get_service():
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds)


def children(service, folder_id, extra=""):
    q = f"'{folder_id}' in parents and trashed = false{extra}"
    items, token = [], None
    while True:
        resp = service.files().list(
            q=q, fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
            pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        items += resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            return items


def find_code_folder(service):
    """FOLDER_ID itself if it is the code folder (or holds readplot.py); otherwise a breadth-first
    search for the code folder inside it (folders only, so it's quick)."""
    try:
        top = service.files().get(fileId=FOLDER_ID, fields="id, name",
                                  supportsAllDrives=True).execute()
    except Exception as e:
        raise SystemExit(f"Can't open the Drive folder {FOLDER_ID}: {e}\n"
                         "Check the ID in analysis_tool.py and that you have access to the folder.")
    if top["name"] == CODE_FOLDER or children(service, FOLDER_ID, f" and name = '{CODE_FILE}'"):
        return FOLDER_ID
    queue = [FOLDER_ID]
    while queue:
        folder = queue.pop(0)
        for sub in children(service, folder, f" and mimeType = '{FOLDER_MIME}'"):
            if sub["name"] == CODE_FOLDER:
                return sub["id"]
            queue.append(sub["id"])
    raise SystemExit(f"Couldn't find '{CODE_FILE}' or a '{CODE_FOLDER}' folder in the Drive folder "
                     f"'{top['name']}'. Check FOLDER_ID in analysis_tool.py and that you have access.")


def download_text(service, file_id):
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, service.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8-sig")


def ensure_requirements(text):
    digest = hashlib.sha256(text.encode()).hexdigest()
    if INSTALLED_MARKER.exists() and INSTALLED_MARKER.read_text().strip() == digest:
        return
    print("Package list changed: installing/updating packages (one time)...")
    req = Path(".requirements_from_drive.txt")
    req.write_text(text)
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)])
    finally:
        req.unlink(missing_ok=True)
    INSTALLED_MARKER.write_text(digest)


def main():
    service = get_service()
    files = {f["name"]: f for f in children(service, find_code_folder(service))}

    if CODE_FILE not in files:
        raise SystemExit(f"'{CODE_FILE}' is missing from the '{CODE_FOLDER}' folder on Drive.")
    if REQUIREMENTS in files:
        ensure_requirements(download_text(service, files[REQUIREMENTS]["id"]))

    code = files[CODE_FILE]
    print(f"Running {CODE_FILE} from Drive (last updated {code['modifiedTime'][:16].replace('T', ' ')} UTC)\n")
    source = download_text(service, code["id"])
    exec(compile(source, f"{CODE_FOLDER}/{CODE_FILE} (Google Drive)", "exec"),
         {"__name__": "__main__", "__file__": str(Path(CODE_FILE).resolve())})


if __name__ == "__main__":
    main()