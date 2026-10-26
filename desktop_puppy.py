#!/usr/bin/env python3
"""
Desktop Puppy  -  a golden retriever pup that lives on your screen
=================================================================
  * Move the cursor normally ........ puppy trots after it (on ANY connected monitor)
  * Move the cursor FAST ............ puppy plays with a ball OR chews a bone
  * Slow down / stop the cursor ..... puppy runs to the cursor, SITS and lifts a paw
                                      as if saying "come on, move!"  (5 seconds)
  * Cursor still after that ......... puppy roams the desktop (all monitors) playing with
                                      the ball for 15 s, chews its bone for 5 s, and repeats
  * Cursor still for 60 s ........... puppy walks to its kennel and goes to sleep (Zzz)
  * Move the cursor again ........... puppy wakes up / stops playing and runs to you
  * Click anywhere .................. WOOF! (bark sound + bark animation)
  * Drag the kennel ................. put it anywhere (even on another monitor) - the puppy
                                      always goes home to its new spot (position is remembered)
  * Click the kennel ................ opens a list of your open apps, right next to the
                                      kennel, each with a Close button

Run:   python desktop_puppy.py          (keep puppy_sprites.py in the same folder)
Quit:  right-click the kennel (or Ctrl+C in the terminal)

Optional: put your own "bark.wav" next to this file to replace the built-in bark.
Standard library only (tkinter). Windows gives the full experience (transparent,
click-through puppy, global click detection, sound, app list).
"""

import io
import json
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import wave

import puppy_sprites as spr

# --------------------------------------------------------------------------
# Settings you can tweak
# --------------------------------------------------------------------------
WAIT_SECONDS = 5.0     # how long the puppy sits & lifts its paw before it goes off to play
BALL_SECONDS = 15.0    # roaming with the ball for this long ...
BONE_SECONDS = 5.0     # ... then chewing the bone for this long, then back to the ball
SLEEP_AFTER = 60.0     # cursor still for this long (seconds) -> puppy goes to the kennel to sleep
ARRIVE_IDLE = 0.5      # cursor stillness (s) before the puppy sits down next to it
FOLLOW_RADIUS = 62     # how close the puppy stays to the cursor (pixels)
FAST_SPEED = 900       # cursor speed (px/s) that counts as "fast"  -> play time
CALM_SPEED = 300       # below this speed the puppy stops playing and comes to you
TICK_MS = 20           # animation step (20 ms = ~50 fps)

# --------------------------------------------------------------------------
# Platform / layout constants
# --------------------------------------------------------------------------
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

if IS_WIN:
    BG = "#ff00ff"            # colour key that Windows makes transparent
elif IS_MAC:
    BG = "systemTransparent"
else:
    BG = "#cfe8ff"            # Linux fallback: solid box

K = spr.SCALE                  # puppy size (set when the sprites were generated)
FW, FH, GROUND = spr.FRAME_W, spr.FRAME_H, spr.GROUND_Y   # puppy window size, feet line
AX = round(100 * K)            # x (in the sprite) that sits on the puppy's position
KS = K                         # kennel scale (matches the puppy)
KW, KH = round(300 * KS), round(292 * KS)                 # kennel window size
BALL = 22

RED = "#D64545"
ZZZ = "#7FA9F5"
OUTLINE = "#4F5964"

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".desktop_puppy.json")


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f)
    except Exception:
        pass


FOLLOW, WAIT, GO_HOME, SETTLE, SLEEP, WAKE, PLAY = (
    "follow", "wait", "go_home", "settle", "sleep", "wake", "play")


# --------------------------------------------------------------------------
# Bark sound (synthesised - no files needed)
# --------------------------------------------------------------------------
def make_bark_wav(f0, dur=0.30, rate=22050, seed=1):
    rnd = random.Random(seed)
    n = int(rate * dur)
    r = 0.965
    th = 2 * math.pi * 750 / rate
    a1, a2 = 2 * r * math.cos(th), -r * r
    y1 = y2 = lp = phase = 0.0
    raw = []
    for i in range(n):
        t = i / rate
        u = t / dur
        f = f0 * (1.35 - 0.75 * u)
        phase += 2 * math.pi * f / rate
        src = sum(math.sin(k * phase) / k for k in range(1, 12))
        lp += 0.3 * (rnd.uniform(-1, 1) - lp)
        x = src * 0.5 + lp * 0.8
        y = x + a1 * y1 + a2 * y2
        y2, y1 = y1, y
        s = 0.12 * y + 0.5 * x
        env = min(1.0, t / 0.012) * math.exp(-t * 10.5)
        raw.append(s * env)
    peak = max(abs(v) for v in raw) or 1.0
    pcm = b"".join(struct.pack("<h", int(v / peak * 0.85 * 32767)) for v in raw)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def app_dir():
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))


