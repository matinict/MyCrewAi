"""
Debate Definition Tool
Saves agent-generated debate arguments to 3 separate files:
  - output/{filename}/propose.md  (arguments FOR the motion)
  - output/{filename}/oppose.md   (arguments AGAINST the motion)
  - output/{filename}/decide.md   (moderator conclusion)

Triggered by: "debate_definition_enabled": true in data.json

The AGENT (deepseek/gpt-4o etc.) writes the actual debate content using its LLM.
This tool simply saves whatever the agent writes to the correct file paths.

Future use: These 3 files → debate_video_tool.py → debate videos with TTS audio
            Pipeline: debate_video → add_audio → merge → upload
"""

import os
import re
import time
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field


class DebateDefinitionToolInput(BaseModel):
    """Input schema for DebateDefinitionTool."""
    topic: str = Field(..., description=(
        "Full debate topic/motion (can be long sentence). "
        "Examples: 'AI Will Replace 80% of Jobs', "
        "'Climate Change Is Primarily Human-Caused', "
        "'Universal Basic Income Is Necessary'"
    ))
    filename: str = Field(..., description=(
        "Base filename slug generated from topic (e.g. 'AIWillReplace', 'ClimateChange'). "
        "Topic slug from first 3-4 words, auto-generated or provided."
    ))
    output_dir: str = Field(..., description=(
        "Output subdirectory for debate files (e.g. 'output/AIWillReplace'). "
        "All 3 debate files saved inside this directory."
    ))
    propose_text: str = Field(..., description=(
        "Arguments supporting the motion (FOR). "
        "Must be well-written, comprehensive arguments with reasoning. "
        "2-3 paragraphs or bullet points."
    ))
    oppose_text: str = Field(..., description=(
        "Arguments against the motion (AGAINST). "
        "Must be well-written counter-arguments with reasoning. "
        "2-3 paragraphs or bullet points."
    ))
    decide_text: str = Field(..., description=(
        "Moderator's conclusion/verdict. "
        "Balanced analysis of both sides with final judgment. "
        "2-3 paragraphs summarizing key points and conclusion."
    ))
    debate_definition_enabled: bool = Field(default=False, description="Whether to save debate definitions")
    channel: str = Field(default="PlayOwnAi", description="Channel name for branding")
    debate_max_chars: int = Field(default=2000, description="Hard cap on each debate argument in characters")


