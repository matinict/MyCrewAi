"""
Debate Definition Tool (OPTIMIZED v7)
Auto-generates debate files for video factory.

All compression config lives in data/label_mappings.json:
  debate_labels       -> abbreviation map (longest-match first)
  debate_compression  -> aux_strip, article_strip, mobile_caps,
                         hard_cap_ratio, header_prefixes, strip_trailing_to

Smart skip: if all 6 .md files exist, returns immediately.
Full version : compressed to debate_max_chars for HD video.
Mobile version: Shorts-optimised with per-role char caps from JSON.
Triggered by: "debate_definition_enabled": true in data.json
"""
import json
import os
import re
import time
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field


class DebateDefinitionToolInput(BaseModel):
    topic: str = Field(..., description="Full debate topic/motion")
    filename: str = Field(..., description="Base filename slug")
    output_dir: str = Field(..., description="Output subdirectory for debate files")
    propose_text: str = Field(default="", description="Arguments supporting the motion (FOR) — leave empty to read from disk")
    oppose_text: str = Field(default="", description="Arguments against the motion (AGAINST) — leave empty to read from disk")
    decide_text: str = Field(default="", description="Moderator's conclusion/verdict — leave empty to read from disk")
    debate_definition_enabled: bool = Field(default=False, description="Whether to process debate definitions")
    channel: str = Field(default="PlayOwnAi", description="Channel name for branding")
    debate_max_chars: int = Field(default=5000, description="Hard cap on each debate argument in characters")
    lang_suffix: str = Field(default="En", description="Language suffix for output .md filenames")
    use_label_mappings: bool = Field(default=False, description="Apply abbreviation map only to -m.md (Shorts) files")
    force_regenerate: bool = Field(default=False, description="Force rewrite of all .md files even if they already exist (use to fix stale/corrupt files)")


