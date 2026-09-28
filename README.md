# PresentBell

Stdlib-only presentation timer for a Windows presentation PC: a small
white countdown window plus a phone-friendly web remote on the venue LAN.

## Run

```powershell
python presentbell.py
```

- Console prints `http://localhost:8765`, LAN URLs, a 6-digit password
  (console only, per run), and where settings live.
- Open the URL on the presentation PC or venue LAN, enter the password.
- Timer window appears top-center on the configured display(s):
  borderless, always-on-top, black on white.

Options: `python presentbell.py --port 8765` (default 8765).

## Build exe (Windows)

```powershell
pip install pyinstaller
pyinstaller --onefile --name PresentBell --add-data 'bell.mp3;.' presentbell.py
```

Run `dist\PresentBell.exe` — the console shows the URLs and password, and
`presentbell_config.json` is created next to the exe on first run.

## Controls (web UI)

The page shows the live phase plus remaining time, and these buttons:

- Presentation Start (restarts), Presentation End (Q&A Start, restarts Q&A),
  Q&A End, Reset
- Show / Hide (visibility only; timer keeps running)
- Quit (exits the app; Esc does nothing, Ctrl+C also works)

## Settings (`presentbell_config.json`)

Durations, remaining-time marks, bell toggles, and displays live only in
`presentbell_config.json` next to the app (auto-created with defaults on
first run; edit while the app is stopped, or delete it to restore defaults).
The file also carries a `_comments` block explaining each field:

```json
{
  "presentation_duration": 600,
  "qa_duration": 300,
  "warning_seconds": 120,
  "qa_warning_seconds": 120,
  "bell_pres_end": true,
  "bell_qa_end": true,
  "bell_pres_warning": true,
  "bell_qa_warning": true,
  "display_index": 0
}
```

Durations are seconds (`600` = 10:00, range 10–10800).
`display_index` can be a list, e.g. `[0, 1]`, to mirror the timer on both
displays (0 = first display).

## Bells

Bundled `bell.mp3` plays offline: single bell at each remaining-time mark,
double bell at presentation timeout and Q&A timeout. Q&A never auto-starts;
button clicks never ring. If the file is missing, a system beep is used.

## Notes

- Python 3, no installs for the script. If venue firewall blocks LAN, use a
  same-PC `localhost` browser.
- Password never appears on the presentation display.