class Sound:
    def __init__(self):
        custom = os.path.join(app_dir(), "bark.wav")
        if os.path.exists(custom):
            with open(custom, "rb") as f:
                self.clips = [f.read()]
        else:
            self.clips = [make_bark_wav(f, seed=s) for f, s in ((470, 1), (540, 2), (610, 3))]
        self.paths = []
        if not IS_WIN:
            d = tempfile.mkdtemp(prefix="puppy_")
            for i, data in enumerate(self.clips):
                p = os.path.join(d, f"bark{i}.wav")
                with open(p, "wb") as f:
                    f.write(data)
                self.paths.append(p)

    def bark(self):
        i = random.randrange(len(self.clips))
        try:
            if IS_WIN:
                import winsound
                winsound.PlaySound(self.clips[i], winsound.SND_MEMORY | winsound.SND_ASYNC)
            else:
                cmds = [["afplay"]] if IS_MAC else [["paplay"], ["aplay", "-q"], ["play", "-q"]]
                for c in cmds:
                    try:
                        subprocess.Popen(c + [self.paths[i]], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
                        break
                    except FileNotFoundError:
                        continue
        except Exception:
            pass


# --------------------------------------------------------------------------
# Global click detection
# --------------------------------------------------------------------------
class ClickWatcher:
    """Detects mouse clicks anywhere on screen (Windows built-in, else pynput if installed)."""

    def __init__(self):
        self.flag = False
        self.prev = False
        self.user32 = None
        if IS_WIN:
            try:
                import ctypes
                self.user32 = ctypes.windll.user32
            except Exception:
                pass
        else:
            try:
                from pynput import mouse

                def on_click(x, y, button, pressed):
                    if pressed:
                        self.flag = True
                self.listener = mouse.Listener(on_click=on_click)
                self.listener.daemon = True
                self.listener.start()
            except Exception:
                pass

    def poll(self):
        if self.user32:
            down = bool((self.user32.GetAsyncKeyState(0x01) | self.user32.GetAsyncKeyState(0x02)) & 0x8000)
            clicked = down and not self.prev
            self.prev = down
            return clicked
        c, self.flag = self.flag, False
        return c


# --------------------------------------------------------------------------
# Window helpers
# --------------------------------------------------------------------------
def enable_dpi_awareness():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def prepare(win, w, h, x, y):
    win.overrideredirect(True)
    win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
    win.attributes("-topmost", True)
    win.configure(bg=BG)
    if IS_WIN:
        win.attributes("-transparentcolor", BG)
    elif IS_MAC:
        win.attributes("-transparent", True)


def make_click_through(win):
    if not IS_WIN:
        return
    try:
        import ctypes
        win.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x80)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Sprites
# --------------------------------------------------------------------------
class Frame:
    """One animation frame in both facing directions."""

    def __init__(self, master, entry):
        ox, oy, w, h, b64 = entry
        self.right = tk.PhotoImage(master=master, data=b64, format="gif")
        self.oy = oy
        self.ox_r = ox
        self.ox_l = FW - (ox + w)
        self.left = self._mirror(master, self.right, w, h)

    @staticmethod
    def _mirror(master, img, w, h):
        out = tk.PhotoImage(master=master, width=w, height=h)
        try:
            for x in range(w):
                out.tk.call(str(out), "copy", str(img), "-from", x, 0, x + 1, h,
                            "-to", w - 1 - x, 0, "-compositingrule", "set")
            return out
        except Exception:
            return img          # worst case: puppy keeps facing right


def draw_kennel(c):
    """A cosy blue-roofed wooden dog house with a name plate and a help sign (drawn in 300x292 units)."""
    wood, plank, dark_wood = "#D79A5B", "#C0854A", "#7A4A22"
    roof, roof_dk, roof_lt = "#3F78B5", "#244E7E", "#5E96CF"
    # grass + flowers
    c.create_rectangle(8, 212, 292, 222, fill="#5FA04A", outline="")
    for x in range(14, 290, 9):
        c.create_line(x, 212, x - 2, 206, fill="#5FA04A", width=2)
        c.create_line(x + 3, 212, x + 5, 207, fill="#4C8A3A", width=2)
    for fx, col in ((22, "#FF8FA3"), (274, "#FFD84D")):
        c.create_line(fx, 212, fx, 198, fill="#3F7A30", width=2)
        c.create_oval(fx - 5, 192, fx + 5, 202, fill=col, outline="")
        c.create_oval(fx - 2, 195, fx + 2, 199, fill="#FFF3C4", outline="")
    # walls
    c.create_rectangle(30, 94, 270, 213, fill=wood, outline=dark_wood, width=3)
    for x in range(54, 270, 24):
        c.create_line(x, 98, x, 212, fill=plank, width=2)
    c.create_rectangle(30, 202, 270, 213, fill=plank, outline=dark_wood, width=2)           # base board
    # roof (with shingle rows) + trim
    c.create_polygon(4, 100, 150, 8, 296, 100, fill=roof, outline=roof_dk, width=3)
    for y, hw in ((34, 38), (54, 70), (74, 102), (92, 130)):
        c.create_line(150 - hw, y, 150 + hw, y, fill=roof_dk, width=2)
        for x in range(int(150 - hw) + 14, int(150 + hw) - 6, 28):
            c.create_line(x, y, x, y + 14, fill=roof_lt, width=1)
    c.create_rectangle(2, 98, 298, 108, fill=roof_dk, outline="")                           # eave trim
    # name plate
    c.create_rectangle(88, 50, 212, 80, fill="#FFF3C4", outline=dark_wood, width=3)
    c.create_text(150, 65, text="PUPPY HOME", fill="#5A3416", font=("Arial", -11, "bold"))
    # door: arch + frame
    c.create_oval(66, 110, 234, 180, fill="#F3D9A8", outline="")
    c.create_rectangle(66, 146, 234, 213, fill="#F3D9A8", outline="")
    c.create_oval(76, 120, 224, 180, fill="#2A1B12", outline="")
    c.create_rectangle(76, 150, 224, 213, fill="#2A1B12", outline="")
    c.create_arc(66, 110, 234, 180, start=0, extent=180, style="arc", outline=dark_wood, width=3)
    c.create_line(66, 146, 66, 213, fill=dark_wood, width=3)
    c.create_line(234, 146, 234, 213, fill=dark_wood, width=3)
    # help sign (readable text, sized in real pixels)
    c.create_rectangle(36, 226, 264, 288, fill="#FFF3C4", outline=dark_wood, width=3)
    c.create_text(150, 238, text="Click: open apps", fill="#5A3416", font=("Arial", -11, "bold"))
    c.create_text(150, 257, text="Drag: move", fill="#5A3416", font=("Arial", -11, "bold"))
    c.create_text(150, 276, text="Right-click: quit", fill="#B03030", font=("Arial", -11, "bold"))
    c.scale("all", 0, 0, KS, KS)


