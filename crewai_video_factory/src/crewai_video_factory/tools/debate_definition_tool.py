"""
Debate Definition Tool (OPTIMIZED v5)
Auto-generates debate files for video factory.
Smart skip: if all 6 .md files exist, returns immediately
Full version: compressed for HD video (max_chars)
Mobile version: 100% full content, NO restrictions
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
    topic: str = Field(..., description="Full debate topic/motion")
    filename: str = Field(..., description="Base filename slug")
    output_dir: str = Field(..., description="Output subdirectory for debate files")
    propose_text: str = Field(..., description="Arguments supporting the motion (FOR)")
    oppose_text: str = Field(..., description="Arguments against the motion (AGAINST)")
    decide_text: str = Field(..., description="Moderator's conclusion/verdict")
    debate_definition_enabled: bool = Field(default=False, description="Whether to process debate definitions")
    channel: str = Field(default="PlayOwnAi", description="Channel name for branding")
    debate_max_chars: int = Field(default=5000, description="Hard cap on each debate argument in characters")
    lang_suffix: str = Field(default="En", description="Language suffix for output .md filenames")

class DebateDefinitionTool(BaseTool):
    name: str = "Debate Definition Tool"
    description: str = "Auto-generates debate files for video factory. Mobile -m.md = full content, no restrictions."
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
        debate_max_chars: int = 5000,
        lang_suffix: str = "En",
    ) -> str:

        if not debate_definition_enabled:
            return "🔇 Debate definition skipped (debate_definition_enabled=false)"

        _lang = lang_suffix if lang_suffix else "En"

        # ── SMART SKIP: all 6 .md files already exist ──────────
        _md_paths = {role: os.path.join(output_dir, f"{role}_{_lang}.md") for role in ('propose', 'oppose', 'decide')}
        _mobile_paths = {role: os.path.join(output_dir, f"{role}-m.md") for role in ('propose', 'oppose', 'decide')}
        _all_exist = all(os.path.exists(p) and os.path.getsize(p) > 0 for p in list(_md_paths.values()) + list(_mobile_paths.values()))

        if _all_exist:
            _sizes = {role: os.path.getsize(p) for role, p in _md_paths.items()}
            _msizes = {role: os.path.getsize(p) for role, p in _mobile_paths.items()}
            print(f"[DebateDef] ⭐️ Debate files exist ({_lang}) — skipping (using existing)")
            lines = [f"   ✓ {role}_{_lang}.md ({_sizes[role]} bytes)  {role}-m.md ({_msizes[role]} bytes)" for role in ('propose', 'oppose', 'decide')]
            return f"⭐️ Debate files exist ({_lang}) — skipping\n" + "\n".join(lines)

        t0 = time.time()
        print(f"\n[DebateDef] ▶ Generating debate files")
        print(f"[DebateDef]   Topic: {topic}")
        print(f"[DebateDef]   Max chars: {debate_max_chars}")
        print(f"[DebateDef]   Lang: {_lang}")

        all_texts = {'propose': propose_text, 'oppose': oppose_text, 'decide': decide_text}
        for role, text in all_texts.items():
            if not text or not text.strip():
                return f"❌ {role}_text is empty. Complete all 3 arguments first."

        os.makedirs(output_dir, exist_ok=True)
        results = []

        for role, raw in all_texts.items():
            orig_chars = len(raw)

            # ── Full version (compressed) ──
            cleaned = self._clean_debate_text(raw, debate_max_chars)
            cleaned_chars = len(cleaned)
            reduction = orig_chars - cleaned_chars

            md_path = _md_paths[role]
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            print(f"[DebateDef] 📝 Saved: {md_path} ({cleaned_chars} chars)")

            # ── Mobile version (FULL content - NO compression) ──
            mobile = self._make_mobile(raw)
            mobile_path = _mobile_paths[role]
            with open(mobile_path, 'w', encoding='utf-8') as f:
                f.write(mobile)
            print(f"[DebateDef] 📱 Saved: {mobile_path} ({len(mobile)} chars)")

            results.append({'type': role, 'original': orig_chars, 'cleaned': cleaned_chars, 'mobile': len(mobile), 'reduction': reduction})

        elapsed = time.time() - t0
        summary = f"✅ Debate files generated in {elapsed:.1f}s\n\n"
        for r in results:
            summary += f"✓ {r['type'].upper()}: {r['original']} → {r['cleaned']} chars (saved {r['reduction']}) | 📱 {r['mobile']} chars\n"
        summary += f"\nFiles: {output_dir}/\n"
        summary += f"  Full  : propose_{_lang}.md  oppose_{_lang}.md  decide_{_lang}.md\n"
        summary += f"  Mobile: propose-m.md  oppose-m.md  decide-m.md\n"
        summary += f"→ ready for debate_video_tool"

        print(f"\n[DebateDef] ✅ Complete in {elapsed:.1f}s")
        return summary

    def _clean_debate_text(self, text: str, max_chars: int = 5000) -> str:
        """Compress for full/HD version only."""
        text = self._apply_abbreviations(text)
        text = self._remove_aux_and_articles(text)
        text = self._collapse_whitespace(text)
        text = self._hard_cap(text, max_chars)
        return text

    def _make_mobile(self, text: str) -> str:
        """✅ Mobile version - ZERO compression, full content preserved."""
        return text.strip()  # Nothing else!

    def _apply_abbreviations(self, text: str) -> str:
        """Headers + word abbreviations for full version only."""
        # Headers
        text = re.sub(r'\bCOUNTER[\s\-]?ARGUMENT\s*(\d+)\s*[:\-]?', r'C-Arg \1:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bARGUMENT\s*(\d+)\s*[:\-]?', r'ARG \1:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bOPENING\s+STATEMENT\s*[:\-]?', 'Opening:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bCONCLUSION\s*[:\-]?', 'Concl:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bPROPOSITION\s*[:\-]?', 'Prop:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bOPPOSITION\s*[:\-]?', 'Opp:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bANALYSIS\s*[:\-]?', 'Anal:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bDECISION\s*[:\-]?', 'Decis:', text, flags=re.IGNORECASE)
        text = re.sub(r'\bVERDICT\s*[:\-]?', 'Verdict:', text, flags=re.IGNORECASE)

        # Common words
        text = re.sub(r'\band\b', ' &', text, flags=re.IGNORECASE)
        text = re.sub(r'\bwith\b', 'w/', text, flags=re.IGNORECASE)
        text = re.sub(r'\bwithout\b', 'w/o', text, flags=re.IGNORECASE)
        text = re.sub(r'\bbecause\b', 'b/c', text, flags=re.IGNORECASE)
        text = re.sub(r'\btherefore\b', '→', text, flags=re.IGNORECASE)

        # Word abbreviations
        word_abbrevs = [
            (r'\bunderstanding\b', 'grasp'), (r'\bintelligence\b', 'intellect'),
            (r'\bcapabilities\b', 'ability'), (r'\balgorithm\b', 'algo'),
            (r'\balgorithms\b', 'algos'), (r'\bsignificant\b', 'key'),
            (r'\bdevelopment\b', 'dev'), (r'\btechnology\b', 'tech'),
            (r'\binformation\b', 'info'), (r'\bartificial intelligence\b', 'AI'),
            (r'\bmachine learning\b', 'ML'), (r'\bnatural language processing\b', 'NLP'),
        ]
        for pattern, replacement in word_abbrevs:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        return text

    def _remove_aux_and_articles(self, text: str) -> str:
        """Remove aux verbs & articles for full version only."""
        aux_list = [r'\bam\b', r'\bis\b', r'\bare\b', r'\bwas\b', r'\bwere\b',
                    r'\bhave\b', r'\bhas\b', r'\bhad\b', r'\bwill\b', r'\bwould\b',
                    r'\bcan\b', r'\bcould\b', r'\bshould\b', r'\bmust\b']
        for aux in aux_list:
            text = re.sub(aux + r'\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bthe\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\ban\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\ba\s+', '', text, flags=re.IGNORECASE)
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
