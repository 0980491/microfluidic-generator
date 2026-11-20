# Printed parts

Ready-to-print STL files from the thesis project. Every file is already oriented for
printing: the contact face is on the bed.

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
