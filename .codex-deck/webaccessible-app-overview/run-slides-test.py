"""Run the bundled overflow test while tolerating the renderer's spurious exit code.

The bundled artifact renderer writes valid PNGs and a JSON manifest, but this
runtime currently exits with status 1 after successful rendering.  This wrapper
keeps the official slides_test logic and accepts the render only when every
manifest path exists.
"""

import json
import os
import subprocess
import sys
import tempfile


TOOLS_DIR = r"C:\Users\might\.codex\plugins\cache\openai-primary-runtime\presentations\26.805.11740\skills\presentations\container_tools"
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import render_slides  # type: ignore  # noqa: E402
import slides_test  # type: ignore  # noqa: E402


def forgiving_render(input_path: str, out_dir: str, dpi: int):
    scale = max(dpi / 96.0, 0.01)
    with tempfile.TemporaryDirectory(prefix="artifact_tool_workspace_") as workspace:
        proc = subprocess.run(
            [
                render_slides.node_binary(),
                os.path.join(TOOLS_DIR, "render_presentation.mjs"),
                "--input",
                input_path,
                "--output_dir",
                out_dir,
                "--scale",
                f"{scale:.6f}",
                "--workspace",
                workspace,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=render_slides.runtime_env(),
        )

    combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
    start = combined.find("{")
    end = combined.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"Renderer produced no JSON manifest.\n{combined}")
    payload = json.loads(combined[start : end + 1])
    paths = payload.get("paths", [])
    if not paths or not all(os.path.exists(path) for path in paths):
        raise RuntimeError(f"Renderer manifest is incomplete.\n{combined}")
    return paths


render_slides._render_presentation_with_artifact_tool = forgiving_render
slides_test.render_slides._render_presentation_with_artifact_tool = forgiving_render

if __name__ == "__main__":
    slides_test.main()