class Ball:
    def __init__(self):
        self.x = self.y = self.z = 0.0
        self.vx = self.vy = self.vz = 0.0


# --------------------------------------------------------------------------
# Monitors
# --------------------------------------------------------------------------
def get_monitors(root):
    """Return [(left, top, right, bottom), ...] for every connected screen (primary first)."""
    mons = []
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes
            proc_t = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HANDLE, wintypes.HDC,
                                        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

            def cb(hmon, hdc, rect, data):
                r = rect.contents
                mons.append((r.left, r.top, r.right, r.bottom))
                return 1
            ctypes.windll.user32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
        except Exception:
            mons = []
    if not mons:
        try:
            vx, vy = root.winfo_vrootx(), root.winfo_vrooty()
            vw, vh = root.winfo_vrootwidth(), root.winfo_vrootheight()
            if vw > 0 and vh > 0:
                mons = [(vx, vy, vx + vw, vy + vh)]
        except Exception:
            pass
    if not mons:
        mons = [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]
    mons.sort(key=lambda m: (m[0] != 0 or m[1] != 0))       # primary monitor (at 0,0) first
    return mons


# --------------------------------------------------------------------------
# Open applications (list + polite close request)
# --------------------------------------------------------------------------
class AppList:
    """Lists open application windows and asks them to close (like clicking their X)."""
    SKIP_CLASSES = {"Progman", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "WorkerW"}

    def __init__(self):
        self.u = self.dwm = None
        if IS_WIN:
            try:
                self._init_win()
            except Exception:
                self.u = None

    def _init_win(self):
        import ctypes
        from ctypes import wintypes as W
        u = ctypes.WinDLL("user32", use_last_error=True)     # private copy: no clash with other code
        self.enum_t = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        u.EnumWindows.argtypes = [self.enum_t, W.LPARAM]
        u.IsWindowVisible.argtypes = [W.HWND]
        u.GetWindow.argtypes = [W.HWND, W.UINT]
        u.GetWindow.restype = W.HWND
        u.GetWindowLongW.argtypes = [W.HWND, ctypes.c_int]
        u.GetWindowTextLengthW.argtypes = [W.HWND]
        u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
        u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        self.u = u
        try:
            d = ctypes.WinDLL("dwmapi")
            d.DwmGetWindowAttribute.argtypes = [W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD]
            self.dwm = d
        except Exception:
            self.dwm = None

    # ---- listing ----
    def list(self):
        """Returns (items, note). items = [(id, title), ...] sorted by title."""
        try:
            if IS_WIN:
                if not self.u:
                    return [], "Could not access the Windows window list."
                return self._list_win(), ""
            if IS_MAC:
                return self._list_mac(), ""
            return self._list_linux()
        except Exception:
            return [], "Could not read the list of open apps."

    def _list_win(self):
        import ctypes
        from ctypes import wintypes as W
        u, out, me = self.u, [], os.getpid()

        def cb(hwnd, lparam):
            try:
                if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, 4):      # hidden / owned popup
                    return True
                ex = u.GetWindowLongW(hwnd, -20)
                if (ex & 0x80 and not ex & 0x40000) or ex & 0x08000000:     # tool / no-activate windows
                    return True
                if self.dwm:
                    cloaked = W.DWORD(0)
                    self.dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
                    if cloaked.value:                                        # on another virtual desktop etc.
                        return True
                n = u.GetWindowTextLengthW(hwnd)
                if n <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, buf, n + 1)
                title = buf.value.strip()
                if not title:
                    return True
                cls = ctypes.create_unicode_buffer(256)
                u.GetClassNameW(hwnd, cls, 256)
                if cls.value in self.SKIP_CLASSES:
                    return True
                pid = W.DWORD(0)
                u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == me:                                          # never list the puppy itself
                    return True
                out.append((int(hwnd), title))
            except Exception:
                pass
            return True

        u.EnumWindows(self.enum_t(cb), 0)
        out.sort(key=lambda it: it[1].lower())
        return out

    def _list_mac(self):
        r = subprocess.run(["osascript", "-e",
                            'tell application "System Events" to get name of '
                            '(processes where background only is false)'],
                           capture_output=True, text=True, timeout=4)
        skip = {"Finder", "Python", "Python3", "python3", "DesktopPuppy", "Desktop Puppy"}
        names = sorted({n.strip() for n in r.stdout.split(",") if n.strip()} - skip, key=str.lower)
        return [(n, n) for n in names]

    def _list_linux(self):
        import shutil
        if not shutil.which("wmctrl"):
            return [], "Install 'wmctrl' (sudo apt install wmctrl) to list open apps."
        r = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=4)
        out = []
        for line in r.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4 and parts[1] != "-1" and parts[3].strip():
                out.append((parts[0], parts[3].strip()))
        out.sort(key=lambda it: it[1].lower())
        return out, ""

    # ---- details (shown when hovering an app name) ----
    def details(self, hid, title):
        """Full title plus, where the OS allows, the program name, its location and process id."""
        lines = [title]
        try:
            if IS_WIN and self.u:
                import ctypes
                from ctypes import wintypes as W
                pid = W.DWORD(0)
                self.u.GetWindowThreadProcessId(hid, ctypes.byref(pid))
                k = ctypes.WinDLL("kernel32", use_last_error=True)
                k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
                k.OpenProcess.restype = W.HANDLE
                k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]
                k.CloseHandle.argtypes = [W.HANDLE]
                path = ""
                h = k.OpenProcess(0x1000, False, pid.value)                  # PROCESS_QUERY_LIMITED_INFORMATION
                if h:
                    buf, n = ctypes.create_unicode_buffer(1024), W.DWORD(1024)
                    if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                        path = buf.value
                    k.CloseHandle(h)
                lines.append("")
                if path:
                    lines += [f"Program:  {os.path.basename(path)}", f"Location:  {path}"]
                lines.append(f"Process ID:  {pid.value}")
            elif IS_MAC:
                lines += ["", f"Application:  {hid}"]
            else:
                lines += ["", f"Window ID:  {hid}"]
        except Exception:
            pass
        return "\n".join(lines)

    # ---- closing ----
    def close(self, hid):
        """Ask the app to close (same as clicking its X) - it may still ask to save work."""
        try:
            if IS_WIN:
                self.u.PostMessageW(hid, 0x0010, 0, 0)                       # WM_CLOSE
            elif IS_MAC:
                name = str(hid).replace("\\", "").replace('"', "")
                subprocess.Popen(["osascript", "-e", f'tell application "{name}" to quit'])
            else:
                subprocess.Popen(["wmctrl", "-ic", str(hid)])
        except Exception:
            pass


