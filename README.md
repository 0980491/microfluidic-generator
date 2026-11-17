# mfcad Layout

Lay out matrices of 3D-printed membrane-valve actuators, then generate the
plates to print.

Every actuator has the construction of the row/column matrices that worked on
the rig:

- three rigid plates (top, middle, bottom) with two membranes between them;
- each actuator is a dome window in the top plate over two normally-open valves
  in series.

You decide where the actuators and bolts go, how far apart things are, which
line drives each valve and which face every inlet comes out on. The program
checks every rule as you work. **Generate 3D** routes the channels through the
plates, and shows them in a 3D view where you can see the logic inside.
**Export STL** writes the three plates, ready to slice.

## Use it online — nothing to install

**<https://0980491.github.io/microfluidic-generator/>**

The website is the whole program:
- the editor and the rules;
- the lines and the inlet faces;
- Generate 3D, with an X-ray view of the real channels;
- Export STL, which downloads a zip with the three plates, the membrane
  template, the channel drawing and the README.

Everything runs in your browser and nothing is uploaded. It reads and writes the
same `.mfl` files as the desktop program, and your last layout is kept in the
browser. It works best on a computer; on a phone it opens, but there's little
room to edit.

The rest of this page is for the desktop program.

## Install

There are two ways:
- **Ready-made program:** nothing else to install. Available once a release has
  been built.
- **With Python:** works today, on any system.

### Windows

**Option A: ready-made program**

