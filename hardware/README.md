# Printed parts

Ready-to-print STL files from the thesis project. The plates are already oriented for
printing, with the contact face on the bed. Slicers drop the moulds onto the bed
automatically.

| Folder | What's in it |
|---|---|
| `matrices/` | The original 2x2, 3x3 and 4x4 matrices |
| `finger/` | The finger actuator (1×3) |
| `molds/` | The moulds the membranes were cast in |
| `assembly/` | The bench: the solenoid manifold and the valve adapters |

## `matrices/`: the original row/column matrices

The matrices designed for the thesis: three plates per matrix, with two silicone
membranes between them. The program in this repository generates the same kind of
plates for any layout.

| Matrix | Plate size (mm) | Bottom / middle / top (mm) | M3 bolts | Lines |
|---|---|---|---|---|
| 2x2 | 37.6 × 36.4 | 7.7 / 8.9 / 3.0 | 9 | 2 rows + 2 columns |
| 3x3 | 51.6 × 49.8 | 8.3 / 8.0 / 3.0 | 16 | 3 rows + 3 columns |
| 4x4 | 65.6 × 63.2 | 8.3 / 8.0 / 3.0 | 25 | 4 rows + 4 columns |

Files: `matrix_<size>_top_plate.stl`, `matrix_<size>_middle_plate.stl`,
`matrix_<size>_bottom_plate.stl`.

- **Status:** the 2x2 worked on the rig. The 3x3 and 4x4 come from the same
  generator; the 4x4 was printed but not tested.
- **Assembly, from the bottom up:**
  1. the bottom plate, with M3 nuts in the hex pockets;
  2. membrane 1;
  3. the middle plate;
  4. membrane 2;
  5. the top plate.

  The chamfered corner goes on the same corner of every plate.
- **Membranes:** cut both to the plate size, with holes at the bolts.
- **Lines:** each row and column line has a needle inlet on a side face of the
  bottom plate. The supply goes into the middle plate.
- **Logic:** a dome rises while both of its lines are vented.

## `finger/`: the finger actuator

The 1×3 matrix worn on a finger, one actuator per phalanx, used for the skin test.
- **Lines:** one row line (`ROW`) is a shared enable; three column lines (`COL1`–`COL3`)
  pick the phalanx.
- **Plates:** 74.8 × 35.7 mm, held by 12 M3 × 22 bolts.
- **Top saddle:** the top plate is a saddle with a groove for the finger.
- **Strap loops:** the bottom plate has 2 × 3 loops on its back face for a 12.6 mm
  velcro strap.

| File | What it is |
|---|---|
| `finger_top_saddle.stl` | Top plate: saddle with the finger groove and the three windows, 4.0 mm |
| `finger_middle_plate.stl` | Middle plate: valves and supply, 8.0 mm |
| `finger_bottom_plate.stl` | Bottom plate: control chambers and lines, 8.3 mm plus 4.6 mm strap loops |
| `finger_membrane_template.svg` | 1:1 template to cut the two membranes (outline and bolt holes) |

The bolt tips stand about 1 mm proud of the back face; a shorter bolt or a thin
washer fixes that.

## `molds/`: membrane moulds

Trays to cast the silicone membranes in: a 2 mm floor, 2.5 mm walls, and a pocket
exactly as deep as the membrane. Pour, scrape level with the rim, cure, then cut the
bolt holes.
- **Silicone:** Elastómero HC 25, A:B 1:1. De-gas in vacuum cycles of about 1 minute
  until no more bubbles surface, then cure for 1 to 2 days.
- **Thicknesses:** the 1 mm membranes were used under the actuators; the 2 mm ones
  in the valves.

| Files | Membrane | For |
|---|---|---|
| `membrane_mold_30x30_{1,2}mm_transistor.stl` | 30 × 30 mm | The first single transistor |
| `membrane_mold_38x38_{1,2}mm_matrix_2x2.stl` | 38 × 38 mm | The 2x2 matrix |
| `membrane_mold_52x52_{1,2}mm_matrix_3x3.stl` | 52 × 52 mm | The 3x3 matrix |
| `membrane_mold_66x66_{1,2}mm_matrix_4x4.stl` | 66 × 66 mm | The 4x4 matrix |
| `membrane_mold_43x78_{1.5,2}mm_finger.stl` | 43.5 × 74 mm pocket | The finger actuator; cut to the plate outline with the template |

The program in this repository writes a membrane template for any layout (Export
STL → `<name>_membrane.svg`). A mould only has to be a tray at least that big.

## `assembly/`: the pneumatic bench

The parts that connect the solenoid valves to the matrices.

| File | What it is |
|---|---|
| `manifold_4_valves_M5_inlet.stl` | Supply manifold for 4 solenoid valves: a block 80 × 25 × 15 mm with one female M5 inlet and 4 valve ports (ø3.7, 20 mm apart). It has three mounting ears with ø3.4 holes on a 20 mm grid, for a perforated plate. |
| `adapter_valve_to_M5.stl` | Adapter from a valve outlet barb to a female M5 fitting. It has a ø4.3 socket for the barb and a hex body. |
| `adapter_valve_to_M6.stl` | The same adapter for female M6 fittings. |

- **Printing:**
  - The manifold was printed in PETG at 100 % infill and 100 % flow, and it holds
    pressure.
  - Print the adapters solid too.
  - Thread clearances are sized for FDM (manifold M5: 0.6 mm; adapters: 0.5 mm). On
    a resin printer they will be loose.
- **What was tested:**
  - The M5 adapter was tested on the bench.
  - The M6 adapter has the same clearances but was not tested.
  - The manifold's valve ports were opened up from ø3.4 to ø3.7, because at
    100 % flow PETG prints them undersized; the ø3.7 fit was not tested.
