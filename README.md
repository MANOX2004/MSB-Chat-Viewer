# MSB Chat Viewer

A read-only desktop viewer for WhatsApp `.txt` and `.zip` chat exports. It
supports multiline messages, participant and date filters, and image attachments
stored in ZIP exports.

## Run

Create and activate a virtual environment, then install the project
dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the application from this folder:

```powershell
python main.py
```

Open a WhatsApp chat export with **Open Chat (.zip / .txt)**. ZIP contents are
read in memory and are not extracted to disk. Select your exported identity to
show its messages on the right, and use the date dropdown to filter the chat.