class DebateDefinitionTool(BaseTool):
    name: str = "Debate Definition Tool"
    description: str = (
        "Auto-generates debate files for video factory. "
        "All compression config is driven by data/label_mappings.json."
    )
    args_schema: Type[BaseModel] = DebateDefinitionToolInput

    # ── In-process cache — reloads only if file changes ──────────────────────
    _cfg_cache: dict = {}
    _cfg_mtime: float = 0.0

    @classmethod
    def _find_label_mappings(cls) -> str:
        """Walk up from this file until data/label_mappings.json is found.
        Works regardless of project structure depth (src/, nested packages etc.)."""
        current = os.path.dirname(os.path.abspath(__file__))
        for _ in range(6):  # max 6 levels up
            candidate = os.path.join(current, 'data', 'label_mappings.json')
            if os.path.exists(candidate):
                return candidate
            current = os.path.dirname(current)
        # Final fallback: same dir as this file
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'label_mappings.json')

    @classmethod
    def _load_cfg(cls) -> dict:
        """Load label_mappings.json; reload automatically if file is updated."""
        try:
            path  = cls._find_label_mappings()
            mtime = os.path.getmtime(path)
            if cls._cfg_cache and mtime == cls._cfg_mtime:
                return cls._cfg_cache
            with open(path, 'r', encoding='utf-8') as f:
                cls._cfg_cache = json.load(f)
            cls._cfg_mtime = mtime
            print(f"[DebateDef] Loaded label_mappings from: {path}")
        except Exception as e:
            print(f"[DebateDef] WARNING label_mappings.json not loaded: {e}")
            cls._cfg_cache = {}
        return cls._cfg_cache

    @classmethod
    def _debate_labels(cls) -> list:
        """debate_labels sorted longest-key first (prevents partial matches)."""
        labels = cls._load_cfg().get('debate_labels', {})
        return sorted(labels.items(), key=lambda x: len(x[0]), reverse=True)

    @classmethod
    def _compression(cls) -> dict:
        """debate_compression config block."""
        return cls._load_cfg().get('debate_compression', {})

    # ── Main entry point ──────────────────────────────────────────────────────
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
        use_label_mappings: bool = False,
        force_regenerate: bool = False,
    ) -> str:

        if not debate_definition_enabled:
            return "Debate definition skipped (debate_definition_enabled=false)"

        _lang = lang_suffix or "En"
        _md_paths     = {r: os.path.join(output_dir, f"{r}_{_lang}.md") for r in ('propose', 'oppose', 'decide')}
        _mobile_paths = {r: os.path.join(output_dir, f"{r}-m.md")       for r in ('propose', 'oppose', 'decide')}

        # ── SMART SKIP: all 6 files already exist ────────────────────────────
        _all_exist = all(
            os.path.exists(p) and os.path.getsize(p) > 0
            for p in list(_md_paths.values()) + list(_mobile_paths.values())
        )
        if _all_exist and not force_regenerate and not use_label_mappings:
            _sizes  = {r: os.path.getsize(p) for r, p in _md_paths.items()}
            _msizes = {r: os.path.getsize(p) for r, p in _mobile_paths.items()}
            print(f"[DebateDef] All 6 debate files exist ({_lang}) - skipping")
            lines = [
                f"   OK {r}_{_lang}.md ({_sizes[r]} B)  {r}-m.md ({_msizes[r]} B)"
                for r in ('propose', 'oppose', 'decide')
            ]
            return f"Debate files exist ({_lang}) - skipping\n" + "\n".join(lines)
        if _all_exist and use_label_mappings and not force_regenerate:
            print(f"[DebateDef] use_label_mappings=True — regenerating -m.md files with abbreviations ({_lang})")
        if _all_exist and force_regenerate:
            print(f"[DebateDef] force_regenerate=True — overwriting all 6 files ({_lang})")

        # ── PARTIAL SKIP: track which -m.md files still need writing ─────────
        # When use_label_mappings=True, always regenerate ALL -m.md files so
        # abbreviations are (re-)applied even if old un-mapped files exist.
        if use_label_mappings or force_regenerate:
            _mobile_needed = {'propose', 'oppose', 'decide'}
        else:
            _mobile_needed = {
                r for r in ('propose', 'oppose', 'decide')
                if not (os.path.exists(_mobile_paths[r]) and os.path.getsize(_mobile_paths[r]) > 0)
            }

        t0 = time.time()
        print(f"[DebateDef] Generating debate files  topic={topic}  max={debate_max_chars}  lang={_lang}")

        # ── Load texts — agent-passed or disk fallback ────────────────────────
        all_texts = {
            'propose': self._load_text(propose_text, output_dir, 'propose', _lang),
            'oppose':  self._load_text(oppose_text,  output_dir, 'oppose',  _lang),
            'decide':  self._load_text(decide_text,  output_dir, 'decide',  _lang),
        }
        for role, text in all_texts.items():
            if not text:
                return f"ERROR: {role}_text is empty and no .md found on disk. Complete all 3 arguments first."

        os.makedirs(output_dir, exist_ok=True)

        # ── Mobile caps from JSON ─────────────────────────────────────────────
        cfg_caps    = self._compression().get('mobile_caps', {})
        mobile_caps = {
            'propose': cfg_caps.get('propose', 2000),
            'oppose':  cfg_caps.get('oppose',  2000),
            'decide':  cfg_caps.get('decide',  1000),
        }

        results = []
        for role, raw in all_texts.items():
            orig_chars = len(raw)

            # Full / HD version — abbreviations always OFF for HD
            cleaned = self._clean_debate_text(raw, debate_max_chars, apply_abbrev=False)
            with open(_md_paths[role], 'w', encoding='utf-8') as f:
                f.write(cleaned)
            print(f"[DebateDef] Saved {_md_paths[role]} ({len(cleaned)} chars)")

            # Mobile / Shorts version — abbreviations ON only when use_label_mappings=True
            mobile_len = 0
            if role in _mobile_needed:
                mobile = self._make_mobile(raw, mobile_caps[role], apply_abbrev=use_label_mappings)
                with open(_mobile_paths[role], 'w', encoding='utf-8') as f:
                    f.write(mobile)
                mobile_len = len(mobile)
                print(f"[DebateDef] Saved {_mobile_paths[role]} ({mobile_len} chars)")
            else:
                mobile_len = os.path.getsize(_mobile_paths[role])
                print(f"[DebateDef] Skip {role}-m.md (exists, {mobile_len} B)")

            results.append({
                'role': role, 'original': orig_chars,
                'cleaned': len(cleaned), 'mobile': mobile_len,
            })

        elapsed = time.time() - t0
        summary  = f"Debate files generated in {elapsed:.1f}s\n\n"
        for r in results:
            saved = r['original'] - r['cleaned']
            summary += f"{r['role'].upper()}: {r['original']} -> {r['cleaned']} chars (saved {saved}) | mobile {r['mobile']} chars\n"
        summary += (
            f"\nFiles: {output_dir}/\n"
            f"  Full  : propose_{_lang}.md  oppose_{_lang}.md  decide_{_lang}.md\n"
            f"  Mobile: propose-m.md  oppose-m.md  decide-m.md\n"
            f"-> ready for debate_video_tool"
        )
        print(f"[DebateDef] Complete in {elapsed:.1f}s")
        return summary

    # ── Internal helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _load_text(passed: str, output_dir: str, role: str, lang: str) -> str:
        """Return passed text if non-empty, else read from disk (lang-suffixed then plain fallback)."""
        if passed and passed.strip():
            return passed.strip()
        for path in (
            os.path.join(output_dir, f'{role}_{lang}.md'),
            os.path.join(output_dir, f'{role}.md'),
        ):
            if os.path.exists(path) and os.path.getsize(path) > 0:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
        return ''

    def _clean_debate_text(self, text: str, max_chars: int = 5000, apply_abbrev: bool = False) -> str:
        """Full/HD compression: pre-clean artifacts -> optionally abbreviate -> strip aux -> collapse -> hard cap.
        apply_abbrev is always False for HD — full names are preserved."""
        text = self._pre_clean(text)
        if apply_abbrev:
            text = self._apply_abbreviations(text)
        text = self._strip_aux_and_articles(text)
        text = self._collapse_whitespace(text)
        return self._hard_cap(text, max_chars)

    def _make_mobile(self, text: str, max_chars: int = 2000, apply_abbrev: bool = False) -> str:
        """Shorts compression: keep ALL args, word-safe + logic-safe trim.
        apply_abbrev=True only when use_label_mappings=True in data.json."""
        # max_chars is driven by mobile_caps from label_mappings.json — do NOT hardcode here
        text = self._pre_clean(text)
        if apply_abbrev:
            text = self._apply_abbreviations(text)
        text = self._strip_aux_and_articles(text)
        text = self._collapse_whitespace(text)
        if len(text) <= max_chars:
            return text
        # Split blocks (Opening, Arg1, Arg2, ...)
        blocks = re.split(r'\n{2,}', text)
        n = len(blocks)
        if n == 0:
            return self._clean_tail(text[:max_chars])

        per_block = max_chars // n
        new_blocks = []
        for blk in blocks:
            blk = blk.strip()
            if len(blk) <= per_block:
                new_blocks.append(blk)
                continue
            # ✅ WORD-SAFE TRIM (no broken words)
            words = blk.split()
            trimmed_words = []
            for w in words:
                test = " ".join(trimmed_words + [w])
                if len(test) > per_block:
                    break
                trimmed_words.append(w)
            trimmed = " ".join(trimmed_words)
            # ✅ LOGIC-SAFE TAIL CLEAN (no dangling fragments or orphan words)
            trimmed = self._clean_tail(trimmed, min_words=3)
            new_blocks.append(trimmed)
        result = "\n\n".join(new_blocks)
        # ✅ FINAL HARD LIMIT (safe)
        if len(result) > max_chars:
            result = self._clean_tail(result[:max_chars], min_words=3)
        return result
    def _clean_tail(self, text: str, min_words: int = 3) -> str:
        """
        Remove orphan trailing fragments after the last clean sentence boundary.
        1. Strip trailing punctuation noise (, ; : - and whitespace)
        2. Snap to last . ! ? if result keeps ≥55% of text and ≥ min_words
        3. Strip trailing ≤2-word orphan after last comma/semicolon
        4. Return as-is if nothing safe to cut
        """
        # 1. Strip trailing punctuation noise
        text = re.sub(r'[\s,;:\-]+$', '', text)
        # 2. Snap to last sentence boundary
        for m in reversed(list(re.finditer(r'[.!?]', text))):
            candidate = text[:m.end()].strip()
            if len(candidate.split()) >= min_words and len(candidate) >= len(text) * 0.55:
                return candidate
        # 3. Strip trailing ≤2-word orphan after last comma/semicolon
        m2 = re.search(r'[,;]\s*\S+(\s+\S+)?\s*$', text)
        if m2:
            candidate = text[:m2.start()].strip()
            if len(candidate.split()) >= min_words:
                return candidate
        return text

    @classmethod
    def _regex_patterns(cls) -> list:
        """All regex patterns from label_mappings.json -> debate_regex_patterns.
        Returns flat list of [pattern, replacement] pairs in declared order."""
        cfg = cls._load_cfg().get('debate_regex_patterns', {})
        patterns = []
        for key, pairs in cfg.items():
            if key.startswith('_'):
                continue
            patterns.extend(pairs)
        return patterns

    @staticmethod
    def _pre_clean(text: str) -> str:
        """Strip known artifact patterns that should NEVER reach the label map.
        Runs before _apply_abbreviations on every input text.
        - (None–None), (None-None), (–), standalone None tokens
        - Stray bare parentheses left after prior cleanups
        """
        # Remove date-range placeholders like "(None–None)" or "(2020–None)"
        text = re.sub(r'\(\s*(?:None|[0-9]{4})\s*[–\-]\s*(?:None|[0-9]{4})\s*\)\s*', '', text)
        # Remove "(–)" or "( – )" standalone
        text = re.sub(r'\(\s*[–\-]\s*\)\s*', '', text)
        # Remove bare "None" tokens (whole word only, not inside other words)
        text = re.sub(r'\bNone\b\s*', '', text)
        # Remove stray bare parens left over (single unmatched)
        text = re.sub(r'(?<!\w)\((?!\S)', '', text)
        text = re.sub(r'(?<!\S)\)(?!\w)', '', text)
        return text

    def _apply_abbreviations(self, text: str) -> str:
        """Apply abbreviations from label_mappings.json.

        Pass 1 — HEADER labels (all-caps or Title Case keys, multi-word first):
            Matched with re.IGNORECASE=False on ALL-CAPS keys so 'OPENING STATEMENT'→'Opening'
            does NOT then get re-matched by the lowercase 'opening'→'start' entry.

        Pass 2 — BODY labels (single-word, lowercase keys):
            Applied with word-boundary matching, IGNORECASE=True.

        Pass 3 — Regex patterns from debate_regex_patterns.
        """
        labels = self._debate_labels()  # sorted longest-key first

        # Split into header keys (contain uppercase) vs body keys (all lowercase)
        # Header keys: any key that has at least one uppercase letter → exact case match
        # Body keys: all-lowercase keys → word-boundary + IGNORECASE
        header_keys = [(s, d) for s, d in labels if s != s.lower()]
        body_keys   = [(s, d) for s, d in labels if s == s.lower()]

        # Pass 1: headers — exact case (no IGNORECASE) to prevent downstream chaining
        for src, dst in header_keys:
            if ' ' in src or '-' in src:
                text = re.sub(re.escape(src), dst, text)   # ← no IGNORECASE
            else:
                text = re.sub(r'\b' + re.escape(src) + r'\b', dst, text)  # no IGNORECASE

        # Pass 2: body — IGNORECASE, word-boundary safe
        for src, dst in body_keys:
            if ' ' in src or '-' in src:
                text = re.sub(re.escape(src), dst, text, flags=re.IGNORECASE)
            else:
                text = re.sub(r'\b' + re.escape(src) + r'\b', dst, text, flags=re.IGNORECASE)

        # Pass 3: regex patterns with capture groups
        for pattern, replacement in self._regex_patterns():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        return text

    def _strip_aux_and_articles(self, text: str) -> str:
        """Remove aux verbs and articles — all lists from label_mappings.json
        debate_compression.aux_strip and article_strip."""
        cfg = self._compression()

        for word in cfg.get('aux_strip', []):
            text = re.sub(r'\b' + re.escape(word) + r'\b\s+', '', text, flags=re.IGNORECASE)

        for word in cfg.get('article_strip', []):
            text = re.sub(r'\b' + re.escape(word) + r'\b\s+', '', text, flags=re.IGNORECASE)

        return text

    def _collapse_whitespace(self, text: str) -> str:
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _hard_cap(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        ratio = self._compression().get('hard_cap_ratio', 0.67)
        cap   = text[:max_chars]
        cut   = max(cap.rfind('.'), cap.rfind('\n'))
        if cut > int(max_chars * ratio):
            return cap[:cut + 1].strip()
        return cap.strip()

    def _smart_trim(self, text: str, max_chars: int) -> str:
        """Iteratively drop trailing sentences from the longest non-header block.
        Header prefixes loaded from label_mappings.json -> debate_compression.header_prefixes."""
        prefixes = self._compression().get('header_prefixes', [
            'Prop', 'Opp', 'Arg', 'C-Arg', 'Opening', 'Closing',
            'Concl', 'Sum Of', 'Anal', 'Decis', 'Verd',
        ])
        hdr = re.compile(
            r'^(' + '|'.join(re.escape(p) for p in prefixes) + r')',
            re.IGNORECASE
        )

        blocks = re.split(r'(\n{2,})', text)
        pairs  = []
        i = 0
        while i < len(blocks):
            blk = blocks[i]
            sep = blocks[i + 1] if i + 1 < len(blocks) and not blocks[i + 1].strip() else '\n'
            pairs.append([blk, sep])
            i += 2 if (i + 1 < len(blocks) and not blocks[i + 1].strip()) else 1

        def joined(p):
            return ''.join(b + s for b, s in p).strip()

        for _ in range(200):
            if len(joined(pairs)) <= max_chars:
                break
            li, ll = -1, 0
            for idx, (blk, _s) in enumerate(pairs):
                if not hdr.match(blk.strip()) and len(blk) > ll:
                    ll, li = len(blk), idx
            if li == -1:
                break
            nb = re.sub(r'[^.!?\n]*[.!?]["\']?\s*$', '', pairs[li][0], flags=re.DOTALL).strip()
            if nb == pairs[li][0] or not nb:
                pairs.pop(li)
            else:
                pairs[li][0] = nb

        return self._hard_cap(joined(pairs), max_chars)
