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

        _md_paths     = {role: os.path.join(output_dir, f"{role}_{_lang}.md") for role in ('propose', 'oppose', 'decide')}
        _mobile_paths = {role: os.path.join(output_dir, f"{role}-m.md")         for role in ('propose', 'oppose', 'decide')}

        # ── SMART SKIP: all 6 files already exist → nothing to do ──────────
        _all_exist = all(
            os.path.exists(p) and os.path.getsize(p) > 0
            for p in list(_md_paths.values()) + list(_mobile_paths.values())
        )
        if _all_exist:
            _sizes  = {role: os.path.getsize(p) for role, p in _md_paths.items()}
            _msizes = {role: os.path.getsize(p) for role, p in _mobile_paths.items()}
            print(f"[DebateDef] ⭐️ All 6 debate files exist ({_lang}) — skipping")
            lines = [f"   ✓ {role}_{_lang}.md ({_sizes[role]} B)  {role}-m.md ({_msizes[role]} B)" for role in ('propose', 'oppose', 'decide')]
            return f"⭐️ Debate files exist ({_lang}) — skipping\n" + "\n".join(lines)

        # ── PARTIAL SKIP: track which -m.md files still need writing ────────
        _mobile_needed = {
            role for role in ('propose', 'oppose', 'decide')
            if not (os.path.exists(_mobile_paths[role]) and os.path.getsize(_mobile_paths[role]) > 0)
        }
        if not _mobile_needed:
            print(f"[DebateDef] ⭐️ All -m.md files already exist — skipping mobile generation")

        t0 = time.time()
        print(f"\n[DebateDef] ▶ Generating debate files")
        print(f"[DebateDef]   Topic: {topic}")
        print(f"[DebateDef]   Max chars: {debate_max_chars}")
        print(f"[DebateDef]   Lang: {_lang}")

        # ── Fallback: read from disk if agent didn't pass text in ──────────
        # CrewAI output_file writes propose/oppose/decide .md directly;
        # the agent may pass empty strings. Read from disk as fallback.
        _disk_paths = {
            'propose': (
                os.path.join(output_dir, f'propose_{_lang}.md'),
                os.path.join(output_dir, 'propose.md'),
            ),
            'oppose': (
                os.path.join(output_dir, f'oppose_{_lang}.md'),
                os.path.join(output_dir, 'oppose.md'),
            ),
            'decide': (
                os.path.join(output_dir, f'decide_{_lang}.md'),
                os.path.join(output_dir, 'decide.md'),
            ),
        }

        def _load(passed_text, paths):
            if passed_text and passed_text.strip():
                return passed_text.strip()
            for p in paths:
                if os.path.exists(p) and os.path.getsize(p) > 0:
                    with open(p, 'r', encoding='utf-8') as f:
                        return f.read().strip()
            return ''

        all_texts = {
            'propose': _load(propose_text, _disk_paths['propose']),
            'oppose':  _load(oppose_text,  _disk_paths['oppose']),
            'decide':  _load(decide_text,  _disk_paths['decide']),
        }
        for role, text in all_texts.items():
            if not text:
                return f"❌ {role}_text is empty and no .md file found on disk. Complete all 3 arguments first."

        os.makedirs(output_dir, exist_ok=True)
        results = []

        _mobile_caps = {'propose': 2000, 'oppose': 2000, 'decide': 1000}

        for role, raw in all_texts.items():
            orig_chars = len(raw)

            # ── Full version (compressed to debate_max_chars) ──
            cleaned = self._clean_debate_text(raw, debate_max_chars)
            cleaned_chars = len(cleaned)
            reduction = orig_chars - cleaned_chars

            md_path = _md_paths[role]
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            print(f"[DebateDef] 📝 Saved: {md_path} ({cleaned_chars} chars)")

            # ── Mobile version (Shorts-optimised, per-role char cap) ──
            mobile_len = 0
            if role in _mobile_needed:
                mobile = self._make_mobile(raw, _mobile_caps.get(role, 2000))
                mobile_path = _mobile_paths[role]
                with open(mobile_path, 'w', encoding='utf-8') as f:
                    f.write(mobile)
                mobile_len = len(mobile)
                print(f"[DebateDef] 📱 Saved: {mobile_path} ({mobile_len} chars)")
            else:
                mobile_len = os.path.getsize(_mobile_paths[role])
                print(f"[DebateDef] ⭐️ Skip {role}-m.md (already exists, {mobile_len} B)")

            results.append({'type': role, 'original': orig_chars, 'cleaned': cleaned_chars, 'mobile': mobile_len, 'reduction': reduction})

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

    def _make_mobile(self, text: str, max_chars: int = 2000) -> str:
        """Shorts-optimised compression: abbreviate + strip aux + smart trim."""
        text = self._apply_abbreviations(text)
        text = self._remove_aux_and_articles(text)
        text = self._collapse_whitespace(text)
        if len(text) <= max_chars:
            return text
        return self._smart_trim(text, max_chars)

    def _smart_trim(self, text: str, max_chars: int) -> str:
        """Drop trailing sentences from longest block iteratively.
        Preserves all headers & opening sentences — only trims tail content."""
        blocks = re.split(r'(\n{2,})', text)
        pairs = []
        i = 0
        while i < len(blocks):
            blk = blocks[i]
            sep = blocks[i + 1] if i + 1 < len(blocks) and not blocks[i + 1].strip() else '\n'
            pairs.append([blk, sep])
            i += 2 if (i + 1 < len(blocks) and not blocks[i + 1].strip()) else 1

        hdr = re.compile(
            r'^(Prop|Opp|ARG|C-Arg|Opening|Closing|Concl|Sum Of|Anal\.|Decis\.|Verdict)',
            re.IGNORECASE
        )

        def joined(p):
            return ''.join(b + s for b, s in p).strip()

        for _ in range(200):
            if len(joined(pairs)) <= max_chars:
                break
            li, ll = -1, 0
            for idx, (blk, _s) in enumerate(pairs):
                if not hdr.match(blk.strip()) and len(blk) > ll:
                    ll = len(blk)
                    li = idx
            if li == -1:
                break
            nb = re.sub(r'[^.!?\n]*[.!?]["\']?\s*$', '', pairs[li][0], flags=re.DOTALL).strip()
            if nb == pairs[li][0] or not nb:
                pairs.pop(li)
            else:
                pairs[li][0] = nb

        return self._hard_cap(joined(pairs), max_chars)

    def post_process_from_disk(self, output_dir: str, lang_suffix: str = "En") -> str:
        """Fallback: read existing propose/oppose/decide .md files from disk
        and write compressed -m.md versions. Called by main.py after kickoff
        when debate files were written by CrewAI output_file (not this tool).
        Mobile caps: propose=2000, oppose=2000, decide=1000 chars."""
        _mobile_caps = {'propose': 2000, 'oppose': 2000, 'decide': 1000}
        results = []
        for role, cap in _mobile_caps.items():
            # Accept both lang-suffixed and plain filenames
            src = os.path.join(output_dir, f'{role}_{lang_suffix}.md')
            if not (os.path.exists(src) and os.path.getsize(src) > 0):
                src = os.path.join(output_dir, f'{role}.md')
            dst = os.path.join(output_dir, f'{role}-m.md')
            if os.path.exists(src) and os.path.getsize(src) > 0:
                with open(src, 'r', encoding='utf-8') as f:
                    raw = f.read()
                mob = self._make_mobile(raw, cap)
                with open(dst, 'w', encoding='utf-8') as f:
                    f.write(mob)
                print(f"[DebateMobile] 📱 {role}-m.md  {len(mob)} chars  (cap={cap})")
                results.append(f"✓ {role}-m.md ({len(mob)} chars)")
            else:
                print(f"[DebateMobile] ⚠️  {src} not found — skipping {role}-m.md")
                results.append(f"⚠️  {role}-m.md skipped (source not found)")
        return "\n".join(results)

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

        # Common words / symbols
        text = re.sub(r'\band\b',       '&',   text, flags=re.IGNORECASE)
        text = re.sub(r'\bwith\b',      'w/',  text, flags=re.IGNORECASE)
        text = re.sub(r'\bwithout\b',   'w/o', text, flags=re.IGNORECASE)
        text = re.sub(r'\bbecause\b',   'b/c', text, flags=re.IGNORECASE)
        text = re.sub(r'\btherefore\b', '→',   text, flags=re.IGNORECASE)
        text = re.sub(r'\bthrough\b',   'thru',text, flags=re.IGNORECASE)

        # Phrase substitutions
        for src, dst in [
            ('For instance, ', ''), ('For example, ', ''), ('thereby ', ''),
            ('rather than', 'not'), ('In conclusion', 'Concl.'), ('In summary', 'In sum'),
            ('highlights', 'shows'), ('emphasizes', 'stresses'),
            ('invaluable', 'key'), ('crucial', 'key'), ('essential', 'vital'),
        ]:
            text = text.replace(src, dst)

        # Word abbreviations
        word_abbrevs = [
            (r'\bcapabilities\b',  'ability'),  (r'\binformation\b',   'info'),
            (r'\bdevelopment\b',   'dev'),       (r'\bmanagement\b',    'mgmt'),
            (r'\btechnology\b',    'tech'),      (r'\btechnologies\b',  'tech'),
            (r'\bartificial intelligence\b', 'AI'),
            (r'\bmachine learning\b',        'ML'),
            (r'\bnatural language processing\b', 'NLP'),
            (r'\balgorithm\b',     'algo'),      (r'\balgorithms\b',    'algos'),
            (r'\bdemonstrates\b',  'shows'),     (r'\bdemonstrate\b',   'show'),
            (r'\bsignificant\b',   'key'),       (r'\bimportant\b',     'key'),
            (r'\bunderstanding\b', 'grasp'),     (r'\bintelligence\b',  'intellect'),
            (r'\bintelligent\b',   'smart'),     (r'\bprofessional\b',  'prof'),
            (r'\borganizations\b', 'orgs'),      (r'\borganization\b',  'org'),
        ]
        for pattern, replacement in word_abbrevs:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # Strip markdown-style bracketed placeholders
        text = re.sub(r'\[.*?\]', '', text)

        return text

    def _remove_aux_and_articles(self, text: str) -> str:
        """Remove aux verbs & articles for full version only."""
        aux_list = [
            r'\bam\b',    r'\bis\b',    r'\bare\b',   r'\bwas\b',   r'\bwere\b',
            r'\bbe\b',    r'\bbeing\b', r'\bbeen\b',
            r'\bhave\b',  r'\bhas\b',   r'\bhad\b',
            r'\bdo\b',    r'\bdoes\b',  r'\bdid\b',
            r'\bshall\b', r'\bshould\b',r'\bwill\b',  r'\bwould\b',
            r'\bmay\b',   r'\bmight\b', r'\bmust\b',
            r'\bcan\b',   r'\bcould\b', r'\bought\b',
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
