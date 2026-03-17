"""
debate_definition_tool.py
─────────────────────────────────────────────────────────────────────────────
Generates all six debate markdown files driven ENTIRELY by data.json values.

  Full-length  (debate_definition_enabled=true in debate_config):
    output/{filename}/propose.md
    output/{filename}/oppose.md
    output/{filename}/decide.md

  Mini / Shorts  (debate_mini_enabled=true in debate_config):
    output/{filename}/propose-m.md
    output/{filename}/oppose-m.md
    output/{filename}/decide-m.md

Fixes applied (v3):
  1. (None–None) header bug — year range omitted when start/end are None/null.
  2. Mini truncation bug — _compress_to_mini is ONLY used as a hard-cap safety
     net after LLM generation, never as a creative compressor. The LLM prompt
     itself enforces the word/char target so output arrives already short.
  3. Mini header format — full readable headers (PROPOSITION/OPPOSITION/VERDICT)
     are preserved; abbreviations (Prop:/Opp:) are NOT applied to mini files.

Every value — topic, start, end, channel, LLM, char caps, flags — comes from
main.py which reads data.json. Nothing is hard-coded in this file.
"""

from __future__ import annotations

import os
import re
import textwrap
from typing import Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

try:
    import anthropic as _anthropic_sdk
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


# ─────────────────────────────────────────────────────────────────────────────
# Input schema — 1-to-1 with flat inputs dict from main.py / data.json
# ─────────────────────────────────────────────────────────────────────────────

class DebateDefinitionInput(BaseModel):
    # top-level data.json fields
    topic:      str            = Field(...,         description="From data.json → topic.")
    filename:   str            = Field(...,         description="Slug: first 3 words of topic joined.")
    output_dir: str            = Field(...,         description="e.g. 'output/IsAI'.")
    start:      Optional[int]  = Field(default=None, description="From data.json → start (may be null).")
    end:        Optional[int]  = Field(default=None, description="From data.json → end   (may be null).")
    channel:    str            = Field(default="PlayOwnAi", description="From data.json → channel.")

    # debate_config flags (hoisted to flat inputs by main.py)
    debate_definition_enabled: bool = Field(default=False)
    debate_mini_enabled:        bool = Field(default=False)
    debate_max_chars:           int  = Field(default=10_000)
    debate_mini_max_chars:      int  = Field(default=1_200)

    # LLM — from data.json → debate_config.llm_debate
    llm_debate: str = Field(
        default="claude-sonnet-4-20250514",
        description="Any LiteLLM-compatible model string from data.json → debate_config.llm_debate.",
    )
    max_tokens: int = Field(default=2048)

    # misc
    overwrite:     bool = Field(default=False)
    extra_context: str  = Field(default="")


# ─────────────────────────────────────────────────────────────────────────────
# Year-range helper
# FIX 1: returns "" when both start and end are None — prevents "(None–None)"
# ─────────────────────────────────────────────────────────────────────────────

def _yr(start: Optional[int], end: Optional[int]) -> str:
    """Return ' (2020–2025)' with a leading space, or '' when both are None."""
    if start is None and end is None:
        return ""
    s = str(start) if start is not None else "?"
    e = str(end)   if end   is not None else "?"
    return f" ({s}–{e})"


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builders
# FIX 3: mini prompts use full section headers (PROPOSITION / OPPOSITION /
#         VERDICT) — NOT the abbreviated forms (Prop: / Opp: / Verdict:).
#         The LLM prompt itself controls word count so the output is already
#         short enough; _compress_to_mini is only a safety net, not the primary
#         shortener.
# ─────────────────────────────────────────────────────────────────────────────

