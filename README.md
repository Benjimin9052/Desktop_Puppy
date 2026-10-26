# Desktop Puppy

A golden retriever puppy that lives on your desktop. It trots after your cursor, plays with a ball, chews a bone, barks when you click, and goes to sleep in its own kennel when you leave it alone.

## Behaviour

| What you do | What the puppy does |
|---|---|
| Move the cursor normally | Trots after it (works on any connected monitor) |
| Move the cursor fast | Plays with a ball or chews a bone |
| Slow down or stop the cursor | Runs to the cursor, sits and lifts a paw ("come on, move!") for 5 seconds |
| Leave the cursor still after that | Roams the desktop, playing with the ball for 15 s and chewing its bone for 5 s, and repeats |
| Leave the cursor still for 60 s | Walks to its kennel and goes to sleep (Zzz) |
| Move the cursor again | Wakes up and runs to you |
| Click anywhere | WOOF! (bark sound and animation) |
| Drag the kennel | Moves it anywhere, even to another monitor. The position is remembered |
| Click the kennel | Opens a list of your open apps beside the kennel, each with a Close button. Hover a name for details |
| Right-click the kennel | Quits the puppy |

The Close button asks the app to quit, as if you clicked its X, so it may still ask you to save your work.

## Running it

Requires Python 3 with tkinter. The puppy itself uses only the standard library.

```
python desktop_puppy.py
```

Keep `puppy_sprites.py` in the same folder. Quit by right-clicking the kennel, or press Ctrl+C in the terminal.

Windows gives the full experience: transparent, click-through puppy, global click detection, sound and the open-apps list. On macOS and Linux it runs with reduced features. Global clicks need `pynput`, and the app list needs `wmctrl` on Linux.

Only one puppy runs at a time. Starting a second copy on Windows does nothing.

## Install as a Windows app

```
python install_app.py              # build DesktopPuppy.exe, install it, add Start Menu and Desktop shortcuts, start at sign-in
python install_app.py --no-startup # same, but don't start at sign-in
python install_app.py --uninstall  # close it and remove the app, shortcuts and auto-start
```

The app installs to `%LOCALAPPDATA%\Programs\DesktopPuppy`.

## Customising

- **Settings:** edit the constants at the top of `desktop_puppy.py`: `WAIT_SECONDS`, `BALL_SECONDS`, `BONE_SECONDS`, `SLEEP_AFTER`, `FOLLOW_RADIUS`, `FAST_SPEED`, `CALM_SPEED` and others.
- **Bark sound:** put your own `bark.wav` next to the program to replace the built-in synthesised bark.
- **Kennel position:** saved in `~/.desktop_puppy.json`.

## Project files

| File | Purpose |
|---|---|
| `desktop_puppy.py` | The app: behaviour, kennel, ball, bark sound and open-apps panel |
| `puppy_sprites.py` | Generated sprite frames for the puppy and ball |
| `make_puppy_sprites.py` | Regenerates `puppy_sprites.py`. Needs Pillow and numpy. Add `--sheet` for a preview image |
| `install_app.py` | Builds and installs the Windows app |
| `build_app/` | Build output and the icon from the installer |
