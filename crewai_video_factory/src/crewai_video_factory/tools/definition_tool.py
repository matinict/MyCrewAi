"""
Topic Definition Tool
Saves the agent-generated topic definition to output/{filename}.txt (flat, alongside CSV).

Triggered by: "definition_enabled": true in data.json

The AGENT (deepseek/gpt-4o etc.) writes the actual definition content using its LLM.
This tool simply saves whatever the agent writes to the correct file path.

Future use: definition text → scrolling story-tell video clip
            Pipeline: intro_clip → definition_clip → bar_race → audio → final merge
"""

import os
import re
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field


class DefinitionToolInput(BaseModel):
    """Input schema for DefinitionTool."""
    topic: str = Field(..., description="Full topic name (e.g. 'LLM Tuning Methods')")
    filename: str = Field(..., description="Base filename slug (e.g. 'LLMTuningMethods')")
    output_dir: str = Field(..., description="Output subdirectory (e.g. 'output/LLMTuningMethods')")
    definition_text: str = Field(..., description=(
        "The full definition written by the agent using its LLM. Must cover: "
        "1) What is this topic? "
        "2) Why does it matter? "
        "3) Key terms explained simply. "
        "4) Timeline context (start to end years). "
        "5) What viewers will see in the race video."
    ))
    start: int = Field(default=2015, description="Start year of data")
    end: int = Field(default=2026, description="End year of data")
    definition_enabled: bool = Field(default=False, description="Whether to generate topic definition")
    channel: str = Field(default="PlayOwnAi", description="Channel name for branding")


class DefinitionTool(BaseTool):
    """
    Saves the agent-written topic definition to output/{filename}.txt (flat alongside CSV).

    The agent (deepseek/gpt-4o-mini/claude etc.) writes the definition content
    using its own LLM knowledge. This tool just saves the result.

    Future pipeline:
      intro_clip → definition_clip → bar_race_clip → audio → final_merge
    """
    name: str = "Definition Tool"
    description: str = (
        "Saves the agent-written topic definition to output/{filename}.txt alongside the CSV. "
        "Agent MUST write the full definition_text before calling this tool. "
        "Triggered by definition_enabled=true."
    )
    args_schema: Type[BaseModel] = DefinitionToolInput

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        definition_text: str,
        start: int = 2015,
        end: int = 2026,
        definition_enabled: bool = False,
        channel: str = "PlayOwnAi",
    ) -> str:

        if not definition_enabled:
            print(f"[Definition] 🔇 Skipped (definition_enabled=false)")
            return "🔇 Topic definition skipped (definition_enabled=false)"

        import time as _time
        t0 = _time.time()
        print(f"[Definition] ▶ Starting — topic='{topic}'")
        print(f"[Definition]   filename : {filename}")
        print(f"[Definition]   output   : output/{filename}.txt (flat alongside CSV)")
        print(f"[Definition]   period   : {start}–{end}  channel: @{channel}")

        if not definition_text or not definition_text.strip():
            print(f"[Definition] ❌ definition_text is empty — agent skipped STEP 1!")
            return (
                "❌ definition_text is empty.\n"
                "You must complete STEP 1 first: write the full definition text yourself,\n"
                "then call this tool again with definition_text=<your written text>.\n"
                "Do NOT call this tool with an empty definition_text."
            )

        print(f"[Definition] ✏️  Agent wrote {len(definition_text.split())} words / {len(definition_text)} chars")
        print(f"[Definition] 💾 Saving to file ...")

        # Sanitize filename slug
        filename_clean = ''.join(re.findall(r'\w+', filename)[:3])

        # Save flat alongside CSV: output/{filename}.txt
        parent_dir = os.path.dirname(os.path.abspath(output_dir))
        txt_path = os.path.join(parent_dir, f"{filename_clean}.txt")

        # Wrap with header/footer if agent didn't include them
        header = (
            f"{'━'*52}\n"
            f"📖 TOPIC: {topic}\n"
            f"Channel: @{channel}  |  Period: {start}–{end}\n"
            f"{'━'*52}\n\n"
        )
        footer = (
            f"\n\n{'━'*52}\n"
            f"Subscribe to @{channel} for more data-driven insights.\n"
            f"{'━'*52}\n"
        )

        full_text = definition_text.strip()
        if "━━━" not in full_text:
            full_text = header + full_text + footer

        try:
            os.makedirs(parent_dir, exist_ok=True)
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(full_text)

            size    = os.path.getsize(txt_path)
            words   = len(full_text.split())
            chars   = len(full_text)
            elapsed = _time.time() - t0

            print(f"[Definition] ✅ Saved: {txt_path}")
            print(f"[Definition]   {words} words | {chars} chars | {size} bytes | {elapsed:.1f}s")
            print(f"[Definition] Preview:")
            for line in full_text[:500].split("\n"):
                print(f"[Definition]   {line}")
            return (
                f"✅ Topic definition saved: {txt_path}\n"
                f"   {words} words | {chars} chars | {elapsed:.1f}s\n\n"
                f"Preview:\n{full_text[:400]}..."
            )
        except Exception as e:
            print(f"[Definition] ❌ Save failed: {e}")
            return f"❌ Failed to save definition: {e}"