def _propose_prompt(topic, start, end, channel, max_chars, context, mini: bool) -> str:
    yr  = _yr(start, end)
    ctx = f"\nBACKGROUND CONTEXT: {context}\n" if context else ""
    header = f"PROPOSITION: {topic}{yr}"

    if mini:
        return textwrap.dedent(f"""
            You are a concise debate writer producing short-form PRO content
            for the @{channel} YouTube Shorts channel.
            Write BRIEF, punchy arguments IN FAVOR of the motion.
            STRICT TARGET: 120–180 words total (so TTS audio is 1–1.5 min).
            Keep EVERY section to 1-2 sentences maximum.
            {ctx}
            Format your response EXACTLY like this
            (preserve full section names, no abbreviations, no extra blank lines):

            {header}

            OPENING STATEMENT
            [1-2 sentences establishing your position]

            Argument 1: [Short Title]
            [1-2 sentences — evidence and reasoning only]

            Argument 2: [Short Title]
            [1-2 sentences — evidence and reasoning only]

            Argument 3: [Short Title]
            [1-2 sentences — evidence and reasoning only]

            CONCLUSION
            [1-2 sentences — why motion should be upheld]

            HARD LIMITS:
            - Total response MUST be under {max_chars} characters
            - Do NOT exceed 180 words under any circumstances
            - Write ONLY the argument text — no tool calls, no JSON, no code
        """).strip()
    else:
        return textwrap.dedent(f"""
            You are a world-class debater writing compelling PRO arguments
            for the @{channel} YouTube channel.
            Write well-structured arguments IN FAVOR of the motion: "{topic}"
            {ctx}
            Format your response EXACTLY like this:

            {header}

            OPENING STATEMENT
            [2-3 sentences establishing your position clearly]

            Argument 1: [Title]
            [3-4 sentences with evidence and reasoning]

            Argument 2: [Title]
            [3-4 sentences with evidence and reasoning]

            Argument 3: [Title]
            [3-4 sentences with evidence and reasoning]

            CONCLUSION
            [2-3 sentences summarizing why the motion should be upheld]

            Keep total response under {max_chars} characters.
            Write ONLY the argument text — no tool calls, no JSON, no code.
        """).strip()


def _oppose_prompt(topic, start, end, channel, max_chars, context, mini: bool,
                   propose_text: str = "") -> str:
    yr  = _yr(start, end)
    ctx = f"\nBACKGROUND CONTEXT: {context}\n" if context else ""
    prop_block = (
        f"\nPROPOSITION for context:\n---\n{propose_text}\n---\n"
        if propose_text else ""
    )
    header = f"OPPOSITION: {topic}{yr}"

    if mini:
        return textwrap.dedent(f"""
            You are a concise debate writer producing short-form CON content
            for the @{channel} YouTube Shorts channel.
            Write BRIEF, punchy arguments AGAINST the motion.
            STRICT TARGET: 120–180 words total (so TTS audio is 1–1.5 min).
            Keep EVERY section to 1-2 sentences maximum.
            {ctx}{prop_block}
            Format your response EXACTLY like this
            (preserve full section names, no abbreviations, no extra blank lines):

            {header}

            OPENING STATEMENT
            [1-2 sentences establishing your counter-position]

            Counter-Argument 1: [Short Title]
            [1-2 sentences — evidence and reasoning only]

            Counter-Argument 2: [Short Title]
            [1-2 sentences — evidence and reasoning only]

            Counter-Argument 3: [Short Title]
            [1-2 sentences — evidence and reasoning only]

            CONCLUSION
            [1-2 sentences — why motion should be rejected]

            HARD LIMITS:
            - Total response MUST be under {max_chars} characters
            - Do NOT exceed 180 words under any circumstances
            - Write ONLY the argument text — no tool calls, no JSON, no code
        """).strip()
    else:
        return textwrap.dedent(f"""
            You are a world-class debater writing compelling CON arguments
            for the @{channel} YouTube channel.
            Write well-structured arguments AGAINST the motion: "{topic}"
            {ctx}{prop_block}
            Format your response EXACTLY like this:

            {header}

            OPENING STATEMENT
            [2-3 sentences establishing your counter-position clearly]

            Counter-Argument 1: [Title]
            [3-4 sentences with evidence and reasoning]

            Counter-Argument 2: [Title]
            [3-4 sentences with evidence and reasoning]

            Counter-Argument 3: [Title]
            [3-4 sentences with evidence and reasoning]

            CONCLUSION
            [2-3 sentences summarizing why the motion should be rejected]

            Keep total response under {max_chars} characters.
            Write ONLY the argument text — no tool calls, no JSON, no code.
        """).strip()