class AppPanel:
    """A little pop-up list of open apps with a Close button each, shown beside the kennel."""
    PW_CHARS = 38
    MAX_ROWS = 10

    def __init__(self, app):
        self.app = app
        self.state = None
        self.visible = False
        self.job = None
        self.tip = None
        self.tip_job = None
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#7A2E24")
        self.inner = tk.Frame(self.win, bg="#FFF7E6")
        self.inner.pack(padx=2, pady=2)
        head = tk.Frame(self.inner, bg="#B5483A")
        head.pack(fill="x")
        tk.Label(head, text="Open applications", bg="#B5483A", fg="white",
                 font=("Arial", 10, "bold")).pack(side="left", padx=8, pady=5)
        tk.Button(head, text="x", command=self.hide, bg="#B5483A", fg="white", relief="flat", bd=0,
                  font=("Arial", 10, "bold"), activebackground="#96382D", activeforeground="white",
                  cursor="hand2").pack(side="right", padx=6)
        self.body = tk.Frame(self.inner, bg="#FFF7E6")
        self.body.pack(fill="x")
        tk.Label(self.inner, text="Hover a name for full details. Close asks the app to quit - it may ask you to save first.",
                 bg="#FFF7E6", fg="#8A5A2B", font=("Arial", 8)).pack(fill="x", padx=8, pady=(2, 6))
        self.win.withdraw()

    def toggle(self):
        self.hide() if self.visible else self.show()

    def show(self):
        self.visible = True
        self.refresh(force=True)
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.win.lift()
        self._schedule()

    # ---- hover tooltip with the app's full details ----
    def hide_tip(self):
        if self.tip_job is not None:
            try:
                self.win.after_cancel(self.tip_job)
            except Exception:
                pass
            self.tip_job = None
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None

    def show_tip(self, widget, hid, title):
        self.hide_tip()
        try:
            text = self.app.apps.details(hid, title)
            tip = tk.Toplevel(self.win)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            tk.Label(tip, text=text, justify="left", anchor="w", wraplength=460, bg="#FFFBE6", fg="#3B2A1A",
                     relief="solid", bd=1, font=("Arial", 9), padx=9, pady=7).pack()
            tip.update_idletasks()
            w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
            l, t, r, b = self.app.monitor_for(widget.winfo_rootx(), widget.winfo_rooty())
            x = max(l, min(widget.winfo_rootx(), r - w - 4))
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            if y + h > b:
                y = widget.winfo_rooty() - h - 4
            tip.geometry(f"+{int(x)}+{int(y)}")
            self.tip = tip
        except Exception:
            self.tip = None

    def hover(self, row, label, hid, title, on):
        bg = "#FFE7B0" if on else "#FFF7E6"
        row.configure(bg=bg)
        label.configure(bg=bg)
        if on:
            self.hide_tip()
            self.tip_job = self.win.after(350, lambda: self.show_tip(label, hid, title))
        else:
            self.hide_tip()

    def hide(self):
        self.hide_tip()
        self.visible = False
        if self.job is not None:
            try:
                self.win.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        self.win.withdraw()

    def _schedule(self):
        if self.job is not None:
            try:
                self.win.after_cancel(self.job)
            except Exception:
                pass
        self.job = self.win.after(2000, self._poll)

    def _poll(self):
        self.job = None
        if self.visible:
            self.refresh()
            self._schedule()

    def refresh(self, force=False):
        items, note = self.app.apps.list()
        key = (tuple(items), note)
        if key == self.state and not force:
            return
        self.state = key
        self.hide_tip()
        for w in self.body.winfo_children():
            w.destroy()
        if not items:
            tk.Label(self.body, text=note or "No open applications found.", bg="#FFF7E6", fg="#6B3F1B",
                     font=("Arial", 9), wraplength=300, justify="left").pack(padx=10, pady=10)
        for hid, title in items[:self.MAX_ROWS]:
            row = tk.Frame(self.body, bg="#FFF7E6")
            row.pack(fill="x", padx=6, pady=2)
            short = title if len(title) <= self.PW_CHARS else title[:self.PW_CHARS - 1] + "..."
            lbl = tk.Label(row, text=short, width=self.PW_CHARS, anchor="w", bg="#FFF7E6", fg="#3B2A1A",
                           font=("Arial", 9), cursor="question_arrow")
            lbl.pack(side="left")
            for w in (row, lbl):
                w.bind("<Enter>", lambda e, r=row, l=lbl, h=hid, t=title: self.hover(r, l, h, t, True))
                w.bind("<Leave>", lambda e, r=row, l=lbl, h=hid, t=title: self.hover(r, l, h, t, False))
            tk.Button(row, text="Close", command=lambda h=hid: self.close(h), bg="#D64545", fg="white",
                      relief="flat", font=("Arial", 8, "bold"), activebackground="#B03030",
                      activeforeground="white", cursor="hand2", padx=8).pack(side="right")
        if len(items) > self.MAX_ROWS:
            tk.Label(self.body, text=f"+ {len(items) - self.MAX_ROWS} more open", bg="#FFF7E6",
                     fg="#8A5A2B", font=("Arial", 8)).pack(pady=(0, 4))
        self.reposition()

    def close(self, hid):
        self.app.apps.close(hid)
        self.win.after(900, lambda: self.refresh() if self.visible else None)

    def reposition(self):
        """Sit next to the kennel, wherever it has been placed."""
        a = self.app
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        l, t, r, b = a.monitor_for(a.kx + KW / 2, a.ky + KH / 2)
        x = a.kx - w - 8                                   # prefer the left of the kennel
        if x < l:
            x = a.kx + KW + 8                              # else the right
        if x + w > r:
            x = max(l, min(a.kx, r - w))                   # else directly above/below it
        y = a.ky + KH - h
        if x < a.kx + KW and x + w > a.kx:
            y = a.ky - h - 8
            if y < t:
                y = a.ky + KH + 8
        y = max(t, min(y, b - h))
        self.win.geometry(f"+{int(x)}+{int(y)}")


