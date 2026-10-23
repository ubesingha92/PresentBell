# PresentBell

Stdlib-only presentation timer for a Windows presentation PC: a small
ASBIRES-styled countdown window plus a phone-friendly web remote on the venue LAN.

## Run

```powershell
python presentbell.py
```

- Console prints `http://localhost:8765`, LAN URLs, the configured password
  (default `asdf1234`, editable as `password` in `presentbell_config.json`), and where settings live.
- Open the URL on the presentation PC or venue LAN, enter the password.
- Timer window appears top-right on the configured display(s):
  borderless, always-on-top, white on navy with an orange accent.

Options: `python presentbell.py --port 8765` (default 8765).

## Build or rebuild the Windows app

1. Stop PresentBell using **Quit** in the web remote or **Ctrl+C** in its
   console. The executable must be closed before rebuilding.
2. Open PowerShell in the project folder:

   ```powershell
   Set-Location -LiteralPath 'C:\Users\ubesi\OneDrive\Desktop\asbires 2026\PresentBell'
   ```

3. Install PyInstaller once using the same Python used for the build:

   ```powershell
   python -m pip install pyinstaller
   ```

4. Build or rebuild using the included specification file. It bundles the bell:

   ```powershell
   python -m PyInstaller --noconfirm PresentBell.spec
   ```

   The finished app is `dist\PresentBell.exe`. Repeat this step after changing
   `presentbell.py`.

5. To apply the project's JSON settings to the packaged app, copy the file:

   ```powershell
   Copy-Item -LiteralPath '.\presentbell_config.json' -Destination '.\dist\presentbell_config.json' -Force
   ```

   This replaces the packaged app's existing settings with the project settings.
   To keep separate settings for the executable, edit
   `dist\presentbell_config.json` directly instead.

6. Start the rebuilt app:

   ```powershell
   & '.\dist\PresentBell.exe'
   ```

The current defaults are a **130 x 40 px** timer on a 1280 x 720 reference
slide, with **20 px** timer text, **8 px** phase text, and password **`asdf1234`**.
The console prints the URLs and configured password.

JSON-only changes need a restart; no rebuild is required. The script reads
`presentbell_config.json` in the project folder, while the executable reads
`dist\presentbell_config.json` beside itself. Existing JSON settings override
code defaults, so rebuilding alone does not apply changed defaults to an existing
configuration. If the JSON file is absent, the app creates it with defaults.

When moving the app to another PC, copy `dist\PresentBell.exe` and its
`presentbell_config.json` together into the same folder. Python is not required
on that PC.

## Controls (web UI)

The page shows the live phase plus remaining time, and these buttons:

- Presentation Start (restarts), Presentation End (Q&A Start, restarts Q&A),
  Q&A End, Reset
- Show / Hide (visibility only; timer keeps running)
- Quit (exits the app; Esc does nothing, Ctrl+C also works)

## Settings (`presentbell_config.json`)

Durations, remaining-time marks, bell toggles, displays, appearance, and the login password live in
`presentbell_config.json` next to the app (auto-created with defaults on
first run; edit while the app is stopped, or delete it to restore defaults).
The file also carries a `_comments` block explaining each field:

```json
{
  "password": "asdf1234",
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

## ASBIRES PowerPoint master

Open `output/ASBIRES 2026 - Paper Title Template.potx` to create a presentation for your talk.
The eight example slides use eight native layouts: cover, section divider,
title/content, two-column comparison, image/caption, chart/table, conclusion,
and Q&A. Use **Home > New Slide / Layout** to reuse them. Replace the example
text. Use the picture/content placeholder insertion buttons for images, charts,
and tables. Slide numbers update in PowerPoint.

The 16:9 design adapts the navy, orange and icy-blue palette of
`ASBIRES-2026-Banner.jpeg`. The cover contains the event and university logos;
content slides use restrained ASBIRES branding. The banner itself is not a
slide background. All decorative shapes and text are editable.

Use **Design > Variants > Colors / Fonts** to customize the theme, and
**View > Slide Master** to adjust shared layout elements. Accent 1 is navy
(`#0D354D`), Accent 2 is orange (`#F26522`), and Accent 3 is icy blue (`#DCEAF2`).
The default heading/body font is Arial. Logos retain their original colors.
Changes in PowerPoint do not automatically synchronize with PresentBell.

### Matching timer size and style

Edit the `style` object in `presentbell_config.json` while PresentBell is stopped:

```json
"style": {
  "background": "#0D3549",
  "foreground": "#FFFFFF",
  "accent": "#F66A17",
  "font_family": "Arial",
  "time_font_size": 20,
  "phase_font_size": 8,
  "width": 130,
  "height": 40,
  "margin_right": 32,
  "margin_top": 6
}
```

Dimensions, margins, and font sizes are pixels on a 1280 x 720 reference slide,
not fixed screen pixels. PresentBell scales each mirrored timer independently
to the monitor's centered 16:9 slide area, accounting for letterboxing. At
1920 x 1080, the default timer is 195 x 60 pixels with 48px right and 9px top
margins. Text automatically shrinks if needed to fit the chosen dimensions,
including hour-long countdowns. Choose an installed font; Tk falls back if
it is unavailable. Colors must be six-digit `#RRGGBB` values.

The compact timer occupies x=1118-1248, y=6-46 on the reference slide,
above the revised cover's conference heading. Its teal (`#0D3549`), orange
(`#F66A17`) and Arial text match the cover. Keep that strip clear when editing
layouts. Increasing timer size or margins may require moving content in Slide
Master. Supported ranges: width 120-400, height 40-180, margins 0-200,
time font 12-80, phase font 8-30. Invalid values use defaults.
Existing configuration files without `style` also use the ASBIRES defaults.

Alignment assumes a full-screen, centered 16:9 PowerPoint slideshow. A windowed
slideshow or a projector that stretches/crops slides will need manual adjustment.
The web remote and timing/bell behavior are unchanged. Run `python presentbell.py`
for the updated app; an existing executable must be rebuilt using the command above.

## Checks

Run `python -m unittest discover -s tests` for configuration, display scaling,
and timer/bell regression checks.

## License

This project is licensed under the [MIT License](LICENSE).
