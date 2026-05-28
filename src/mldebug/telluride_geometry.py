# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2024-2025 Advanced Micro Devices, Inc. All rights reserved.

"""
Telluride chip geometry profiles (t50 vs t10c).

Both use the same AIE2PS register maps but differ in array size and row layout.
"""

from mldebug.arch.loader import AIE_DEV_TEL, AIE_DEV_TEL_T10C
from mldebug.utils import is_aarch64

# t50: 4 AIE core rows x 36 cols, 2 memory-tile rows (default Telluride)
T50 = {
  "numcols": 36,
  "numrows": 7,
  "memtile_rows": 2,
  "mem_row_start": 1,
  "core_row_start": 3,
  "aie_tile_row_offset": 3,
  "aie_tile_num_rows": 4,
}

# t10c: 2 AIE core rows x 8 cols, 1 memory-tile row
T10C = {
  "numcols": 8,
  "numrows": 4,
  "memtile_rows": 1,
  "mem_row_start": 1,
  "core_row_start": 2,
  "aie_tile_row_offset": 2,
  "aie_tile_num_rows": 2,
}

_AIE_CONTROL_INT_DEFINES = (
  "XAIE_NUM_COLS",
  "XAIE_NUM_ROWS",
  "XAIE_MEM_TILE_ROW_START",
  "XAIE_MEM_TILE_NUM_ROWS",
  "XAIE_AIE_TILE_ROW_START",
  "XAIE_AIE_TILE_NUM_ROWS",
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
  Map array width and memory-tile row count to a Telluride device id.

  Matches core-dump header fields and aie_control.cpp defines.
  """
  if numcols == T10C["numcols"] and memtile_rows == T10C["memtile_rows"]:
    return AIE_DEV_TEL_T10C
  if numcols == T50["numcols"] and memtile_rows == T50["memtile_rows"]:
    return AIE_DEV_TEL
  return None


def device_from_numcols(numcols: int) -> str | None:
  """Map array column count to a Telluride device id."""
  if numcols == T10C["numcols"]:
    return AIE_DEV_TEL_T10C
  if numcols == T50["numcols"]:
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


def _aie_control_path(aie_dir: str | None) -> str | None:
  if not aie_dir:
    return None
  return f"{aie_dir}/ps/c_rts/aie_control.cpp"


def _read_aie_control_lines(ctrl_cpp: str | None) -> list[str] | None:
  if not ctrl_cpp:
    return None
  try:
    with open(ctrl_cpp, encoding="utf-8") as f:
      return f.read().split("\n")
  except OSError:
    return None


def _parse_aie_control_lines(lines: list[str]) -> dict:
  """
  Parse geometry fields from ``aie_control.cpp`` lines.

  Expected Telluride compiler output includes e.g.::

      #define HW_GEN                   XAIE_DEV_GEN_AIE2PS
      #define XAIE_NUM_ROWS            4
      #define XAIE_NUM_COLS            8
      #define XAIE_MEM_TILE_NUM_ROWS   1
      #define XAIE_AIE_TILE_ROW_START  2
      #define XAIE_AIE_TILE_NUM_ROWS   2
  """
  info: dict = {}

  for line in lines:
    if "#define HW_GEN" in line:
      info["hw_gen"] = line.split()[-1]
      break

  define_map = {
    "XAIE_NUM_COLS": "numcols",
    "AIE_NUM_COLS": "numcols",
    "NUM_COLS": "numcols",
    "AIE_ARRAY_COLS": "numcols",
    "XAIE_NUM_ROWS": "numrows",
    "XAIE_MEM_TILE_ROW_START": "mem_row_start",
    "XAIE_MEM_TILE_NUM_ROWS": "memtile_rows",
    "XAIE_AIE_TILE_ROW_START": "core_row_start",
    "XAIE_AIE_TILE_NUM_ROWS": "aie_tile_num_rows",
  }

  for src, dst in define_map.items():
    if dst in info:
      continue
    value = _parse_define(lines, src)
    if value is not None:
      info[dst] = value

  return info


def device_from_aie_control_info(info: dict) -> str | None:
  """Infer Telluride variant from parsed ``aie_control.cpp`` fields."""
  if "numcols" in info and "memtile_rows" in info:
    detected = device_from_geometry(info["numcols"], info["memtile_rows"])
    if detected:
      return detected

  if "numcols" in info:
    detected = device_from_numcols(info["numcols"])
    if detected:
      return detected

  return None


def read_aie_control(aie_dir: str | None) -> dict:
  """
  Parse ``aie_control.cpp`` for HW generation and array geometry.

  Returns a dict with optional keys ``hw_gen``, ``numcols``, ``numrows``,
  ``memtile_rows``, ``core_row_start``, and ``aie_tile_num_rows``.
  """
  lines = _read_aie_control_lines(_aie_control_path(aie_dir))
  if lines is None:
    return {}
  return _parse_aie_control_lines(lines)


def detect_from_aie_control(ctrl_cpp: str) -> str | None:
  """Infer Telluride variant from an ``aie_control.cpp`` file path."""
  lines = _read_aie_control_lines(ctrl_cpp)
  if lines is None:
    return None
  return device_from_aie_control_info(_parse_aie_control_lines(lines))


def refine_telluride_device(args) -> None:
  """
  Refine ``telluride`` (t50) vs ``telluride_t10c`` for VAIML, live HW, and standalone.

  On aarch64 hosts the Telluride family default is t50; this step reads
  ``aie_control.cpp`` (``XAIE_NUM_COLS``, ``XAIE_MEM_TILE_NUM_ROWS``, etc.)
  and selects the matching variant.

  No-op when the user explicitly chose ``telluride_t10c`` or a non-Telluride device.
  """
  if args.device and args.device not in (AIE_DEV_TEL, AIE_DEV_TEL_T10C):
    return
  if args.device == AIE_DEV_TEL_T10C:
    return

  aie_dir = getattr(args, "aie_dir", None)
  ctrl_info = read_aie_control(aie_dir)
  detected = device_from_aie_control_info(ctrl_info)

  if detected:
    if detected != args.device:
      prev = args.device or "telluride (default)"
      cols = ctrl_info.get("numcols", "?")
      mem = ctrl_info.get("memtile_rows", "?")
      print(
        f"[INFO] Telluride variant: {detected} (was {prev}; "
        f"from aie_control.cpp: {cols} cols, {mem} mem tile rows)."
      )
    args.device = detected
    return

  if is_aarch64() and args.device == AIE_DEV_TEL:
    if aie_dir:
      print(
        "[WARNING] Telluride variant not detected from aie_control.cpp "
        f"({_aie_control_path(aie_dir)}); assuming t50 ({AIE_DEV_TEL}). "
        f"Use -d {AIE_DEV_TEL_T10C} for t10c."
      )
    else:
      print(
        f"[WARNING] Telluride variant not detected (no work directory); "
        f"assuming t50 ({AIE_DEV_TEL}). Use -d {AIE_DEV_TEL_T10C} for t10c."
      )