class DebateDefinitionTool(BaseTool):
    """
    Saves agent-written debate arguments to 3 separate files.

    The agent (deepseek/gpt-4o/claude etc.) writes the debate content
    using its own LLM knowledge. This tool saves the 3 argument texts:
      1. propose.md  → Arguments FOR the motion
      2. oppose.md   → Arguments AGAINST the motion
      3. decide.md   → Moderator conclusion/verdict

    Files saved in: output/{filename}/

    Future pipeline:
      propose.md + oppose.md + decide.md
            ↓
      debate_definition_tool (this)
            ↓
      debate_video_tool (generate video)
            ↓
      Add TTS audio
            ↓
      debate_video_[format]_with_audio.mp4
    """
    name: str = "Debate Definition Tool"
    description: str = (
        "Saves agent-written debate arguments to 3 files (propose.md, oppose.md, decide.md). "
        "Agent MUST write all three argument texts before calling this tool. "
        "Triggered by debate_definition_enabled=true."
    )
    args_schema: Type[BaseModel] = DebateDefinitionToolInput

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        propose_text: str,
        oppose_text: str,
        decide_text: str,
        debate_definition_enabled: bool = False,
        channel: str = "PlayOwnAi",
        debate_max_chars: int = 2000,
    ) -> str:

        if not debate_definition_enabled:
            print(f"[DebateDef] 🔇 Skipped (debate_definition_enabled=false)")
            return "🔇 Debate definition skipped (debate_definition_enabled=false)"

        t0 = time.time()
        print(f"\n[DebateDef] ▶ Starting — topic='{topic}'")
        print(f"[DebateDef]   filename : {filename}")
        print(f"[DebateDef]   output   : {output_dir}/")
        print(f"[DebateDef]   files    : propose.md | oppose.md | decide.md")
        print(f"[DebateDef]   channel  : @{channel}")

        # ── Validate all 3 debate texts are provided ─────────────────────
        all_texts = {
            'propose': propose_text,
            'oppose': oppose_text,
            'decide': decide_text
        }

        for name, text in all_texts.items():
            if not text or not text.strip():
                print(f"[DebateDef] ❌ {name}_text is empty — agent skipped!")
                return (
                    f"❌ {name}_text is empty.\n"
                    f"You must complete all 3 debate arguments FIRST:\n"
                    f"  1. propose_text (arguments FOR)\n"
                    f"  2. oppose_text (arguments AGAINST)\n"
                    f"  3. decide_text (moderator conclusion)\n"
                    f"Then call this tool with all three texts.\n"
                    f"Do NOT call with empty texts."
                )

        # ── Anchor save path to project root via __file__ ──────────────────
        _tool_dir     = os.path.dirname(os.path.abspath(__file__))
        _pkg_dir      = os.path.dirname(_tool_dir)
        _src_dir      = os.path.dirname(_pkg_dir)
        _project_root = os.path.dirname(_src_dir)

        # If output_dir is relative, anchor it to project root
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(_project_root, output_dir)

        os.makedirs(output_dir, exist_ok=True)

        print(f"[DebateDef]   base dir : {output_dir}")

        # ── Process and save all 3 debate files ──────────────────────────
        results = []
        errors = []

        for file_type, text in [('propose', propose_text), ('oppose', oppose_text), ('decide', decide_text)]:
            try:
                # Analyze input
                words = len(text.split())
                chars = len(text)
                print(f"\n[DebateDef] ✏️  {file_type.upper()}: {words} words / {chars} chars")

                # Clean the text
                cleaned_text = self._clean_debate_text(text, debate_max_chars)
                cleaned_words = len(cleaned_text.split())
                cleaned_chars = len(cleaned_text)
                print(f"[DebateDef]   Cleaned: {cleaned_words} words / {cleaned_chars} chars")

                # Save to file
                file_path = os.path.join(output_dir, f"{file_type}.md")
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(cleaned_text)

                file_size = os.path.getsize(file_path)
                print(f"[DebateDef] ✅ Saved: {file_path} ({file_size} bytes)")
                print(f"[DebateDef]   Preview:")
                for line in cleaned_text[:300].split("\n"):
                    print(f"[DebateDef]      {line}")

                results.append({
                    'file': file_type,
                    'path': file_path,
                    'words': cleaned_words,
                    'chars': cleaned_chars,
                    'bytes': file_size
                })

            except Exception as e:
                error_msg = f"❌ Failed to save {file_type}.md: {e}"
                print(f"[DebateDef] {error_msg}")
                errors.append(error_msg)

        elapsed = time.time() - t0

        if errors:
            print(f"\n[DebateDef] ⚠️  Completed with errors:")
            for error in errors:
                print(f"[DebateDef]   {error}")

        # ── Generate summary ─────────────────────────────────────────────
        print(f"\n[DebateDef] ✅ All done in {elapsed:.1f}s")
        print(f"[DebateDef] 📊 Summary:")

        summary = f"✅ Debate definitions saved in {elapsed:.1f}s\n\n"
        summary += f"Files created in: {output_dir}\n\n"

        for result in results:
            summary += (
                f"✓ {result['file'].upper():8} → {result['file']}.md\n"
                f"           {result['words']:4} words | {result['chars']:5} chars | {result['bytes']:7} bytes\n"
            )
            print(f"[DebateDef]   {result['file'].upper():8}: {result['words']} words | {result['chars']} chars")

        if errors:
            summary += f"\n⚠️  Errors:\n"
            for error in errors:
                summary += f"  {error}\n"
            return summary

        summary += f"\nTopic: {topic}\n"
        summary += f"All files ready for debate_video_tool →  debate video generation!\n"

        return summary

    def _clean_debate_text(self, text: str, max_chars: int = 2000) -> str:
        """
        Clean and normalize debate argument text.

        Removes:
        - Instruction leakage [like this]
        - Emoji icons
        - Numbered headers that got duplicated
        - Extra blank lines
        - Trims to max_chars
        """
        lines_out = []

        for ln in text.splitlines():
            s = ln.strip()

            # Skip blank lines and dividers
            if not s or s.startswith('━') or s.startswith('─') or s.startswith('==='):
                lines_out.append('')
                continue

            # Strip emoji icons at start of line
            s_clean = re.sub(
                r'^[\U00010000-\U0010ffff\U0001f300-\U0001f9ff'
                r'\u2600-\u27ff\u2000-\u206f]+\s*', '', s
            ).strip()

            # Skip instruction headers
            if re.match(r'^(TOPIC:|Motion:|DEBATE TOPIC:|For the motion:|Against the motion:)', s_clean, re.IGNORECASE):
                continue
            if re.match(r'^(Channel:|Subscribe to|Video|.*YouTube)', s, re.IGNORECASE):
                continue

            lines_out.append(s)

        # Join and clean up
        text = '\n'.join(lines_out).strip()

        # Remove [instruction leakage like this]
        text = re.sub(r'\[.*?\]', '', text)

        # Remove trailing instruction sections
        text = re.split(r'\n(ADDITIONAL NOTES|NOTES FOR VIDEO|PRODUCTION NOTES)', text, flags=re.IGNORECASE)[0]

        # Fix doubled numbered sections: "1: 1:" → "1:"
        text = re.sub(r'\b(\d+):\s+\1:\s*', r'\1: ', text)

        # Fix "Term N:" → "N:" if it appears
        text = re.sub(r'\bTerm\s+(\d+):\s*', r'\1: ', text)

        # Collapse multiple blank lines
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        # Hard cap at max_chars
        if len(text) > max_chars:
            cap = text[:max_chars]
            # Try to cut at sentence boundary
            cut = max(cap.rfind('.'), cap.rfind('\n'))
            if cut > int(max_chars * 0.67):  # Only cut if we're at least 67% through
                text = cap[:cut+1].strip()
            else:
                text = cap.strip()

        return text


# ── HELPER: Generate filename slug from long debate topic ────────────────
def generate_debate_filename_slug(topic: str) -> str:
    """
    Generate a filename slug from a potentially long debate topic.

    Examples:
      "AI Will Replace 80% of Jobs" → "AIWillReplace"
      "Climate Change Is Primarily Human-Caused" → "ClimateChangeIsPrimarily"
      "Universal Basic Income Is Necessary" → "UniversalBasicIncome"

    Strategy:
      1. Extract first 3-4 words that are meaningful (skip "is", "the", "and")
      2. CamelCase them
      3. Keep it under 40 chars
    """
    # Extract words, filter out small words
    words = [w for w in re.findall(r'\b\w+\b', topic)
             if len(w) > 2 and w.lower() not in ('the', 'and', 'or', 'is', 'are', 'will', 'have')]

    # Take first 3-4 meaningful words
    slug_words = words[:4]

    # CamelCase: capitalize first letter of each word
    slug = ''.join(w.capitalize() for w in slug_words)

    # Cap at 40 chars
    return slug[:40] if slug else "DebateTopic"
