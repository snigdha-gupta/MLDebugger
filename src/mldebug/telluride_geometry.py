# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2024-2025 Advanced Micro Devices, Inc. All rights reserved.

"""
Telluride chip geometry profiles (t50 vs t10c).

Both use the same AIE2PS register maps but differ in array size and row layout.
"""

from mldebug.arch.loader import AIE_DEV_TEL, AIE_DEV_TEL_T10C

# t50: 4 AIE core rows x 36 cols, 2 memory-tile rows (default Telluride)
T50 = {
  "numcols": 36,
  "numrows": 7,
  "memtile_rows": 2,
  "mem_row_start": 1,
  "core_row_start": 3,
  "aie_tile_row_offset": 3,
}

# t10c: 2 AIE core rows x 8 cols, 1 memory-tile row
T10C = {
  "numcols": 8,
  "numrows": 4,
  "memtile_rows": 1,
  "mem_row_start": 1,
  "core_row_start": 2,
  "aie_tile_row_offset": 2,
}

_COL_DEFINE_NAMES = (
  "XAIE_NUM_COLS",
  "AIE_NUM_COLS",
  "NUM_COLS",
  "AIE_ARRAY_COLS",
)


def geometry_for_device(device: str) -> dict | None:
  """Return chip geometry dict for a Telluride device id, or None if not Telluride."""
  if device == AIE_DEV_TEL_T10C:
    return T10C
  if device == AIE_DEV_TEL:
    return T50
  return None


def device_from_geometry(numcols: int, memtile_rows: int) -> str | None:
  """
  Map core-dump header fields (or similar) to a device id.

  Returns None if the pair does not match a known Telluride profile.
  """
  if numcols == T10C["numcols"] and memtile_rows == T10C["memtile_rows"]:
    return AIE_DEV_TEL_T10C
  if numcols == T50["numcols"] and memtile_rows == T50["memtile_rows"]:
    return AIE_DEV_TEL
  return None


def _parse_define(lines: list[str], name: str) -> int | None:
  token = f"#define {name}"
  for line in lines:
    if token not in line:
      continue
    parts = line.split()
    if len(parts) < 3:
      continue
    raw = parts[-1].rstrip("uUlL")
    try:
      return int(raw, 0)
    except ValueError:
      continue
  return None


def detect_from_aie_control(ctrl_cpp: str) -> str | None:
  """
  Infer Telluride variant from aiecompiler ``aie_control.cpp``.

  Uses ``XAIE_NUM_COLS`` (and common aliases). Returns a device id or None.
  """
  if not ctrl_cpp:
    return None
  try:
    with open(ctrl_cpp, encoding="utf-8") as f:
      lines = f.read().split("\n")
  except OSError:
    return None

  numcols = None
  for name in _COL_DEFINE_NAMES:
    numcols = _parse_define(lines, name)
    if numcols is not None:
      break

  if numcols == T10C["numcols"]:
    return AIE_DEV_TEL_T10C
  if numcols == T50["numcols"]:
    return AIE_DEV_TEL
  return None


def refine_telluride_device(args) -> None:
  """
  If ``args.device`` is Telluride (or unset), refine t50 vs t10c from work dir.

  No-op when the user already chose ``telluride_t10c`` or a non-Telluride device.
  """
  if args.device and args.device not in (AIE_DEV_TEL, AIE_DEV_TEL_T10C):
    return
  if args.device == AIE_DEV_TEL_T10C:
    return

  aie_dir = getattr(args, "aie_dir", None)
  if not aie_dir:
    return

  detected = detect_from_aie_control(f"{aie_dir}/ps/c_rts/aie_control.cpp")
  if detected and detected != args.device:
    prev = args.device or "telluride (default)"
    args.device = detected
    print(f"[INFO] Telluride variant: {detected} (was {prev}; from aie_control.cpp).")
