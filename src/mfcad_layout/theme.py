"""Colours, fonts and ttk styles shared by every window."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

BG = "#eef1f5"          # window
SIDE = "#f8f9fb"        # side panels
CARD = "#ffffff"
BORDER = "#dde2e8"
TEXT = "#1f2933"
MUTED = "#6b7785"
ACCENT = "#3b5bdb"
ACCENT_DARK = "#2f4ac0"
ACCENT_SOFT = "#e5eaff"
SELECT_BG = "#e5eaff"
HOVER = "#e9edf3"
GOOD = "#2b8a3e"
GOOD_SOFT = "#e6f6ea"
BAD = "#e03131"
BAD_SOFT = "#fdecec"

FONT = ("TkDefaultFont", 10)
FONT_SMALL = ("TkDefaultFont", 9)
FONT_BOLD = ("TkDefaultFont", 10, "bold")
FONT_HEAD = ("TkDefaultFont", 9, "bold")
FONT_TITLE = ("TkDefaultFont", 13, "bold")
FONT_MONO = ("TkFixedFont", 9)

_PREFERRED = ("Inter", "Segoe UI", "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue",
              "Cantarell", "Noto Sans", "Ubuntu", "DejaVu Sans")


def init(root: tk.Tk) -> ttk.Style:
    """Pick a font, set the ttk styles. Call once, right after Tk()."""
    global FONT, FONT_SMALL, FONT_BOLD, FONT_HEAD, FONT_TITLE
    fams = set(tkfont.families(root))
    fam = next((f for f in _PREFERRED if f in fams), None)
    if fam is None:
        fam = tkfont.nametofont("TkDefaultFont").actual("family")
    FONT = (fam, 10)
    FONT_SMALL = (fam, 9)
    FONT_BOLD = (fam, 10, "bold")
    FONT_HEAD = (fam, 9, "bold")
    FONT_TITLE = (fam, 13, "bold")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=fam, size=10)
        except tk.TclError:
            pass
    root.configure(bg=BG)
    root.option_add("*Menu.activeBackground", ACCENT)
    root.option_add("*Menu.activeForeground", "#ffffff")
    root.option_add("*Menu.relief", "flat")
    root.option_add("*Listbox.font", FONT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    s = ttk.Style(root)
    if "clam" in s.theme_names():
        s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, font=FONT, bordercolor=BORDER,
                lightcolor=BORDER, darkcolor=BORDER, troughcolor=HOVER, focuscolor=ACCENT,
                selectbackground=ACCENT, selectforeground="#ffffff", insertcolor=TEXT)
    for name, bg in (("TFrame", BG), ("Side.TFrame", SIDE), ("Card.TFrame", CARD),
                     ("Bar.TFrame", CARD)):
        s.configure(name, background=bg)
    for name, bg, fg, f in (("TLabel", BG, TEXT, FONT), ("Side.TLabel", SIDE, TEXT, FONT),
                            ("Card.TLabel", CARD, TEXT, FONT), ("Bar.TLabel", CARD, MUTED, FONT_SMALL),
                            ("Head.TLabel", SIDE, MUTED, FONT_HEAD),
                            ("CardHead.TLabel", CARD, MUTED, FONT_HEAD),
                            ("Muted.TLabel", SIDE, MUTED, FONT_SMALL),
                            ("CardMuted.TLabel", CARD, MUTED, FONT_SMALL),
                            ("Title.TLabel", CARD, TEXT, FONT_TITLE),
                            ("Status.TLabel", BG, MUTED, FONT_SMALL),
                            ("Good.TLabel", SIDE, GOOD, FONT_BOLD), ("Bad.TLabel", SIDE, BAD, FONT_BOLD),
                            ("CardBad.TLabel", CARD, BAD, FONT_SMALL),
                            ("GoodPill.TLabel", GOOD_SOFT, GOOD, FONT_SMALL),
                            ("BadPill.TLabel", BAD_SOFT, BAD, FONT_SMALL)):
        s.configure(name, background=bg, foreground=fg, font=f)
    s.configure("GoodPill.TLabel", padding=(10, 2))
    s.configure("BadPill.TLabel", padding=(10, 2))

    s.configure("TButton", background=CARD, foreground=TEXT, padding=(10, 5), relief="flat", width=-4,
                borderwidth=1, bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD, focusthickness=0)
    s.map("TButton", background=[("disabled", SIDE), ("pressed", ACCENT_SOFT), ("active", HOVER)],
          foreground=[("disabled", "#adb5bd")], bordercolor=[("focus", ACCENT)])
    s.configure("Small.TButton", padding=(6, 3), font=FONT_SMALL)
    s.configure("Flat.TButton", padding=(8, 5), bordercolor=CARD)
    s.configure("Tiny.TButton", padding=(2, 3), font=FONT_SMALL)
    s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT,
                lightcolor=ACCENT, darkcolor=ACCENT, font=FONT_BOLD, padding=(14, 6))
    s.map("Accent.TButton", background=[("disabled", "#a5b4fc"), ("pressed", ACCENT_DARK),
                                        ("active", ACCENT_DARK)],
          foreground=[("disabled", "#ffffff")], bordercolor=[("active", ACCENT_DARK)])

    for name, bg in (("Tool.TRadiobutton", CARD), ("Seg.TRadiobutton", SIDE)):
        s.layout(name, s.layout("Toolbutton"))
        s.configure(name, background=bg, foreground=TEXT, padding=(10, 5), anchor="center",
                    relief="flat", borderwidth=0)
        s.map(name, background=[("selected", ACCENT_SOFT), ("active", HOVER)],
              foreground=[("selected", ACCENT)])
    s.configure("Seg.TRadiobutton", borderwidth=1, bordercolor=BORDER)
    s.layout("Chip.TCheckbutton", s.layout("Toolbutton"))
    s.configure("Chip.TCheckbutton", background=CARD, foreground=MUTED, padding=(8, 4), anchor="center",
                borderwidth=1, relief="flat", bordercolor=BORDER)
    s.map("Chip.TCheckbutton", background=[("selected", ACCENT_SOFT), ("active", HOVER)],
          foreground=[("selected", ACCENT)])

    s.configure("TCheckbutton", background=SIDE, foreground=TEXT, indicatorbackground=CARD,
                indicatorforeground=ACCENT)
    s.configure("Side.TCheckbutton", background=SIDE)
    s.configure("Card.TCheckbutton", background=CARD)
    s.map("TCheckbutton", background=[("active", SIDE)], indicatorbackground=[("selected", ACCENT)],
          indicatorforeground=[("selected", "#ffffff")])
    s.map("Card.TCheckbutton", background=[("active", CARD)])

    s.configure("TEntry", fieldbackground=CARD, padding=(6, 3), bordercolor=BORDER, lightcolor=CARD)
    s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
          fieldbackground=[("disabled", SIDE)])
    s.configure("TCombobox", fieldbackground=CARD, padding=(6, 3), arrowsize=12, background=CARD)
    s.map("TCombobox", bordercolor=[("focus", ACCENT)], fieldbackground=[("readonly", CARD),
                                                                         ("disabled", SIDE)],
          background=[("active", HOVER)])
    s.configure("TSpinbox", fieldbackground=CARD, padding=(6, 3), arrowsize=11)

    s.configure("TNotebook", background=SIDE, borderwidth=0, tabmargins=(8, 6, 8, 0))
    s.configure("TNotebook.Tab", background=SIDE, foreground=MUTED, padding=(12, 6), borderwidth=0,
                font=FONT_BOLD)
    s.map("TNotebook.Tab", background=[("selected", CARD), ("active", HOVER)],
          foreground=[("selected", ACCENT)], expand=[("selected", (0, 0, 0, 0))])
    s.configure("TSeparator", background=BORDER)
    s.configure("Horizontal.TScale", background=ACCENT, troughcolor=BORDER, sliderthickness=14,
                bordercolor=SIDE, lightcolor=ACCENT, darkcolor=ACCENT, gripcount=0)
    s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=HOVER, bordercolor=HOVER,
                lightcolor=ACCENT, darkcolor=ACCENT)
    s.configure("Vertical.TScrollbar", background=SIDE, troughcolor=SIDE, bordercolor=SIDE,
                arrowcolor=MUTED, lightcolor=SIDE, darkcolor=SIDE)
    return s


def card(parent, title: str | None = None, pad=10):
    """A white panel with an optional small heading. Returns the inner frame."""
    outer = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=pad)
    inner.pack(fill="both", expand=True)
    if title:
        ttk.Label(inner, text=title.upper(), style="CardHead.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
    return outer, inner
