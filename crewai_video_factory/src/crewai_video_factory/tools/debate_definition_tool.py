"""
Debate Definition Tool (OPTIMIZED v4)
Aggressive text optimization to meet character limits.
- Smart skip: if all 3 lang-suffixed .md files already exist, returns immediately
- Removes auxiliary verbs & articles
- Shortens phrases & headers
- Abbreviates long words
- Hard cap enforcement with sentence boundary detection
- Writes lang-suffixed .md files (propose_En.md, oppose_En.md, decide_En.md)
Triggered by: "debate_definition_enabled": true in data.json
"""
import os
import re
import time
import traceback
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
    lang_suffix: str = Field(default="En", description="Language suffix for output .md filenames. e.g. 'En', 'Bn', 'Fr'")


class DebateDefinitionTool(BaseTool):
    """
    Optimized debate definition tool - aggressive text compression.
    - Smart skip: all 3 lang-suffixed .md files already exist → returns immediately
    - Removes auxiliary verbs, articles, verbose phrases
    - Shortens headers: ARGUMENT 2 → ARG 2, COUNTER-ARGUMENT 2 → COUNTER-ARG 2
    - Shortens long phrases: entry-level engineers → juniors
    - Hard character cap with intelligent sentence boundary detection
    - Writes propose_{lang}.md, oppose_{lang}.md, decide_{lang}.md
    """
    name: str = "Debate Definition Tool"
    description: str = (
        "Optimizes debate text to meet character limits through aggressive compression.  "
        "Smart-skips if lang-suffixed .md files already exist.  "
        "Removes aux verbs, shortens headers & phrases.  "
        "Writes propose/oppose/decide_{lang}.md for debate_video_tool. "
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
        lang_suffix: str = "En",
    ) -> str:

        if not debate_definition_enabled:
            return "🔇 Debate definition skipped (debate_definition_enabled=false)"

        _lang = lang_suffix if lang_suffix else "En"

        # ── SMART SKIP: all 3 lang-suffixed .md files already exist ──────────
        _md_paths = {
            role: os.path.join(output_dir, f"{role}_{_lang}.md")
            for role in ('propose', 'oppose', 'decide')
        }
        _all_exist = all(
            os.path.exists(p) and os.path.getsize(p) > 0
            for p in _md_paths.values()
        )
        if _all_exist:
            _sizes = {role: os.path.getsize(p) for role, p in _md_paths.items()}
            print(f"[DebateDef] ⭐️ Debate files exist ({_lang}) — skipping LLM generation (using existing)")
            for role, p in _md_paths.items():
                print(f"[DebateDef]   {role}_{_lang}.md ({_sizes[role]} bytes)")
            return (
                f"⭐️ Debate files exist ({_lang}) — skipping (using existing)\n"
                + "\n".join(f"   ✓ {role}_{_lang}.md ({_sizes[role]} bytes)" for role in ('propose', 'oppose', 'decide'))
            )

        t0 = time.time()
        print(f"\n[DebateDef] ▶ Optimizing debate text")
        print(f"[DebateDef]   Topic:      {topic}")
        print(f"[DebateDef]   Max chars:  {debate_max_chars}")
        print(f"[DebateDef]   Lang:       {_lang}")

        # ── Validate all 3 texts ─────────────────────────────────────────────
        all_texts = {
            'propose': propose_text,
            'oppose':  oppose_text,
            'decide':  decide_text,
        }
        for role, text in all_texts.items():
            if not text or not text.strip():
                return f"❌ {role}_text is empty. Complete all 3 arguments first."

        # ── Process, log, and write each .md file ────────────────────────────
        os.makedirs(output_dir, exist_ok=True)
        results = []

        for role, raw in all_texts.items():
            orig_chars = len(raw)

            try:
                cleaned = self._clean_debate_text(raw, debate_max_chars)
            except Exception as e:
                traceback.print_exc()
                return f"❌ Error cleaning {role} text: {e}"

            cleaned_chars = len(cleaned)
            reduction = orig_chars - cleaned_chars
            reduction_pct = (reduction / orig_chars * 100) if orig_chars > 0 else 0

            print(f"\n[DebateDef] {role.upper()}: {orig_chars} → {cleaned_chars} chars (↓{reduction_pct:.0f}%)")

            # Write lang-suffixed .md file
            md_path = _md_paths[role]
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            print(f"[DebateDef] 📝 Saved: {md_path} ({cleaned_chars} chars)")

            results.append({
                'type':      role,
                'original':  orig_chars,
                'cleaned':   cleaned_chars,
                'reduction': reduction,
            })

        elapsed = time.time() - t0

        summary = f"✅ Debate texts optimized in {elapsed:.1f}s\n\n"
        for r in results:
            summary += f"✓ {r['type'].upper()}: {r['original']} → {r['cleaned']} chars (saved {r['reduction']})\n"
        summary += f"\nFiles written to {output_dir}/ — ready for debate_video_tool"

        print(f"\n[DebateDef] ✅ Complete in {elapsed:.1f}s — ready for video generation")
        return summary

    # ── Text compression ──────────────────────────────────────────────────────

    def _clean_debate_text(self, text: str, max_chars: int = 2000) -> str:
        """Aggressively compress debate text to meet character limits."""

        # ── STEP 1: SHORTEN HEADERS ──────────────────────────────────────────
        text = re.sub(r'\bCOUNTER[\s\-]?ARGUMENT\s+(\d+)\s*[:\-]?', r'COUNTER-ARG \1:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bARGUMENT\s+(\d+)\s*[:\-]?',               r'ARG \1:',         text, flags=re.IGNORECASE)
        text = re.sub(r'\bOPENING\s+STATEMENT\s*[:\-]?',   'OPENING:',        text, flags=re.IGNORECASE)
        text = re.sub(r'\bCLOSING\s+STATEMENT\s*[:\-]?',   'CLOSING:',        text, flags=re.IGNORECASE)
        text = re.sub(r'\bSUMMARY\s+OF\s+PROPOSITION\s*[:\-]?', 'PRO SUMMARY:',     text, flags=re.IGNORECASE)
        text = re.sub(r'\bSUMMARY\s+OF\s+OPPOSITION\s*[:\-]?',  'CON SUMMARY:',     text, flags=re.IGNORECASE)
        text = re.sub(r'\bSUMMARY\s+OF\s+VERDICT\s*[:\-]?',     'VERDICT SUMMARY:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bCONCLUSION\s*[:\-]?', 'CONCLUSION:', text, flags=re.IGNORECASE)

        # ── STEP 2: PHRASE SUBSTITUTIONS (longest first to avoid partial hits) ─
        phrase_subs = [
            ('entry-level software engineers', 'juniors'),
            ('entry-level engineers',          'juniors'),
            ('entry-level',                    'junior'),
            ('software engineers',             'devs'),
            ('human development',              'human growth'),
            ('social consequences',            'social impact'),
            ('problem-solving',                'problem-solving'),   # keep hyphen, saves nothing
            ('presents a compelling case',     'supports'),
            ('raise valid concerns',           'raise concerns'),
            ('rather than',                    'not'),
            ('For instance, ',                 ''),
            ('thereby ',                       ''),
            ('highlights',                     'shows'),
            ('emphasizes',                     'stresses'),
            ('emphasize',                      'stress'),
            ('invaluable',                     'key'),
            ('crucial',                        'key'),
            ('essential',                      'vital'),
        ]
        for src, dst in phrase_subs:
            text = text.replace(src, dst)

        # ── STEP 3: WORD ABBREVIATIONS ────────────────────────────────────────
        # Use word-boundary regex to avoid partial hits (e.g. "professional" → "profs" not "profs")
        word_abbrevs = [
            (r'\boperational\b',  'ops'),
            (r'\befficiency\b',   'speed'),
            (r'\bcapabilities\b', 'ability'),
            (r'\bprofessional\b', 'prof'),
            (r'\bcollaboration\b','teamwork'),
            (r'\bcollaborative\b','team-based'),
            (r'\bengineer\b',     'dev'),
            (r'\binformation\b',  'info'),
            (r'\bdevelopment\b',  'dev'),
            (r'\bmanagement\b',   'mgmt'),
            (r'\borganizations\b','orgs'),
            (r'\borganization\b', 'org'),
        ]
        for pattern, replacement in word_abbrevs:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # ── STEP 4: REMOVE AUXILIARY VERBS & ARTICLES ────────────────────────
        # NOTE: Only strip when followed by a space (not at end-of-line) to avoid
        # corrupting words that START with these sequences (e.g. "can" in "candidate").
        # The \b word-boundary + \s+ trailing space handles this safely.
        aux_removals = [
            r'\bcan\b', r'\bwill\b', r'\bwould\b', r'\bshould\b',
            r'\bis\b',  r'\bare\b',  r'\bwas\b',   r'\bwere\b',
            r'\bhas\b', r'\bhave\b', r'\bhad\b',
            r'\bdo\b',  r'\bdoes\b', r'\bdid\b',
        ]
        for aux in aux_removals:
            text = re.sub(aux + r'\s+', '', text, flags=re.IGNORECASE)

        # Articles stripped with word boundary — safer than the original bare \ba\s+
        text = re.sub(r'\bthe\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\ban\s+',  '', text, flags=re.IGNORECASE)
        text = re.sub(r'\ba\s+',   '', text, flags=re.IGNORECASE)

        # "to " only at start of infinitive phrases (preceded by space or newline)
        # Stripping ALL "to " breaks words like "today", "together", "toward"
        text = re.sub(r'(?<=\s)to\s+', '', text, flags=re.IGNORECASE)

        # ── STEP 5: REMOVE INSTRUCTION LEAKAGE ───────────────────────────────
        text = re.sub(r'\[.*?\]', '', text)
        text = re.split(
            r'\n(ADDITIONAL NOTES|NOTES FOR VIDEO|PRODUCTION NOTES)',
            text, flags=re.IGNORECASE
        )[0]

        # ── STEP 6: COLLAPSE WHITESPACE ──────────────────────────────────────
        # Must run AFTER removals to tidy up double-spaces they leave behind
        text = re.sub(r'[ \t]+', ' ', text)          # collapse inline spaces/tabs
        text = re.sub(r'\n{3,}', '\n\n', text)       # max 1 blank line
        text = text.strip()

        # ── STEP 7: HARD CAP AT max_chars ────────────────────────────────────
        if len(text) > max_chars:
            cap = text[:max_chars]
            # Prefer cutting at a sentence boundary in the last third
            cut = max(cap.rfind('.'), cap.rfind('\n'))
            if cut > int(max_chars * 0.67):
                text = cap[:cut + 1].strip()
            else:
                text = cap.strip()

        return text
