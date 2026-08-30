"""Package init.

These four lines have to run before grpc, absl or ADK are imported anywhere, and
importing any `app.*` module runs this file first — which is the only hook early
enough. They exist because the agent logs are part of the demo: without them,
grpc's C++ fork notices and ADK's per-request INFO lines bury the
[CARTOGRAPHER] / [SOCRATIC] lines the judges are meant to read.
"""

import os
import warnings

os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GLOG_minloglevel", "2")

warnings.filterwarnings("ignore", category=UserWarning, module=r"google\.adk\..*")
