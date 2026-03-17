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
    - Shortens long phrases: entry-level engineers → juniors
    - Hard character cap with intelligent sentence boundary detection
    - Writes propose_{lang}.md, oppose_{lang}.md, decide_{lang}.md
    """
    name: str = "Debate Definition Tool"
    description: str = (
        "Optimizes debate text to meet character limits through aggressive compression.  "
        "Smart-skips if lang-suffixed .md files already exist.  "
        "Removes aux verbs & verbose phrases (full/HD version only).  "
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
        _mobile_paths = {
            role: os.path.join(output_dir, f"{role}-m.md")
            for role in ('propose', 'oppose', 'decide')
        }
        _all_exist = all(
            os.path.exists(p) and os.path.getsize(p) > 0
            for p in list(_md_paths.values()) + list(_mobile_paths.values())
        )
        if _all_exist:
            _sizes  = {role: os.path.getsize(p) for role, p in _md_paths.items()}
            _msizes = {role: os.path.getsize(p) for role, p in _mobile_paths.items()}
            print(f"[DebateDef] ⭐️ Debate files exist ({_lang}) — skipping LLM generation (using existing)")
            for role in ('propose', 'oppose', 'decide'):
                print(f"[DebateDef]   {role}_{_lang}.md ({_sizes[role]} bytes)  {role}-m.md ({_msizes[role]} bytes)")
            lines = []
            for role in ('propose', 'oppose', 'decide'):
                lines.append(f"   ✓ {role}_{_lang}.md ({_sizes[role]} bytes)  {role}-m.md ({_msizes[role]} bytes)")
            return f"⭐️ Debate files exist ({_lang}) — skipping (using existing)\n" + "\n".join(lines)

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

        # ── Mobile (Shorts): raw LLM text, NO restrictions ───────────────────

        # ── Process, log, and write each .md file ────────────────────────────
        os.makedirs(output_dir, exist_ok=True)
        results = []

        for role, raw in all_texts.items():
            orig_chars = len(raw)

            # ── Full version → propose_En.md / oppose_En.md / decide_En.md ──
            try:
                cleaned = self._clean_debate_text(raw, debate_max_chars)
            except Exception as e:
                traceback.print_exc()
                return f"❌ Error cleaning {role} text: {e}"

            cleaned_chars = len(cleaned)
            reduction = orig_chars - cleaned_chars
            reduction_pct = (reduction / orig_chars * 100) if orig_chars > 0 else 0

            print(f"\n[DebateDef] {role.upper()}: {orig_chars} → {cleaned_chars} chars (↓{reduction_pct:.0f}%)")

            md_path = _md_paths[role]
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            print(f"[DebateDef] 📝 Saved: {md_path} ({cleaned_chars} chars)")

            # ── Mobile/Shorts version → propose-m.md / oppose-m.md / decide-m.md ──
            # ✅ NO restrictions — raw LLM text written exactly as produced by tasks.yaml spec.
            try:
                mobile = self._make_mobile(raw)
            except Exception as e:
                traceback.print_exc()
                return f"❌ Error creating mobile text for {role}: {e}"

            mobile_path = os.path.join(output_dir, f"{role}-m.md")
            with open(mobile_path, 'w', encoding='utf-8') as f:
                f.write(mobile)
            print(f"[DebateDef] 📱 Saved: {mobile_path} ({len(mobile)} chars)")

            results.append({
                'type':       role,
                'original':   orig_chars,
                'cleaned':    cleaned_chars,
                'mobile':     len(mobile),
                'reduction':  reduction,
            })

        elapsed = time.time() - t0

        summary = f"✅ Debate texts optimized in {elapsed:.1f}s\n\n"
        for r in results:
            summary += (
                f"✓ {r['type'].upper()}: {r['original']} → {r['cleaned']} chars (saved {r['reduction']}) "
                f"| 📱 {r['mobile']} chars\n"
            )
        summary += f"\nFiles written to {output_dir}/\n"
        summary += f"  Full  : propose_{_lang}.md  oppose_{_lang}.md  decide_{_lang}.md\n"
        summary += f"  Mobile: propose-m.md  oppose-m.md  decide-m.md\n"
        summary += f"→ ready for debate_video_tool"

        print(f"\n[DebateDef] ✅ Complete in {elapsed:.1f}s — ready for video generation")
        return summary

    # ── Text compression ──────────────────────────────────────────────────────

    def _clean_debate_text(self, text: str, max_chars: int = 2000) -> str:
        """Compress debate text for full/HD version."""
        text = self._apply_abbreviations(text)
        text = self._remove_aux_and_articles(text)
        text = self._collapse_whitespace(text)
        text = self._hard_cap(text, max_chars)
        return text

    def _make_mobile(self, text: str) -> str:
        """
        Shorts / -m.md version — raw LLM output written as-is.
        Zero post-processing: no abbreviations, no aux/article removal,
        no header rewrites, no hard cap.
        The tasks.yaml spec already defines the exact format the LLM must
        produce, so any transformation here corrupts the intended output.
        """
        return text.strip()

    def _apply_abbreviations(self, text: str) -> str:
        """All header shortenings, phrase subs, and word abbreviations."""

        # ── HEADERS ──────────────────────────────────────────────────────────
        text = re.sub(r'\bCOUNTER[\s\-]?ARGUMENT\s*(\d+)\s*[:\-]?', r'C-Arg \1:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bARGUMENT\s*(\d+)\s*[:\-]?',                  r'ARG \1:',   text, flags=re.IGNORECASE)
        text = re.sub(r'\bOPENING\s+STATEMENT\s*[:\-]?',    'Opening:',      text, flags=re.IGNORECASE)
        text = re.sub(r'\bCLOSING\s+STATEMENT\s*[:\-]?',    'Closing:',      text, flags=re.IGNORECASE)
        text = re.sub(r'\bSUMMARY\s+OF\s+PROPOSITION\s*[:\-]?', 'Sum Of Prop:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bSUMMARY\s+OF\s+OPPOSITION\s*[:\-]?',  'Sum Of Opp:',  text, flags=re.IGNORECASE)
        text = re.sub(r'\bSUMMARY\s+OF\s+VERDICT\s*[:\-]?',     'Sum Verdict:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bCONCLUSION\s*[:\-]?',  'Concl:',  text, flags=re.IGNORECASE)
        text = re.sub(r'\bPROPOSITION\s*[:\-]?', 'Prop:',   text, flags=re.IGNORECASE)
        text = re.sub(r'\bOPPOSITION\s*[:\-]?',  'Opp:',    text, flags=re.IGNORECASE)
        text = re.sub(r'\bANALYSIS\s*[:\-]?',    'Anal.:',  text, flags=re.IGNORECASE)
        text = re.sub(r'\bDECISION\s*[:\-]?',    'Decis.:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bVERDICT\s*[:\-]?',     'Verdict:',text, flags=re.IGNORECASE)

        # ── COMMON WORDS → SYMBOLS / SHORT FORMS ─────────────────────────────
        text = re.sub(r'\band\b',      '&',    text, flags=re.IGNORECASE)
        text = re.sub(r'\bwith\b',     'w/',   text, flags=re.IGNORECASE)
        text = re.sub(r'\bwithout\b',  'w/o',  text, flags=re.IGNORECASE)
        text = re.sub(r'\bversus\b',   'vs',   text, flags=re.IGNORECASE)
        text = re.sub(r'\bvs\.\b',    'vs',   text, flags=re.IGNORECASE)
        text = re.sub(r'\btherefore\b','→',    text, flags=re.IGNORECASE)
        text = re.sub(r'\bbecause\b',  'b/c',  text, flags=re.IGNORECASE)
        text = re.sub(r'\bthrough\b',  'thru', text, flags=re.IGNORECASE)
        text = re.sub(r'\bapproximately\b', '~', text, flags=re.IGNORECASE)
        text = re.sub(r'\bincluding\b', 'incl.',text, flags=re.IGNORECASE)

        # ── PHRASE SUBSTITUTIONS ─────────────────────────────────────────────
        phrase_subs = [
            ('entry-level software engineers', 'juniors'),
            ('entry-level engineers',          'juniors'),
            ('entry-level',                    'junior'),
            ('software engineers',             'devs'),
            ('human development',              'human growth'),
            ('social consequences',            'social impact'),
            ('presents a compelling case',     'supports'),
            ('raise valid concerns',           'raise concerns'),
            ('rather than',                    'not'),
            ('For instance, ',                 ''),
            ('For example, ',                  ''),
            ('thereby ',                       ''),
            ('highlights',                     'shows'),
            ('emphasizes',                     'stresses'),
            ('emphasize',                      'stress'),
            ('invaluable',                     'key'),
            ('crucial',                        'key'),
            ('essential',                      'vital'),
            ('In conclusion',                  'Concl.'),
            ('In summary',                     'In sum'),
        ]
        for src, dst in phrase_subs:
            text = text.replace(src, dst)

        # ── WORD ABBREVIATIONS ────────────────────────────────────────────────
        word_abbrevs = [
            (r'\boperational\b',   'ops'),
            (r'\befficiency\b',    'speed'),
            (r'\bcapabilities\b',  'ability'),
            (r'\bcapability\b',    'ability'),
            (r'\bprofessional\b',  'prof'),
            (r'\bcollaboration\b', 'teamwork'),
            (r'\bcollaborative\b', 'team-based'),
            (r'\bengineer\b',      'dev'),
            (r'\binformation\b',   'info'),
            (r'\bdevelopment\b',   'dev'),
            (r'\bmanagement\b',    'mgmt'),
            (r'\borganizations\b', 'orgs'),
            (r'\borganization\b',  'org'),
            (r'\btechnology\b',    'tech'),
            (r'\btechnologies\b',  'tech'),
            (r'\bartificial intelligence\b', 'AI'),
            (r'\bmachine learning\b',        'ML'),
            (r'\bnatural language processing\b', 'NLP'),
            (r'\balgorithm\b',     'algo'),
            (r'\balgorithms\b',    'algos'),
            (r'\bdemonstrates\b',  'shows'),
            (r'\bdemonstrate\b',   'show'),
            (r'\bsignificant\b',   'key'),
            (r'\bsignificantly\b', 'greatly'),
            (r'\bimportant\b',     'key'),
            (r'\bimportance\b',    'value'),
            (r'\bunderstanding\b', 'grasp'),
            (r'\bintelligence\b',  'intellect'),
            (r'\bintelligent\b',   'smart'),
        ]
        for pattern, replacement in word_abbrevs:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # ── REMOVE INSTRUCTION LEAKAGE ────────────────────────────────────────
        text = re.sub(r'\[.*?\]', '', text)
        text = re.split(
            r'\n(ADDITIONAL NOTES|NOTES FOR VIDEO|PRODUCTION NOTES)',
            text, flags=re.IGNORECASE
        )[0]

        return text

    def _remove_aux_and_articles(self, text: str) -> str:
        """Remove auxiliary verbs and articles."""
        aux_list = [
            r'\bam\b', r'\bis\b', r'\bare\b', r'\bwas\b', r'\bwere\b',
            r'\bbe\b', r'\bbeing\b', r'\bbeen\b',
            r'\bhave\b', r'\bhas\b', r'\bhad\b',
            r'\bdo\b', r'\bdoes\b', r'\bdid\b',
            r'\bshall\b', r'\bshould\b', r'\bwill\b', r'\bwould\b',
            r'\bmay\b', r'\bmight\b', r'\bmust\b',
            r'\bcan\b', r'\bcould\b', r'\bought\b',
        ]
        for aux in aux_list:
            text = re.sub(aux + r'\s+', '', text, flags=re.IGNORECASE)

        text = re.sub(r'\bthe\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\ban\s+',  '', text, flags=re.IGNORECASE)
        text = re.sub(r'\ba\s+',   '', text, flags=re.IGNORECASE)
        text = re.sub(r'(?<=\s)to\s+', '', text, flags=re.IGNORECASE)
        return text

    def _collapse_whitespace(self, text: str) -> str:
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _hard_cap(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        cap = text[:max_chars]
        cut = max(cap.rfind('.'), cap.rfind('\n'))
        if cut > int(max_chars * 0.67):
            return cap[:cut + 1].strip()
        return cap.strip()
