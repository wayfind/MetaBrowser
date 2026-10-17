"""MetaBrowser: an agent-grade browser runtime on ungoogled-chromium.

Layers (see docs/ARCHITECTURE.md):
  L0 engine      ungoogled-chromium (open Chromium, humanized input)
  L1 primitives  tabs / navigate / snapshot / click / type ...
  L2 semantic    read / extract_table / fill_form / collect_pages / net capture ...
  L3 site packs  site.<pack>.<capability> recipes compiled from site knowledge
  L4 delegation  agent.run_task (metacodes session)
"""

from .tools.base import Risk, ToolContext, ToolError, ToolResult, ToolSpec, ToolRegistry

__version__ = "0.1.0"

__all__ = ["Risk", "ToolContext", "ToolError", "ToolResult", "ToolSpec", "ToolRegistry", "__version__"]