# --------------------------------------------------------------------------
# The app
# --------------------------------------------------------------------------
class PuppyApp:
    def __init__(self):
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("Desktop Puppy")
        self.mons = get_monitors(self.root)
        self.sound = Sound()
        self.clicks = ClickWatcher()
        self.apps = AppList()

        # sprites (both directions)
        self.frames = {n: Frame(self.root, e) for n, e in spr.FRAMES.items() if n != "ball"}
        self.ball_img = tk.PhotoImage(master=self.root, data=spr.FRAMES["ball"][4], format="gif")
        s0 = spr.FRAMES["sleep0"]
        self.sleep_dx = AX - (s0[0] + s0[2] / 2.0)        # centre the sleeping pup in the doorway

        # kennel: remembered position (if that screen still exists), else primary screen bottom-right
        self.kx, self.ky = self.default_kennel()
        cfg = load_config()
        try:
            kx, ky = int(cfg["kx"]), int(cfg["ky"])
            if self.point_in_monitors(kx + KW / 2, ky + KH / 2):
                self.kx, self.ky = kx, ky
        except Exception:
            pass
        self.drag = None
        self.kennel = tk.Toplevel(self.root)
        prepare(self.kennel, KW, KH, self.kx, self.ky)
        kc = tk.Canvas(self.kennel, width=KW, height=KH, bg=BG, highlightthickness=0, bd=0)
        try:
            kc.configure(cursor="fleur")
        except Exception:
            pass
        kc.pack()
        draw_kennel(kc)
        kc.bind("<ButtonPress-1>", self.kennel_press)
        kc.bind("<B1-Motion>", self.kennel_motion)
        kc.bind("<ButtonRelease-1>", self.kennel_release)
        for ev in ("<Button-2>", "<Button-3>"):
            kc.bind(ev, lambda e: self.quit())
        self.panel = AppPanel(self)

        # ball window (hidden until play time)
        self.ballwin = tk.Toplevel(self.root)
        prepare(self.ballwin, BALL, BALL, -200, -200)
        bc = tk.Canvas(self.ballwin, width=BALL, height=BALL, bg=BG, highlightthickness=0, bd=0)
        bc.pack()
        bc.create_image(0, 0, anchor="nw", image=self.ball_img)
        self.root.update_idletasks()
        make_click_through(self.ballwin)
        self.ballwin.withdraw()
        self.ball = Ball()

        # puppy window
        prepare(self.root, FW, FH, 0, 0)
        self.canvas = tk.Canvas(self.root, width=FW, height=FH, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", lambda e: self.bark())
        self.sprite_item = self.canvas.create_image(0, 0, anchor="nw")
        self.root.update_idletasks()
        make_click_through(self.root)

        # state: start asleep in the kennel
        now = time.time()
        self.x, self.y = self.door
        self.facing = 1
        self.walk_phase = 0.0
        self.last_t = now
        self.prev_mouse = self.last_mouse = self.root.winfo_pointerxy()
        self.last_move = now
        self.mouse_speed = 0.0
        self.fast_time = 0.0
        self.calm_time = 0.0
        self.state = SLEEP
        self.state_t = now
        self.anchor = self.last_mouse
        self.activity = None
        self.play_mode = "cursor"
        self.play_t = now
        self.kick_ready = 0.0
        self.kick_until = 0.0
        self.last_bark = 0.0
        self.bark_until = 0.0
        self.ticks = 0

    # ---------------- monitors ----------------
    def point_in_monitors(self, x, y):
        return any(l <= x < r and t <= y < b for l, t, r, b in self.mons)

    def monitor_for(self, x, y):
        """The monitor containing (x, y), or the nearest one."""
        best, bd = self.mons[0], None
        for m in self.mons:
            l, t, r, b = m
            dx, dy = max(l - x, 0, x - r), max(t - y, 0, y - b)
            d = dx * dx + dy * dy
            if bd is None or d < bd:
                best, bd = m, d
        return best

    def default_kennel(self):
        l, t, r, b = self.mons[0]
        return r - KW - 20, b - KH - 55

    def refresh_monitors(self):
        """Pick up monitors being plugged in / unplugged."""
        new = get_monitors(self.root)
        if new == self.mons:
            return
        self.mons = new
        if not self.point_in_monitors(self.kx + KW / 2, self.ky + KH / 2):   # its screen went away
            self.kx, self.ky = self.default_kennel()
            self.kennel.geometry(f"+{self.kx}+{self.ky}")
            if self.state in (SLEEP, SETTLE):
                self.x, self.y = self.door
            if self.panel.visible:
                self.panel.reposition()

    # ---------------- kennel (draggable, click = app list) ----------------
    @property
    def door(self):
        """Where the puppy's feet go when it sleeps - follows the kennel wherever it is."""
        return (self.kx + KW / 2 + self.sleep_dx, self.ky + 212 * KS)

    def kennel_press(self, e):
        self.drag = {"ox": e.x_root - self.kx, "oy": e.y_root - self.ky,
                     "sx": e.x_root, "sy": e.y_root, "moved": False}

    def kennel_motion(self, e):
        d = self.drag
        if not d:
            return
        if not d["moved"] and math.hypot(e.x_root - d["sx"], e.y_root - d["sy"]) < 5:
            return
        d["moved"] = True
        l, t, r, b = self.monitor_for(e.x_root, e.y_root)           # can be dragged onto any screen
        self.kx = int(min(max(e.x_root - d["ox"], l), max(l, r - KW)))
        self.ky = int(min(max(e.y_root - d["oy"], t), max(t, b - KH)))
        self.kennel.geometry(f"+{self.kx}+{self.ky}")
        if self.state in (SLEEP, SETTLE):                           # a sleeping puppy rides along
            self.x, self.y = self.door
        if self.panel.visible:
            self.panel.reposition()

    def kennel_release(self, e):
        d, self.drag = self.drag, None
        if d is None:
            return
        if d["moved"]:
            save_config({"kx": self.kx, "ky": self.ky})             # remember the new spot
        else:
            self.panel.toggle()                                     # plain click = open/close app list

    # ---------------- helpers ----------------
    def quit(self):
        self.root.destroy()

    def set_state(self, state, mouse=None):
        self.state = state
        self.state_t = time.time()
        if mouse is not None:
            self.anchor = mouse
        self.root.attributes("-topmost", True)

    def bark(self):
        now = time.time()
        if now - self.last_bark < 0.4:
            return
        self.last_bark = now
        self.bark_until = now + 0.45
        self.sound.bark()
        if self.state in (SLEEP, SETTLE):
            self.set_state(WAKE)

    def clamp(self, x, y):
        """Keep the puppy's feet on the nearest monitor."""
        l, t, r, b = self.monitor_for(x, y)
        m = min(110 * K, (r - l) / 2 - 1)
        return (min(max(x, l + m), r - m), min(max(y, t + GROUND + 4), b - 8))

    def random_point(self):
        l, t, r, b = random.choice(self.mons)
        return (random.uniform(l + 90, max(l + 91, r - 90)),
                random.uniform(t + GROUND + 20, max(t + GROUND + 21, b - 30)))

    def step(self, tx, ty, dt, vmax, dead):
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        if dist <= max(dead, 1.5) or dt <= 0:
            return 0.0
        v = min(vmax, max(70, dist * 6))
        mv = min(dist, v * dt)
        self.x += dx / dist * mv
        self.y += dy / dist * mv
        if abs(dx) > 3:
            self.facing = 1 if dx > 0 else -1
        return mv / dt

    # ---------------- play ----------------
    def start_play(self, mode="cursor", activity=None):
        """mode 'cursor': cursor is being flicked.  mode 'idle': cursor still -> roam, ball 15 s / bone 5 s."""
        self.play_mode = mode
        self.activity = activity or random.choice(("ball", "bone"))
        self.calm_time = 0.0
        self.play_t = time.time()
        self.set_state(PLAY)
        if self.activity == "ball":
            self.place_ball()

    def place_ball(self):
        b = self.ball
        b.x, b.y = self.clamp(self.x + self.facing * 100 * K, self.y)
        b.z, b.vx, b.vy, b.vz = 0.0, self.facing * 160 * K, 0.0, 380.0 * K
        self.kick_ready = time.time() + 0.3
        self.ballwin.deiconify()
        self.ballwin.attributes("-topmost", True)

    def end_play(self):
        self.ballwin.withdraw()
        self.activity = None

    def keep_ball_on_screen(self, b):
        """Let the ball roll freely across monitors; bounce it only off the outer edges of the desktop."""
        for l, t, r, bm in self.mons:
            if l <= b.x <= r and t + GROUND + 10 <= b.y <= bm - 20:
                return                                              # inside some monitor: fine
        best = None
        for l, t, r, bm in self.mons:                               # outside all: pull back to the nearest one
            lo_y, hi_y = t + GROUND + 10, bm - 20
            cx, cy = min(max(b.x, l + 12), r - 12), min(max(b.y, lo_y), max(lo_y, hi_y))
            d = (cx - b.x) ** 2 + (cy - b.y) ** 2
            if best is None or d < best[0]:
                best = (d, cx, cy)
        _, cx, cy = best
        if cx > b.x:
            b.vx = abs(b.vx)
        elif cx < b.x:
            b.vx = -abs(b.vx)
        if cy > b.y:
            b.vy = abs(b.vy)
        elif cy < b.y:
            b.vy = -abs(b.vy)
        b.x, b.y = cx, cy

    def update_ball(self, dt, now, roam=False):
        b = self.ball
        b.x += b.vx * dt
        b.y += b.vy * dt
        b.z += b.vz * dt
        b.vz -= 1500 * K * dt
        if b.z <= 0:
            b.z = 0.0
            b.vz = -b.vz * 0.55 if b.vz < -150 * K else 0.0
            k = max(0.0, 1 - 2.2 * dt)
            b.vx *= k
            b.vy *= k
        self.keep_ball_on_screen(b)

        dirx = 1 if b.x > self.x else -1
        tx, ty = self.clamp(b.x - dirx * 62 * K, b.y)
        speed = self.step(tx, ty, dt, 560, 4)
        if speed == 0:
            self.facing = dirx
        near = abs(b.x - self.x) < 80 * K and abs(b.y - self.y) < 18 * K and b.z < 28 * K
        if near and now > self.kick_ready:                          # boop! nudge the ball away
            if roam:                                                # wander: send it somewhere across the desktop
                gx, gy = self.random_point()
                ang = math.atan2(gy - b.y, gx - b.x)
                sp = random.uniform(500, 1000) * K
                b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
            else:
                b.vx = dirx * random.uniform(300, 540) * K
                b.vy = random.uniform(-150, 150) * K
            b.vz = random.uniform(260, 430) * K
            self.kick_ready = now + 0.55
            self.kick_until = now + 0.28
            self.facing = dirx
        self.ballwin.geometry(f"+{int(b.x - BALL / 2)}+{int(b.y - b.z - BALL)}")
        return speed

    # ---------------- main loop ----------------
    def tick(self):
        now = time.time()
        dt = max(0.001, min(now - self.last_t, 0.1))
        self.last_t = now

        if self.clicks.poll():
            self.bark()

        mx, my = self.root.winfo_pointerxy()                        # virtual-desktop coordinates (all monitors)
        inst = math.hypot(mx - self.prev_mouse[0], my - self.prev_mouse[1]) / dt
        self.prev_mouse = (mx, my)
        self.mouse_speed += (inst - self.mouse_speed) * min(1.0, dt * 8)
        if math.hypot(mx - self.last_mouse[0], my - self.last_mouse[1]) > 2:
            self.last_mouse = (mx, my)
            self.last_move = now
        idle = now - self.last_move

        self.fast_time = self.fast_time + dt if self.mouse_speed > FAST_SPEED else max(0.0, self.fast_time - dt * 2)
        self.calm_time = self.calm_time + dt if self.mouse_speed < CALM_SPEED else 0.0

        speed, hop = 0.0, 0.0

        if self.state == FOLLOW:
            if self.fast_time > 0.3:
                self.fast_time = 0.0
                self.start_play("cursor")
            else:
                d = math.hypot(self.x - mx, self.y - my)
                ux, uy = ((self.x - mx) / d, (self.y - my) / d) if d > 1.5 else (-1.0, 0.0)
                tx, ty = self.clamp(mx + ux * FOLLOW_RADIUS, my + uy * FOLLOW_RADIUS)
                speed = self.step(tx, ty, dt, 650, 10)
                if speed == 0:
                    self.facing = 1 if mx > self.x else -1
                    if idle > ARRIVE_IDLE:                          # arrived + cursor is still -> sit & beg
                        self.set_state(WAIT, (mx, my))

        elif self.state == WAIT:
            self.facing = 1 if mx > self.x else -1
            if self.fast_time > 0.3 or math.hypot(mx - self.anchor[0], my - self.anchor[1]) > 30:
                self.set_state(FOLLOW)                              # cursor moved -> get up, follow
            elif idle > SLEEP_AFTER:
                self.set_state(GO_HOME)
            elif now - self.state_t > WAIT_SECONDS:                 # paw-waving didn't work -> go play
                self.start_play("idle", "ball")

        elif self.state == PLAY:
            if self.play_mode == "cursor":
                if self.calm_time > 0.7:                            # cursor slowed/stopped -> run to it
                    self.end_play()
                    self.set_state(FOLLOW)
                elif self.activity == "ball":
                    speed = self.update_ball(dt, now)
            else:                                                   # cursor is still: roam & play
                if idle < 0.3 or math.hypot(mx - self.anchor[0], my - self.anchor[1]) > 30:
                    self.end_play()
                    self.set_state(FOLLOW)                          # cursor moved -> come running
                elif idle > SLEEP_AFTER:
                    self.end_play()
                    self.set_state(GO_HOME)                         # 60 s of nothing -> bed time
                else:
                    dur = BALL_SECONDS if self.activity == "ball" else BONE_SECONDS
                    if now - self.play_t > dur:                     # ball 15 s -> bone 5 s -> ball ...
                        nxt = "bone" if self.activity == "ball" else "ball"
                        self.end_play()
                        self.activity = nxt
                        self.play_t = now
                        if nxt == "ball":
                            self.place_ball()
                    if self.activity == "ball":
                        speed = self.update_ball(dt, now, roam=True)

        elif self.state == GO_HOME:
            if self.fast_time > 0.3 or idle < 0.3:
                self.set_state(FOLLOW)
            else:
                speed = self.step(self.door[0], self.door[1], dt, 420, 0)
                if math.hypot(self.x - self.door[0], self.y - self.door[1]) < 3:
                    self.x, self.y = self.door
                    self.facing = 1
                    self.set_state(SETTLE)

        elif self.state == SETTLE:
            if idle < 0.3:
                self.set_state(WAKE)
            elif now - self.state_t > 1.2:
                self.set_state(SLEEP, (mx, my))

        elif self.state == SLEEP:
            if math.hypot(mx - self.anchor[0], my - self.anchor[1]) > 25:
                self.set_state(WAKE)

        elif self.state == WAKE:
            prog = (now - self.state_t) / 0.9
            hop = abs(math.sin(prog * math.pi * 2)) * 10 * K
            self.facing = 1 if mx > self.x else -1
            if prog >= 1:
                self.last_move = now
                self.set_state(FOLLOW)

        # ---- pick & draw the frame ----
        barking = now < self.bark_until
        if now < self.kick_until:
            q = 1 - (self.kick_until - now) / 0.28
            hop = max(hop, math.sin(q * math.pi) * 6 * K)
        self.walk_phase += min(speed / (43.0 * K), 4.0) * dt

        flip = self.facing < 0
        name = self.pick_frame(now, speed, barking)
        fr = self.frames[name]
        self.canvas.itemconfig(self.sprite_item, image=(fr.left if flip else fr.right))
        self.canvas.coords(self.sprite_item, fr.ox_l if flip else fr.ox_r, fr.oy)
        self.draw_overlays(now, flip, barking)

        ax = (FW - AX) if flip else AX
        self.root.geometry(f"+{int(self.x - ax)}+{int(self.y - GROUND - hop)}")

        self.ticks += 1
        if self.ticks % 100 == 0:
            self.refresh_monitors()
            self.kennel.attributes("-topmost", True)
            self.root.attributes("-topmost", True)
            if self.panel.visible:
                self.panel.win.attributes("-topmost", True)
        self.root.after(TICK_MS, self.tick)

    def pick_frame(self, now, speed, barking):
        s = self.state
        if s == SLEEP:
            return f"sleep{int(now / 0.35) % 4}"
        if s == SETTLE:
            return "drowsy"
        if s == PLAY and self.activity == "bone":
            return f"chew{int(now / 0.12) % 6}"
        if s == WAIT:
            if barking:
                return "sit_bark"
            if (now % 3.7) < 0.14:
                return "sit_blink"
            return f"sit{int((now - self.state_t) / 0.11) % 8}"
        if barking:
            return "bark1" if int(now * 12) % 2 else "bark0"
        if now < self.kick_until:
            return "kick"
        if speed > 25:
            return f"run{int((self.walk_phase % 1.0) * 8) % 8}"
        if (now % 3.3) < 0.12:
            return "stand_blink"
        return f"stand{int(now / 0.1) % 6}"

    def draw_overlays(self, now, flip, barking):
        c = self.canvas
        c.delete("ov")
        X = (lambda x: FW - x * K) if flip else (lambda x: x * K)
        if barking:                                              # speech bubble
            pts = [(126, 2), (184, 2), (184, 24), (152, 24), (144, 34), (140, 24), (126, 24)]
            c.create_polygon(*[v for x, y in pts for v in (X(x), y * K)], fill="white", outline=OUTLINE,
                             width=2, tags="ov")
            c.create_text(X(155), 13 * K, text="Woof!", fill="#333333", font=("Arial", 9, "bold"), tags="ov")
        elif self.state == WAKE:                                 # "!"
            c.create_line(X(150), 4, X(150), 15, fill=RED, width=3, capstyle="round", tags="ov")
            c.create_oval(X(150) - 2, 19, X(150) + 2, 23, fill=RED, outline="", tags="ov")
        if self.state == SLEEP:                                  # floating Zzz
            for i in range(3):
                ph = (now * 0.55 + i / 3.0) % 1.0
                zx, zy, zs = 118 + ph * 24, 100 - ph * 62, (5 + ph * 10)
                pts = [(zx, zy), (zx + zs, zy), (zx, zy + zs), (zx + zs, zy + zs)]
                c.create_line(*[v for x, y in pts for v in (X(x), y * K)], fill=ZZZ, width=2, tags="ov")

    def run(self):
        print("Puppy is asleep in the kennel. Move your mouse to wake it up!")
        print(f"{len(self.mons)} monitor(s) detected. Click the kennel for the open-apps list, drag it to move it.")
        self.root.after(TICK_MS, self.tick)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass


def already_running():
    """True if another Desktop Puppy is running (Windows named mutex), so it never shows up twice."""
    if not IS_WIN:
        return False
    try:
        import ctypes
        global _MUTEX
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\DesktopPuppy_SingleInstance")
        return ctypes.windll.kernel32.GetLastError() == 183          # ERROR_ALREADY_EXISTS
    except Exception:
        return False


if __name__ == "__main__":
    if not already_running():
        PuppyApp().run()