def _decide_prompt(topic, start, end, channel, max_chars, context, mini: bool,
                   propose_text: str = "", oppose_text: str = "") -> str:
    yr  = _yr(start, end)
    ctx = f"\nBACKGROUND CONTEXT: {context}\n" if context else ""
    sides = ""
    if propose_text:
        sides += f"\nPROPOSITION:\n---\n{propose_text}\n---\n"
    if oppose_text:
        sides += f"\nOPPOSITION:\n---\n{oppose_text}\n---\n"
    header = f"VERDICT: {topic}{yr}"

    if mini:
        return textwrap.dedent(f"""
            You are a concise, impartial debate judge producing short-form verdicts
            for the @{channel} YouTube Shorts channel.
            Deliver a SHORT, balanced verdict.
            STRICT TARGET: 120–180 words total (so TTS audio is 1–1.5 min).
            Keep EVERY section to 1-2 sentences maximum.
            {ctx}{sides}
            Format your response EXACTLY like this
            (preserve full section names, no abbreviations, no extra blank lines):

            {header}

            SUMMARY OF PROPOSITION
            [1-2 sentences summarizing PRO arguments]

            SUMMARY OF OPPOSITION
            [1-2 sentences summarizing CON arguments]

            ANALYSIS
            [1-2 sentences comparing both sides]

            DECISION
            [1-2 sentences — final verdict and reason]

            HARD LIMITS:
            - Total response MUST be under {max_chars} characters
            - Do NOT exceed 180 words under any circumstances
            - Write ONLY the verdict text — no tool calls, no JSON, no code
        """).strip()
    else:
        return textwrap.dedent(f"""
            You are an experienced, impartial debate judge delivering a balanced verdict
            for the @{channel} YouTube channel.
            Review both sides and deliver your verdict on: "{topic}"
            {ctx}{sides}
            Format your response EXACTLY like this:

            {header}

            SUMMARY OF PROPOSITION
            [2-3 sentences summarizing the PRO arguments]

            SUMMARY OF OPPOSITION
            [2-3 sentences summarizing the CON arguments]

            ANALYSIS
            [3-4 sentences comparing the strength of both sides]

            DECISION
            [2-3 sentences with your final verdict and reasoning]

            Keep total response under {max_chars} characters.
            Write ONLY the verdict text — no tool calls, no JSON, no code.
        """).strip()


# ─────────────────────────────────────────────────────────────────────────────
# LLM caller — supports ANY LiteLLM model string from data.json
# ─────────────────────────────────────────────────────────────────────────────

def _call_llm(prompt: str, model: str, max_tokens: int) -> str:
    """
    Call any model via LiteLLM (Strategy 1) or direct Anthropic SDK (Strategy 2).
    model comes from data.json → debate_config.llm_debate, e.g.:
      'dashscope/qwen-plus'  |  'ollama/llama3.1:8b'
      'deepseek/deepseek-chat'  |  'claude-sonnet-4-20250514'
    """
    # Strategy 1: LiteLLM — handles all provider prefixes
    try:
        import litellm
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except ImportError:
        pass
    except Exception as litellm_err:
        is_bare_anthropic = (
            "/" not in model and
            ("claude" in model.lower() or "anthropic" in model.lower())
        )
        if not is_bare_anthropic:
            raise RuntimeError(
                f"LiteLLM failed for '{model}': {litellm_err}"
            ) from litellm_err

    # Strategy 2: Direct Anthropic SDK (bare model names only)
    if not _HAS_ANTHROPIC:
        raise RuntimeError(
            "Neither litellm nor anthropic package available. "
            "Run: pip install litellm"
        )
    client = _anthropic_sdk.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in msg.content:
        if hasattr(block, "text"):
            return block.text.strip()
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Hard-cap safety net
# FIX 2: _compress_to_mini is ONLY called when the LLM over-generates despite
#         the prompt's HARD LIMITS instruction. It is NOT the primary shortener.
#         We use a LIGHT version that only trims trailing sentences — it does
#         NOT apply abbreviations (Prop:, Opp:, C-Arg etc.) to keep headers
#         readable as required by debate_video_tool.py downstream.
# ─────────────────────────────────────────────────────────────────────────────

def _hard_cap_trim(text: str, max_chars: int) -> str:
    """
    Lightly trim text to fit within max_chars by removing trailing sentences
    from the longest paragraph. Does NOT abbreviate section headers or words.
    Only invoked when LLM ignores the char limit in the prompt.
    """
    if len(text) <= max_chars:
        return text

    # Split into paragraphs, trim the longest one sentence at a time
    paras = re.split(r'(\n{2,})', text)
    # Rebuild as list of [content, separator] pairs
    pairs: list = []
    i = 0
    while i < len(paras):
        content = paras[i]
        sep = paras[i + 1] if (i + 1 < len(paras) and not paras[i + 1].strip()) else '\n'
        pairs.append([content, sep])
        i += 2 if (i + 1 < len(paras) and not paras[i + 1].strip()) else 1

    # Header pattern — never trim section headers themselves
    _hdr = re.compile(
        r'^(PROPOSITION|OPPOSITION|VERDICT|OPENING|CONCLUSION|'
        r'Argument \d|Counter-Argument \d|SUMMARY OF|ANALYSIS|DECISION)',
        re.IGNORECASE,
    )

    def _joined(p: list) -> str:
        return ''.join(b + s for b, s in p).strip()

    for _ in range(300):
        if len(_joined(pairs)) <= max_chars:
            break
        # Find the longest non-header paragraph
        li, ll = -1, 0
        for idx, (blk, _s) in enumerate(pairs):
            if not _hdr.match(blk.strip()) and len(blk) > ll:
                ll, li = len(blk), idx
        if li == -1:
            break
        # Remove last sentence from that paragraph
        trimmed = re.sub(
            r'[^.!?\n]*[.!?]["\']?\s*$', '', pairs[li][0], flags=re.DOTALL
        ).strip()
        if not trimmed or trimmed == pairs[li][0]:
            pairs.pop(li)
        else:
            pairs[li][0] = trimmed

    result = _joined(pairs)
    # Absolute hard cap as last resort
    if len(result) > max_chars:
        c = result[:max_chars]
        cut = max(c.rfind('.'), c.rfind('\n'))
        result = (c[:cut + 1] if cut > int(max_chars * 0.67) else c).strip()

    return result


