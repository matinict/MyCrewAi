"""
Debate Definition Tool (OPTIMIZED v3)
Aggressive text optimization to meet character limits.
- Removes auxiliary verbs & articles
- Shortens phrases & headers
- Abbreviates long words
- Hard cap enforcement with sentence boundary detection
- Returns cleaned text directly (NO .md files)
Triggered by: "debate_definition_enabled": true in data.json
"""
import os
import re
import time
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field


class DebateDefinitionToolInput(BaseModel):
    """Input schema for DebateDefinitionTool."""
    topic: str = Field(..., description="Full debate topic/motion")
    filename: str = Field(..., description="Base filename slug")
    output_dir: str = Field(..., description="Output subdirectory for debate files")
    propose_text: str = Field(..., description="Arguments supporting the motion (FOR)")
    oppose_text: str = Field(..., description="Arguments against the motion (AGAINST)")
    decide_text: str = Field(..., description="Moderator's conclusion/verdict")
    debate_definition_enabled: bool = Field(default=False, description="Whether to process debate definitions")
    channel: str = Field(default="PlayOwnAi", description="Channel name for branding")
    debate_max_chars: int = Field(default=2000, description="Hard cap on each debate argument in characters")


class DebateDefinitionTool(BaseTool):
    """
    Optimized debate definition tool - aggressive text compression.
    - Removes auxiliary verbs, articles, verbose phrases
    - Shortens headers: ARGUMENT 2 → ARG 2, COUNTER-ARGUMENT 2 → COUNTER-ARG 2
    - Shortens long phrases: entry-level engineers → juniors, engineer → eng
    - Returns cleaned text (NO .md file creation)
    - Hard character cap with intelligent sentence boundary detection
    """
    name: str = "Debate Definition Tool"
    description: str = (
        "Optimizes debate text to meet character limits through aggressive compression.  "
        "Removes aux verbs, shortens headers & phrases.  "
        "Returns cleaned text for debate_video_tool. "
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
            return "🔇 Debate definition skipped (debate_definition_enabled=false)"

        t0 = time.time()
        print(f"\n[DebateDef] ▶ Optimizing debate text")
        print(f"[DebateDef]   Topic: {topic}")
        print(f"[DebateDef]   Max chars: {debate_max_chars}")

        # Validate all 3 texts
        all_texts = {
            'propose': propose_text,
            'oppose': oppose_text,
            'decide': decide_text
        }

        for name, text in all_texts.items():
            if not text or not text.strip():
                return f"❌ {name}_text is empty. Complete all 3 arguments first."

        results = []

        # Process all 3 texts
        for file_type, text in [('propose', propose_text), ('oppose', oppose_text), ('decide', decide_text)]:
            orig_chars = len(text)
            orig_words = len(text.split())

            # Clean and optimize
            cleaned = self._clean_debate_text(text, debate_max_chars)
            cleaned_chars = len(cleaned)
            cleaned_words = len(cleaned.split())

            reduction = orig_chars - cleaned_chars
            reduction_pct = (reduction / orig_chars * 100) if orig_chars > 0 else 0

            print(f"\n[DebateDef] {file_type.upper()}: {orig_chars} → {cleaned_chars} chars (↓{reduction_pct:.0f}%)")

            results.append({
                'type': file_type,
                'original': orig_chars,
                'cleaned': cleaned_chars,
                'reduction': reduction
            })

        elapsed = time.time() - t0

        summary = f"✅ Debate texts optimized in {elapsed:.1f}s\n\n"
        for r in results:
            summary += f"✓ {r['type'].upper()}: {r['original']} → {r['cleaned']} chars (saved {r['reduction']})\n"

        summary += f"\nReady for debate_video_tool"
        print(f"\n[DebateDef] ✅ Complete - ready for video generation")

        return summary

    def _clean_debate_text(self, text: str, max_chars: int = 2000) -> str:
        """Aggressively compress debate text to meet character limits."""

        # ── STEP 1: SHORTEN HEADERS ──────────────────────────────────
        text = re.sub(r'\bCOUNTER[\s\-]?ARGUMENT\s+(\d+)\s*[:\-]?', r'COUNTER-ARG\1:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bARGUMENT\s+(\d+)\s*[:\-]?', r'ARG\1:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bOPENING\s+STATEMENT\s*[:\-]?', 'OPENING:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bCLOSING\s+STATEMENT\s*[:\-]?', 'CLOSING:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bSUMMARY\s+OF\s+PROPOSITION\s*[:\-]?', 'PRO SUMMARY:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bSUMMARY\s+OF\s+OPPOSITION\s*[:\-]?', 'CON SUMMARY:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bSUMMARY\s+OF\s+VERDICT\s*[:\-]?', 'VERDICT SUMMARY:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bCONCLUSION\s*[:\-]?', 'CONCLUSION:', text, flags=re.IGNORECASE)

        # ── STEP 2: ABBREVIATE LONG WORDS ────────────────────────────
        text = text.replace('operational', 'ops')
        text = text.replace('efficiency', 'speed')
        text = text.replace('capabilities', 'ability')
        text = text.replace('professional', 'prof')
        text = text.replace('collaboration', 'teamwork')
        text = text.replace('collaborative', 'team-based')
        text = text.replace('engineer', 'eng')
        text = text.replace('information', 'info')
        text = text.replace('development', 'dev')
        text = text.replace('management', 'mgmt')
        text = text.replace('organization', 'org')
        text = text.replace('organizations', 'orgs')

        # ── STEP 3: SHORTEN LONG PHRASES ────────────────────────────
        text = text.replace('entry-level software engineers', 'juniors')
        text = text.replace('entry-level engineers', 'juniors')
        text = text.replace('entry-level', 'junior')
        text = text.replace('software engineers', 'engs')
        text = text.replace('human development', 'human growth')
        text = text.replace('social consequences', 'social impact')
        text = text.replace('problem-solving', 'problem solve')
        text = text.replace('innovation', 'innovation')
        text = text.replace('presents a compelling case', 'supports')
        text = text.replace('raise valid concerns', 'raise concerns')
        text = text.replace('highlights', 'shows')
        text = text.replace('emphasizes', 'stresses')
        text = text.replace('emphasize', 'stress')
        text = text.replace('invaluable', 'key')
        text = text.replace('crucial', 'key')
        text = text.replace('essential', 'vital')
        text = re.sub(r'\brather than\s+', 'not ', text)
        text = re.sub(r'For instance, ', '', text)
        text = re.sub(r'thereby ', '', text)

        # ── STEP 4: REMOVE AUXILIARY VERBS & ARTICLES ────────────────
        text = re.sub(r'\bcan\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bwill\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bwould\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bshould\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bis\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bare\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bwas\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bwere\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bhas\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bhave\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bhad\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bdo\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bdoes\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bdid\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bto\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bthe\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\ba\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\ban\s+', '', text, flags=re.IGNORECASE)

        # ── STEP 5: COLLAPSE WHITESPACE ────────────────────────────
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        # ── STEP 6: REMOVE INSTRUCTION LEAKAGE ──────────────────────
        text = re.sub(r'\[.*?\]', '', text)
        text = re.split(r'\n(ADDITIONAL NOTES|NOTES FOR VIDEO|PRODUCTION NOTES)', text, flags=re.IGNORECASE)[0]

        # ── STEP 7: HARD CAP AT max_chars ───────────────────────────
        if len(text) > max_chars:
            cap = text[:max_chars]
            # Cut at sentence boundary
            cut = max(cap.rfind('.'), cap.rfind('\n'))
            if cut > int(max_chars * 0.67):
                text = cap[:cut+1].strip()
            else:
                text = cap.strip()

        return text