1. Open the [**Releases**](https://github.com/0980491/microfluidic-generator/releases) page and download `mfcad-layout.exe`.
2. Double-click it. Windows SmartScreen may warn that the app is unknown,
   because it is not signed. Click **More info → Run anyway**.

**Option B: with Python**

1. Install Python 3.9 or newer from <https://www.python.org/downloads/>. In the
   installer:
   - tick **"Add python.exe to PATH"**;
   - leave **"tcl/tk and IDLE"** ticked (the window needs it).
2. Open **PowerShell** or **Command Prompt** and run:

   ```bat
   py -m pip install --user "https://github.com/0980491/microfluidic-generator/archive/refs/heads/main.zip"
   ```

   It downloads the program and its two packages (numpy and manifold3d).
3. Start it:

   ```bat
   py -m mfcad_layout
   ```

   To open a layout directly: `py -m mfcad_layout C:\path\to\layout.mfl`
4. To update later, run the same `pip install` line again, adding
   `--upgrade --force-reinstall`.

### Linux

**Option A: ready-made program**

1. Download `mfcad-layout-linux` from the [**Releases**](https://github.com/0980491/microfluidic-generator/releases) page.
2. Make it executable and run it:

   ```bash
   chmod +x mfcad-layout-linux
   ./mfcad-layout-linux
   ```

**Option B: with Python (pipx)**

1. Install Python's Tk and pipx:

   | Distribution | Command |
   |---|---|
   | Debian / Ubuntu / Mint | `sudo apt install python3-tk pipx` |
   | Fedora | `sudo dnf install python3-tkinter pipx` |
   | Arch / Manjaro | `sudo pacman -S tk python-pipx` |

2. Install the program, then open a new terminal so `mfcad-layout` is on the PATH:

   ```bash
   pipx ensurepath
   pipx install "https://github.com/0980491/microfluidic-generator/archive/refs/heads/main.zip"
   ```

3. Start it:

   ```bash
   mfcad-layout
   ```

   To open a layout directly: `mfcad-layout layout.mfl`
4. To update later: `pipx install --force` with the same link.

### macOS

Download `mfcad-layout-macos.zip` from [**Releases**](https://github.com/0980491/microfluidic-generator/releases) and unzip it. The first time,
right-click the app and choose **Open**, because it is unsigned. Or use Python,
with the same steps as Linux: `brew install python-tk pipx`, then `pipx install …`.

### Try it

Open [`examples/3x3.mfl`](examples/3x3.mfl) from this repository (or press **M** to place a matrix),
then press **Generate 3D**.

## Use

The view is the plate seen from the top (the skin side), in millimetres. The
origin is at the bottom-left corner.

| Tool | Key | What it does |
|---|---|---|
| Select | V | Click to select, Shift+click to add, drag to move, drag on empty space to box-select |
| Actuator | A | Click to place one. The point is the dome centre. Press R before clicking to rotate it. |
| Bolt | B | Click to place an M3 through-bolt. Bolts can go between actuators or outside them. |
| Matrix | M | Places a rows × columns block, optionally with bolts at every footprint corner, like the printed matrices |

Other actions:

- **Corner bolts:** adds bolts at the footprint corners of the selected actuators,
  or of all actuators if none are selected. It skips any bolt that would break a
  rule.
- **Fit plate:** shrinks or grows the plate around everything on it, keeping the
  edge margins.
- **Rules…:** sets every distance, in mm. The proven values are shown next to
  each one. Going below a proven value asks for confirmation, because it is
  untested.

A ghost shows where the next piece will go. It is green when allowed and red when
not, and the status bar says why. Anything already on the plate that breaks a
rule is drawn red and listed under **Checks**. That happens after you change the
rules, for example. Click a problem in the list to select the parts involved.

Placing, moving or rotating something into a broken rule is refused, and it
snaps back. Undo and redo are Ctrl+Z and Ctrl+Y. Actuators snap by their
footprint corner, so corner bolts also land on the grid.

### Lines: the logic

Each actuator is supply → valve 1 → valve 2 → dome. Pressurising a line closes
every valve it feeds, so with the supply on, **a dome rises only while both of
its lines are vented**. That is how a keyboard matrix picks one key with a row
and a column.

- **Automatic names:** domes at the same height share a row line, numbered R1,
  R2… from the top. Domes in the same vertical share a column line, C1, C2… from
  the left. The row line drives the supply-side valve, and the column line the
  dome-side valve.
- **Your own wiring:** select an actuator and type another name under **Row
  line** or **Column line**. Actuators with the same name share that line and its
  inlet. Type `auto` to go back.
- **Lines tab:** every line, how many valves it drives, and the **face** its
  inlet comes out on:
  - `left`, `right`, `front` (y = 0) or `back`;
  - `auto`, which takes the shortest way out.

  The supply has its own face setting.
- The chambers on the plate are drawn in the colour of their line.

### Generate 3D and export

**Generate 3D** (Ctrl+G) routes every line through the bottom plate and the
supply through the middle plate, then opens the 3D view:

- **X-ray** draws the plates as glass. Every channel, chamber, seat and window is
  drawn inside, one colour per line. Click a line in the list to pick it out.
- **Solid** shows the plates as they come off the printer.
- **Explode** pulls the plates apart. Drag to orbit, right/middle drag to pan,
  and use the wheel to zoom.

The routes also appear on the 2D plate, until you change the layout.

**Export STL** (Ctrl+E, or the button in the 3D view) writes, into a folder you
pick:

| File | What |
|---|---|
| `<name>_bottom.stl`, `_middle.stl`, `_top.stl` | The plates, each already contact face down for printing |
| `<name>_membrane.svg` | 1:1 template to cut both membranes (outline and bolt holes) |
| `<name>_channels.svg` | 1:1 drawing of every routed channel, one colour per line |
| `<name>_README.txt` | Thicknesses, which inlet is which (face and position in mm), which valves each line drives, assembly order |

Before writing, the export checks every plate:
- Every line, the supply and each cell's own channels must be separate sealed
  cavities. If two of them touch, it says so, and it says not to print.
- It reports the thinnest wall between any two.

Without the window:

```bash
mfcad-layout --export layout.mfl [folder]
```

### How the channels are routed

The construction is the printed matrix cell, feature for feature: the same seats,
chambers, needle ports, nut pockets and corner key. The numbers are in
`src/mfcad_layout/stack.py`. They come from the parent project,
mfcad (`proven_geom`), and a test
checks them against it when mfcad sits next to this folder.

- **Bottom plate:**
  - Each line drops into the centre of each chamber it drives. The drops are
    joined into a tree, which ends at a needle inlet on a side face.
  - Lines run on levels below the chambers. Level 0 passes under other
    chambers with a 1 mm floor; level 1 passes under level 0.
  - Two lines cross by taking different levels, as the rows and columns of the
    3x3 do. The plate gets thicker only when a second or third level is needed.
- **Middle plate:** the supply runs on its own level above the valve channels.
  It drops into every actuator's first seat and keeps clear of every dome
  riser.
- **Walls:**
  - 1.2 mm between channels of different lines, and between a channel and a
    bolt hole.
  - 1.0 mm vertically between levels.
  - The funnel mouths of the needle ports keep their extra width.
  - Deep levels go round the nut pockets.

If a line can't be routed, the message names it. Things that help:
- more room between actuators (**Rules → Extra gap**);
- moving a bolt that is in the way;
- giving that line another face, or `auto`.

## The rules (defaults are the printed 2x2 / 3x3)

| Rule | Default | Meaning |
|---|---|---|
| Actuator footprint X × Y | 14 × 11.9 | The area one actuator owns, which is the matrix pitch. Footprints may touch, not overlap. |
| Extra gap between actuators | 0 | Added between footprints |
| Actuator to plate edge | 4.8 | From the footprint |
| Dome window diameter | 7 | |
| Bolt hole / nut pocket | 3.8 / 5.9 AF | M3 |
| Bolt to plate edge | 4.8 | Centre to edge |
| Bolt to bolt | 8.0 | Two nut pockets plus a wall |
| Bolt hole to dome window | 2.0 | Clamped membrane |
| Bolt hole to chamber / seat | 0.7 | What the printed matrices have |
| Needle bore, line inlets | 7.0 | How far the needle goes in before it lands on the stop |
| Needle bore, supply inlet | 8.0 | The same, for the supply |

The actuator's own construction is fixed:

- valve columns 6 mm apart, seats 3.2 mm apart, ø2.4 relief pockets;
- 3.8 × 7 mm control chambers;
- footprint centre 0.7 mm off the dome.

## File format

`.mfl` is plain JSON:

```json
{
  "format": "mfcad-layout", "version": 1, "units": "mm",
  "plate": {"width": 51.6, "length": 45.3},
  "rules": {"pitch_x": 14.0, "pitch_y": 11.9, "...": "..."},
  "actuators": [{"name": "A1", "x": 11.8, "y": 10.05, "rotation": 0},
                {"name": "A2", "x": 25.8, "y": 10.05, "rotation": 0, "row_line": "X"}],
  "bolts": [{"name": "B1", "x": 4.8, "y": 4.8}],
  "lines": {"X": {"face": "right"}, "S": {"face": "front"}}
}
```

- **Actuator position:** `x, y` is the dome centre.
- **Rotation:** 0/90/180/270, counter-clockwise. With rotation 0 the valve row
  runs along x, and the link row is +y of the dome.
- **Line names:** `row_line` and `col_line` are written only when set by hand.
- **Inlet faces:** `lines` holds only the faces that are not `auto`. `S` is the
  supply.

## Development

```bash
git clone https://github.com/0980491/microfluidic-generator.git
cd microfluidic-generator
pip install -e . pytest
python -m pytest -q tests
python -m mfcad_layout examples/3x3.mfl
```

### The website

The website lives in [`docs/`](docs/): plain HTML and JavaScript modules, with
no build step. It loads [three.js](https://threejs.org) and
[manifold](https://github.com/elalish/manifold) (the same geometry engine as the
desktop program) from jsDelivr. GitHub Pages serves it from `main` / `docs`.

`docs/js/route.js` and `docs/js/geometry.js` are line-by-line ports of
`route.py` and `build3d.py`. To check that the two still give the same channels
and plates:

```bash
cd tools && npm install && npm run check
```

To try the website locally: `python -m http.server -d docs`, then open
<http://localhost:8000>.

To build a standalone program for the system you are on:

```bash
pip install . pyinstaller
pyinstaller --onefile --windowed --name mfcad-layout --hidden-import manifold3d --hidden-import numpy packaging/launcher.py
```

The GitHub workflow `.github/workflows/build.yml` does that for Windows,
macOS and Linux. Run it by hand (Actions → mfcad Layout builds → Run workflow), or
push a tag `vX.Y.Z` to also publish the programs as a release.
