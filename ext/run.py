# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2024-2025 Advanced Micro Devices, Inc. All rights reserved.

"""
Runs onnx test and mldebugger
"""

import argparse
import numpy as np
import onnxruntime
import os
import shutil
import subprocess
import sys
import threading

from pathlib import Path
from subprocess import PIPE

os.environ["XLNX_ENABLE_CACHE"] = "0"
os.environ["DEBUG_VAIML_PARTITION"] = "2"
os.environ["DEBUG_LOG_LEVEL"] = "info"

def setup_halt():
  content = (
    "[Debug]\n"
    "aie_halt=true\n"
    "[AIE_halt_settings]\n"
    "control_code=aieHalt1x4x4.elf\n"
    "[Runtime]\n"
    "cert_timeout_ms = 0x99999999\n"
  )
  with open("xrt.ini", "w", encoding="utf-8") as fd:
    fd.write(content)
  shutil.copy2("MLDebug/ext/initial_halt_elfs/telluride/aieHalt1x4x4.elf", ".")

class ProcessWithNotification:
  def __init__(self, args):
    self.continue_event = threading.Event()
    self.halfway_event = threading.Event()
    self.thread = None
    self.args = args
    self.cache_key = None

  def _process_function(self):
    model_file = Path(self.args.input_model)
    self.cache_key = model_file.stem
    provider_options_dict = {
      "config_file": "vitisai_config.json",
      "cache_dir": os.getcwd(),
      "cache_key": self.cache_key,
    }
    session = onnxruntime.InferenceSession(
      model_file,
      # providers=["CPUExecutionProvider"],
      providers=["VitisAIExecutionProvider"],
      provider_options=[provider_options_dict],
    )
    input_name = {
      inp.name: np.load(f"ifm_{count}.npy")
      for count, inp in enumerate(session.get_inputs())
    }
    outputs = [x.name for x in session.get_outputs()]
    ofm = None
    try:
      ofm = session.run(outputs, input_name)
    except:
      # print(f"ERROR: onnx_session failed run the inference with exception: {e}")
      print("Reached MLDebugger Halt with hang")
      self.halfway_event.set()
      print("Waiting for signal to continue...\n")
      self.continue_event.wait()
      return
    print("Reached MLDebugger Halt without hang")
    self.halfway_event.set()
    print("Waiting for signal to continue...\n")
    self.continue_event.wait()
    count = 0
    for i, j in zip(outputs, ofm):
      np.save(f"ofm_{count}.npy", j)
      print(f"INFO: Saved OFM {i} size = {j.shape}")
      count = count + 1
    del session
    for i in range(count):
      ofm = np.load(f"ofm_{i}.npy")
      ofm_ref = np.load(f"ofm_{i}_ref.npy")
      max_diff = np.max(np.abs(ofm - ofm_ref))
      print(f"Max absolute difference for ofm_{i}.npy: {max_diff}")

  def start(self):
    """Start the processing in a separate thread."""
    self.thread = threading.Thread(target=self._process_function)
    self.thread.start()
    return self

  def wait_for_halfway(self, timeout=None):
    """Wait for the thread to reach the halfway point."""
    return self.halfway_event.wait(timeout)

  def continue_processing(self):
    """Signal the thread to continue processing."""
    self.continue_event.set()

  def join(self, timeout=None):
    """Wait for the thread to complete."""
    if self.thread:
      self.thread.join(timeout)

def check_stdout(stdout):
  """
  Check if the output of the command contains valid results.
  """
  check_strings = [
    "Finished Execution",
    "Reached Final iteration",
    "now exiting InteractiveConsole...",
  ]
  return any(check_str in stdout for check_str in check_strings)

def run_mldebugger(processor):
  os.chdir("MLDebug")
  cmdseq = None
  CMD = "python mldebug.py -v ../ -f l2_ifm_dump"
  user_input = b""
  if cmdseq:
    # Simulate user input for interactive mode
    user_input = cmdseq.encode("utf-8")
  with subprocess.Popen(CMD, shell=True, stdout=PIPE, stderr=PIPE, stdin=PIPE) as process:
    stdout, stderr = process.communicate(input=user_input)
  stdout_txt = stdout.decode(encoding="utf-8")
  stderr_txt = stderr.decode(encoding="utf-8")
  with open("../test.log", "w", encoding="utf-8") as fd:
    fd.write(stdout_txt)
    fd.write(stderr_txt)
  if process.returncode != 0 or not check_stdout(stdout_txt + stderr_txt):
    print(stdout_txt, stderr_txt)
    print(f"FAILED: {CMD} RET_CODE: {process.returncode}")
    return 1
  return 0

def main():
  parser = argparse.ArgumentParser(
    description="onnxruntime compile and run using python API"
  )
  parser.add_argument(
    "--input_model",
    "-i",
    help="Path to the model (.onnx for ONNX) for onnxruntime compile",
  )
  args = parser.parse_args()
  setup_halt()
  status = 0

  processor = ProcessWithNotification(args)
  processor.start()
  print("Main thread: Wait for halfway")
  processor.wait_for_halfway()
  print("Main thread: Received halt notification! Running MLDebugger")
  status = run_mldebugger(processor)
  print("Finished MLDebugger")
  processor.continue_processing()
  processor.join()
  if status != 0:
    print("FAILED: MLDebugger")
  else:
    print("SUCCESS")
  sys.exit(status)

if __name__ == "__main__":
  main()