# ─────────────────────────────────────────────────────────────────────────────
# File helpers
# ─────────────────────────────────────────────────────────────────────────────

def _write_file(path: str, content: str, overwrite: bool) -> tuple:
    if not overwrite and os.path.exists(path) and os.path.getsize(path) > 0:
        return False, f"⏭️  Skipped (exists): {path}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    kb = max(1, len(content.encode()) // 1024)
    return True, f"✅ Written: {path}  ({kb} KB, {len(content)} chars)"


def _read_safe(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except (OSError, IOError):
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Main tool class
# ─────────────────────────────────────────────────────────────────────────────

class DebateDefinitionTool(BaseTool):
    """
    Generates propose.md / oppose.md / decide.md (full-length) and/or
    propose-m.md / oppose-m.md / decide-m.md (mini/Shorts).

    All values come from data.json via the flat inputs dict built by main.py.
    Nothing is hard-coded. LLM model = data.json → debate_config.llm_debate.

    v3 fixes:
      • (None–None) eliminated — year range omitted when start/end are null
      • Mini files are full and complete — LLM prompt enforces 120-180 word
        target; _hard_cap_trim is only a safety net, NOT the primary shortener
      • Mini section headers are preserved in full (PROPOSITION, OPPOSITION,
        VERDICT) — no abbreviations that break downstream parsing
    """

    name: str = "Debate Definition Tool"
    description: str = (
        "Generates propose.md, oppose.md, decide.md (full debate) and/or "
        "propose-m.md, oppose-m.md, decide-m.md (Shorts/mini debate). "
        "All values driven by data.json — topic, start, end, channel, "
        "llm_debate, debate_max_chars, debate_mini_max_chars, flags. "
        "Pass as JSON matching DebateDefinitionInput."
    )
    args_schema: Type[BaseModel] = DebateDefinitionInput

    # ── _run ─────────────────────────────────────────────────────────────────

    def _run(
        self,
        topic: str,
        filename: str,
        output_dir: str,
        start: Optional[int] = None,
        end:   Optional[int] = None,
        channel: str = "PlayOwnAi",
        debate_definition_enabled: bool = False,
        debate_mini_enabled:        bool = False,
        debate_max_chars:           int  = 10_000,
        debate_mini_max_chars:      int  = 1_200,
        llm_debate: str = "claude-sonnet-4-20250514",
        max_tokens: int = 2048,
        overwrite:     bool = False,
        extra_context: str  = "",
    ) -> str:

        results: list = []
        errors:  list = []

        if not debate_definition_enabled and not debate_mini_enabled:
            return (
                "⏭️  DebateDefinitionTool SKIPPED — "
                "debate_definition_enabled=False AND debate_mini_enabled=False "
                "(check data.json → debate_config)."
            )

        os.makedirs(output_dir, exist_ok=True)
        model = llm_debate  # straight from data.json

        propose_path   = os.path.join(output_dir, "propose.md")
        oppose_path    = os.path.join(output_dir, "oppose.md")
        decide_path    = os.path.join(output_dir, "decide.md")
        propose_m_path = os.path.join(output_dir, "propose-m.md")
        oppose_m_path  = os.path.join(output_dir, "oppose-m.md")
        decide_m_path  = os.path.join(output_dir, "decide-m.md")

        propose_text = oppose_text = decide_text = ""

        # ── 1. Full-length debate files ──────────────────────────────────────
        if debate_definition_enabled:
            results.append(f"\n── Full-Length Debate Files  [model={model}] ──")

            for role, path, get_prompt in [
                (
                    "propose", propose_path,
                    lambda: _propose_prompt(
                        topic, start, end, channel,
                        debate_max_chars, extra_context, mini=False),
                ),
                (
                    "oppose", oppose_path,
                    lambda: _oppose_prompt(
                        topic, start, end, channel,
                        debate_max_chars, extra_context, mini=False,
                        propose_text=propose_text),
                ),
                (
                    "decide", decide_path,
                    lambda: _decide_prompt(
                        topic, start, end, channel,
                        debate_max_chars, extra_context, mini=False,
                        propose_text=propose_text, oppose_text=oppose_text),
                ),
            ]:
                existing = _read_safe(path)
                if existing and not overwrite:
                    results.append(f"⏭️  Skipped (exists): {path}")
                    if role == "propose":  propose_text = existing
                    elif role == "oppose": oppose_text  = existing
                    else:                  decide_text  = existing
                    continue

                try:
                    text = _call_llm(get_prompt(), model, max_tokens)
                    # Safety net only — prompt already enforces the limit
                    if len(text) > debate_max_chars:
                        text = _hard_cap_trim(text, debate_max_chars)
                    _, msg = _write_file(path, text, overwrite=True)
                    results.append(msg)
                    if role == "propose":  propose_text = text
                    elif role == "oppose": oppose_text  = text
                    else:                  decide_text  = text
                except Exception as exc:
                    errors.append(f"❌ {role}.md [{model}]: {exc}")

        else:
            # Not generating full-length — load any existing for mini fallback
            propose_text = _read_safe(propose_path)
            oppose_text  = _read_safe(oppose_path)
            decide_text  = _read_safe(decide_path)

        # ── 2. Mini / Shorts debate files ────────────────────────────────────
        if debate_mini_enabled:
            # decide-m gets slightly smaller cap (matches main.py convention)
            mini_decide_cap = int(debate_mini_max_chars * 0.85)

            results.append(
                f"\n── Mini / Shorts Debate Files  "
                f"[model={model}, cap={debate_mini_max_chars}] ──"
            )

            mini_jobs = [
                ("propose", propose_m_path, propose_text, debate_mini_max_chars),
                ("oppose",  oppose_m_path,  oppose_text,  debate_mini_max_chars),
                ("decide",  decide_m_path,  decide_text,  mini_decide_cap),
            ]

            for role, m_path, full_text, cap in mini_jobs:
                if _read_safe(m_path) and not overwrite:
                    results.append(f"⏭️  Skipped (exists): {m_path}")
                    continue

                # Build the per-role prompt
                try:
                    if role == "propose":
                        prompt = _propose_prompt(
                            topic, start, end, channel, cap,
                            extra_context, mini=True,
                        )
                    elif role == "oppose":
                        # Feed the already-written propose-m for context
                        prompt = _oppose_prompt(
                            topic, start, end, channel, cap,
                            extra_context, mini=True,
                            propose_text=_read_safe(propose_m_path),
                        )
                    else:  # decide
                        prompt = _decide_prompt(
                            topic, start, end, channel, cap,
                            extra_context, mini=True,
                            propose_text=_read_safe(propose_m_path),
                            oppose_text=_read_safe(oppose_m_path),
                        )

                    # Use half the token budget — mini content is short
                    mini_text = _call_llm(prompt, model, max_tokens // 2)

                    # Safety net: light trim only if LLM exceeded the cap
                    if len(mini_text) > cap:
                        mini_text = _hard_cap_trim(mini_text, cap)

                    _, msg = _write_file(m_path, mini_text, overwrite=True)
                    results.append(
                        msg + f"  [LLM:{model}, {len(mini_text)} chars, "
                              f"{len(mini_text.split())} words]"
                    )

                except Exception as exc_llm:
                    # Fallback: light-trim the full-length version
                    if full_text:
                        try:
                            mini_text = _hard_cap_trim(full_text, cap)
                            _, msg = _write_file(m_path, mini_text, overwrite=True)
                            results.append(
                                msg + f"  [trim-fallback, {len(mini_text)} chars]"
                            )
                        except Exception as exc_trim:
                            errors.append(
                                f"❌ {role}-m.md: LLM({exc_llm}) & "
                                f"trim-fallback({exc_trim})"
                            )
                    else:
                        errors.append(
                            f"❌ {role}-m.md: LLM failed [{model}] ({exc_llm}) "
                            f"— no source text for fallback."
                        )

        # ── Summary ──────────────────────────────────────────────────────────
        w = sum(1 for r in results if r.startswith("✅"))
        s = sum(1 for r in results if r.startswith("⏭️"))
        report = "\n".join([
            "=" * 60,
            "✅ DebateDefinitionTool completed",
            f"   Written: {w}  |  Skipped: {s}  |  Errors: {len(errors)}",
            f"   LLM    : {model}",
            "=" * 60,
        ] + results + errors)
        print(report)
        return report
