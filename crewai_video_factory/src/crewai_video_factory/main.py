#!/usr/bin/env python
"""
🔥 ONE-COMMAND VIDEO FACTORY 🔥
Usage via CrewAI CLI:
crewai run
Or directly:
python main.py
crewai run          # English — loads input/data.json
crewai run -bn      # Bengali — loads input/dataBn.json
crewai run -fr      # French  — loads input/dataFr.json
crewai run -ar      # Arabic  — loads input/dataAr.json
Configuration: Edit input/data.json to customize settings
"""
import os
import sys
import json
import re
import warnings
import logging
from crewai_video_factory.crew import CrewaiVideoFactory
# Silence Pydantic warnings
warnings.filterwarnings("ignore", message=".*skip_file_prefixes.*")
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic.*")
# Silence LiteLLM proxy server import errors (fastapi/uvicorn not needed for client use)
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", message=".*fastapi.*")
warnings.filterwarnings("ignore", message=".*litellm.*proxy.*")
import os
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"  # prevents proxy server import
def load_config():
    """Load configuration from input/data.json, with optional override file.

    Override file specified via INPUT_CONFIG env var:
        INPUT_CONFIG=input/dataBn.json crewai run

    Override keys are merged on top of data.json — only specify what changes.
    """
    base_path     = "input/data.json"
    override_path = os.environ.get("INPUT_CONFIG", "").strip()

    if not os.path.exists(base_path):
        print("❌ Configuration file not found: input/data.json")
        print("📝 Please create input/data.json with your settings")
        print("📖 See input/data.schema.json for available options")
        example_config = {
            "topic": "Programming Language",
            "start": 2015,
            "end": 2026,
            "granularity": "yearly",
            "animation_styles": ["bar_race"],
            "video_formats": ["Shorts"],
            "fps": 0.5,
            "use_existing_csv": False,
            "video_enabled": True,
            "bar_race_video_enabled": False,
            "audio_enabled": True,
            "audio_speed": 0.9,
            "merge_audio_video": True,
            "generate_youtube_metadata": True
        }
        os.makedirs("input", exist_ok=True)
        with open(base_path, 'w') as f:
            json.dump(example_config, f, indent=2)
        print(f"✅ Created example config at: {base_path}")
        print("⚠️  Please edit it and run again")
        sys.exit(1)

    try:
        with open(base_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # ── Apply override file if specified ──────────────────────────────
        if override_path:
            if not os.path.exists(override_path):
                print(f"❌ INPUT_CONFIG file not found: {override_path}")
                sys.exit(1)
            with open(override_path, 'r', encoding='utf-8') as f:
                overrides = json.load(f)
            # Deep-merge nested *_config blocks; shallow-merge everything else
            for k, v in overrides.items():
                if k.startswith('_'):
                    continue  # skip comment keys
                if isinstance(v, dict) and isinstance(config.get(k), dict):
                    config[k] = {**config[k], **v}
                else:
                    config[k] = v
            print(f"✅ Override applied: {override_path}  "
                  f"({len([k for k in overrides if not k.startswith('_')])} keys)")
        else:
            print(f"📄 Config: {base_path}")

        # ── Parent-switch-aware flattening ────────────────────────────────
        # When switch=true  → hoist all nested block keys to top level
        # When switch=false → force master flag to False, discard nested content
        _block_map = [
            ("animation",     "animation_config",     "bar_race_video_enabled"),
            ("debate",        "debate_config",        "debate_video_enabled"),
            ("metadata_prep", "metadata_prep_config", "generate_youtube_metadata"),
            ("publisher",     "publisher_config",     "upload_youtube_video"),
            ("social",        "social_config",        "social_share_enabled"),

        ]
        for _switch, _block, _flag in _block_map:
            _nested = config.pop(_block, None)
            if config.get(_switch, False):
                if isinstance(_nested, dict):
                    # metadata_prep: rename video_formats → metadata_video_formats to avoid
                    # overwriting the main pipeline video_formats
                    if _switch == 'metadata_prep' and 'video_formats' in _nested:
                        _nested['metadata_video_formats'] = _nested.pop('video_formats')
                    config.update(_nested)
            else:
                config[_flag] = False  # guarantee gate flag is off

        # ── Alias publisher_config lang keys → internal names ─────────────
        # upload_cc_lang  → upload_cc_limit  (caps CC files uploaded to YouTube)
        # upload_md_lang  → upload_md_limit  (caps MD localizations uploaded to YouTube)
        # NOTE: yt_cc_lang / yt_metadata_lang are set by metadata_prep_config separately
        #       and control how many files are GENERATED — independent of upload limits
        if 'upload_cc_lang' in config:
            config.setdefault('upload_cc_limit', int(config['upload_cc_lang']))
        if 'upload_md_lang' in config:
            config.setdefault('upload_md_limit', int(config['upload_md_lang']))
        if 'upload_dry_run' in config:
            config.setdefault('upload_dry_run', bool(config['upload_dry_run']))

        # Map engine-specific voices → tts_voices so debate_video_tool receives them.
        _engine = config.get('tts_engine', 'gtts').strip().lower()
        _is_debate = config.get('debate', False)
        if _is_debate:
            if _engine == 'piper' and config.get('piper_voices'):
                config['tts_voices'] = config['piper_voices']
            elif _engine == 'edge-tts' and config.get('edge_tts_voices'):
                config['tts_voices'] = config['edge_tts_voices']

        # ── Safe defaults for ALL tasks.yaml template variables ─────────
        # CrewAI interpolates {placeholders} in ALL task descriptions at
        # kickoff — even tasks not in final_tasks. Any missing key raises
        # a ValueError. Set harmless defaults here so interpolation never fails.
        _task_defaults = {
            # animation_config
            'animation_styles':           [],
            'use_existing_csv':           False,
            'definition_enabled':         False,
            'use_existing_definition':    False,
            'definition_max_chars':       1500,
            'definition_video':           False,
            'intro_enabled':              False,
            'intro_duration':             7,
            'intro_duration_hd':          10,
            'bar_race_video_enabled':     False,
            'bar_merge_enabled':          False,
            'video_enabled':              False,
            'audio_enabled':              False,
            'audio_speed':                1.0,
            'audio_speed_hd':             1.0,
            'merge_audio_video':          False,
            'bar_race_audio_enabled':     False,
            # metadata_prep_config
            'generate_youtube_metadata':  False,
            'generate_yt_thumbnail':      False,  # generate_yt_thumbnail from metadata_prep_config
            'yt_metadata_lang':           35,
            'yt_cc_lang':                 20,
            'metadata_video_formats':     [],   # video_formats from metadata_prep_config
            '_metadata_video_formats':    [],   # resolved at run() — passed to task
            'animation_video_formats':    [],   # = main video_formats, used by metadata tool for animation branch
            # publisher_config
            'upload_youtube_video':       False,
            'upload_privacy':             'private',
            'upload_category_id':         '28',
            'upload_cc':                  False,
            'upload_cc_limit':            0,
            'upload_md_limit':            0,
            'upload_dry_run':             False,
            'upload_notify_subscribers':  False,
            'upload_client_secrets_file': 'client_secrets.json',
            'upload_token_file':          'token.json',
            # social_config
            'social_share_enabled':       False,
            'social_share_dry_run':       False,
            'social_platforms':           [],
            # watermark / branding
            'watermark_enabled':          False,
            'watermark_text':             '',
            'watermark_opacity':          60,
            # core fields with safe defaults
            'video_formats':              ['Shorts'],
            'fps_hd_offset':              1.0,
            'audio_speed':                1.0,
            'audio_speed_hd':             1.0,
            'tts_engine':                 'gtts',    # 'gtts' or 'edge-tts'
            'channel_lower':              '',
            'website':                    '',
            'use_label_mappings':         False,
            # debate_config
            'debate_definition_enabled':  False,
            'debate_video_enabled':       False,
            'debate_secs_per_line':       3.5,
            'debate_max_chars':           10000,
            'debate_merge_enabled':       False,      # ✅ ADDED
            'debate_bg_opacity':          255,
            'tts_voices':                 {},
            'intro_context':              'bar_race',  # bar_race | debate | definition
            'intro_slug':                 '',          # custom narration line 2
            # computed at run() — must exist for tasks.yaml interpolation
            'topic_slug':                 '',
            'filename':                   '',
            'output_dir':                 '',
            'fmt':                        'HD',
            'lang_suffix':                'En',
            'start':                      None,
            'end':                        None,
        }
        for k, v in _task_defaults.items():
            config.setdefault(k, v)

        return config

    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in {base_path}: {e}")
        print("💡 Check syntax at https://jsonlint.com/")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        sys.exit(1)

# ── Lang flag: crewai run -bn  →  INPUT_CONFIG=input/dataBn.json ─────────
# Scans sys.argv for -xx flags (2-letter ISO code). Sets INPUT_CONFIG env var
# so load_config() picks it up. Default (no flag) = input/data.json (English).
_lang_flag = next((a for a in sys.argv[1:] if re.match(r'^-[a-z]{2}$', a)), None)
if _lang_flag:
    _lang_code   = _lang_flag[1:]          # e.g. "bn"
    _config_file = f"input/data{_lang_code.upper()}.json"   # e.g. input/dataBN.json
    # Also try camelCase: dataBn.json
    import glob as _glob
    _candidates = _glob.glob(f"input/data{_lang_code}*.json", ) +                   _glob.glob(f"input/data{_lang_code.upper()}*.json")
    _candidates = [c for c in _candidates if c != "input/data.json"]
    if _candidates:
        _config_file = sorted(_candidates)[0]
    os.environ["INPUT_CONFIG"] = _config_file
    print(f"🌐 Lang flag: {_lang_flag}  →  {_config_file}")
    # Remove flag from argv so crewai doesn't choke on it
    sys.argv = [a for a in sys.argv if a != _lang_flag]

_LANG_SUFFIX = _lang_flag[1:].capitalize() if _lang_flag else "En"  # e.g. "Bn", "Fr", "En"

# Load configuration from input/data.json (+ optional INPUT_CONFIG override)
DEFAULT_INPUTS = load_config()

def run():
    inputs = DEFAULT_INPUTS.copy()
    inputs['lang_suffix'] = _LANG_SUFFIX   # e.g. "En" | "Bn" | "Fr"

    # Parse CLI arguments (override input/data.json if provided)
    if len(sys.argv) > 1:
        try:
            custom_inputs = json.loads(sys.argv[1])
            inputs.update(custom_inputs)
            print("✅ CLI arguments override applied")
        except json.JSONDecodeError:
            pass  # not JSON — already handled as lang flag above

    # Generate filename from topic
    words = re.findall(r'\w+', inputs['topic'])[:3]
    inputs['filename'] = ''.join(words)
    inputs['original_topic'] = inputs['topic']

    # 🔑 KEY: Set output_dir for ALL tools (topic subdirectory)
    output_dir = f"output/{inputs['filename']}"
    os.makedirs(output_dir, exist_ok=True)
    inputs['output_dir'] = output_dir

    # Required by tasks.yaml templates — must be set before kickoff
    inputs['topic_slug'] = '_'.join(re.findall(r'\w+', inputs['topic'])[:4])

    # Auto-set intro_context + resolve intro_slug from active pipeline
    if not inputs.get('intro_context') or inputs.get('intro_context') == 'bar_race':
        if inputs.get('debate', False):
            inputs['intro_context'] = 'debate'
        elif inputs.get('animation', False):
            inputs['intro_context'] = 'bar_race'
        else:
            inputs['intro_context'] = 'bar_race'  # safe default

    # intro_slug already flattened from active _config block by _block_map.update()
    # — no extra work needed; setdefault ensures empty string if not in any config
    inputs.setdefault('fmt', 'HD')

    # FPS validation
    fps = float(inputs.get('fps', 0.5))
    if fps < 0.1 or fps > 30.0:
        print(f"⚠️  Invalid FPS {fps}. Clamping to valid range (0.1-30.0)")
        fps = max(0.1, min(30.0, fps))
    inputs['fps'] = fps

    # ===== USE_EXISTING_CSV HANDLING =====
    csv_path = f"output/{inputs['filename']}.csv"
    use_existing = inputs.get('use_existing_csv', False)

    print("\n" + "="*60)
    print("🎬 VIDEO FACTORY STARTING")
    print("="*60)
    print(f"📊 Topic: {inputs['topic']}")
    print(f"📄 CSV File: {csv_path}")
    print(f"📁 Output Subdirectory: {output_dir}/")
    print(f"⏱️  Speed: {fps} seconds per period")

    if not inputs.get('animation', False):
        # Animation is OFF — research & CSV are ONLY needed by animation tasks.
        # debate / metadata_prep / publisher / social never need a CSV.
        # Always skip — regardless of whether a CSV file exists on disk.
        print("⭐️  Animation OFF — research & CSV generation skipped")
        inputs['_skip_research'] = True
        inputs['_skip_csv']      = True
    elif use_existing:
        if not os.path.exists(csv_path):
            print(f"⚠️  use_existing_csv=True but CSV not found at {csv_path}")
            print("🔄 Auto-generating CSV data instead...")
            inputs['_skip_research'] = False
            inputs['_skip_csv'] = False
        else:
            print("⭐️  SKIPPING data research & CSV generation (using existing file)")
            inputs['_skip_research'] = True
            inputs['_skip_csv'] = True
    else:
        print("📊 Researching new data & generating CSV")
        inputs['_skip_research'] = False
        inputs['_skip_csv'] = False

    print(f"📱 Formats: {', '.join(inputs['video_formats'])}")

    # ── Animation block ──────────────────────────────────────
    anim_on = inputs.get('animation', False)
    print(f"🎬 Animation:        {anim_on}")
    if anim_on:
        styles = ', '.join(inputs.get('animation_styles', []) or ['(none)'])
        print(f"   🎨 Styles:          {styles}")
        print(f"   📊 Use Existing CSV:{inputs.get('use_existing_csv', False)}")
        print(f"   📖 Definition:      {inputs.get('definition_enabled', False)}" +
              (f"  [existing={inputs.get('use_existing_definition',False)}, max={inputs.get('definition_max_chars',1500)}ch]"
               if inputs.get('definition_enabled') else ""))
        print(f"   🎞️  Definition Video:{inputs.get('definition_video', False)}")
        print(f"   🎬 Bar Race Video:  {inputs.get('bar_race_video_enabled', False)}")
        print(f"   🎬 Intro Clip:      {inputs.get('intro_enabled', False)}" +
              (f"  [Shorts={inputs.get('intro_duration',7)}s, HD={inputs.get('intro_duration_hd',10)}s]"
               if inputs.get('intro_enabled') else ""))
        print(f"   🔀 Bar Merge:       {inputs.get('bar_merge_enabled', False)}")
        print(f"   🎞️  Video (standard):{inputs.get('video_enabled', False)}")
        print(f"   🔊 Audio:           {inputs.get('audio_enabled', False)}" +
              (f"  [Shorts={inputs.get('audio_speed',1.0)}x, HD={inputs.get('audio_speed_hd',1.0)}x]"
               if inputs.get('audio_enabled') else ""))
        print(f"   📹 Merge Audio+Video:{inputs.get('merge_audio_video', False)}")

    # ── Metadata block ───────────────────────────────────────
    meta_on = inputs.get('metadata_prep', False)
    print(f"📺 Metadata Prep:    {meta_on}")
    if meta_on:
        print(f"   📋 YouTube Metadata:{inputs.get('generate_youtube_metadata', False)}")
        print(f"   🖼️  Thumbnail:       {inputs.get('generate_yt_thumbnail', False)}")
        _meta_fmts = inputs.get('metadata_video_formats') or inputs.get('video_formats', [])
        print(f"   🎬 Meta Formats:    {_meta_fmts}")
        print(f"   🌍 MD langs:        {inputs.get('yt_metadata_lang', 35)} | CC langs: {inputs.get('yt_cc_lang', 20)}")

    # ── Publisher block ──────────────────────────────────────
    pub_on = inputs.get('publisher', False)
    print(f"📤 Publisher:        {pub_on}")
    if pub_on:
        upload_on = inputs.get('upload_youtube_video', False)
        print(f"   ▶️  YouTube Upload:  {upload_on}" +
              (f"  [{inputs.get('upload_privacy','private')}]" if upload_on else ""))

    # ── Social block ─────────────────────────────────────────
    soc_on = inputs.get('social', False)
    print(f"📢 Social Share:     {soc_on}")
    if soc_on:
        plats = ', '.join(inputs.get('social_platforms', []))
        print(f"   🌐 Platforms:       {plats or '(none)'}")
        print(f"   🧪 Dry Run:         {inputs.get('social_share_dry_run', False)}")

    # ── Debate block ─────────────────────────────────────────
    debate_on = inputs.get('debate', False)
    print(f"🗣️  Debate Video:     {debate_on}")
    if debate_on:
        print(f"   ✍️  Debate Text:     {inputs.get('debate_definition_enabled', False)}" +
              (f"  [max={inputs.get('debate_max_chars',10000)}ch]"
               if inputs.get('debate_definition_enabled') else ""))
        _eng = inputs.get('tts_engine', 'gtts')
        print(f"   🎤 TTS Engine:      {_eng}")
        if inputs.get('tts_voices'):
            _v = inputs['tts_voices']
            if _eng == 'piper':
                print(f"   🎙️  PRO voice:  {_v.get('propose', {}).get('model', 'default')}")
                print(f"   🎙️  CON voice:  {_v.get('oppose',  {}).get('model', 'default')}")
                print(f"   🎙️  MOD voice:  {_v.get('decide',  {}).get('model', 'default')}")
            elif _eng == 'edge-tts':
                print(f"   🎙️  PRO voice:  {_v.get('propose', {}).get('edge_voice', 'default')}")
                print(f"   🎙️  CON voice:  {_v.get('oppose',  {}).get('edge_voice', 'default')}")
                print(f"   🎙️  MOD voice:  {_v.get('decide',  {}).get('edge_voice', 'default')}")
        else:
            print(f"   🎙️  Voices:        (engine defaults)")
        print(f"   🎬 Debate Video:    {inputs.get('debate_video_enabled', False)}" +
              (f"  [secs/line={inputs.get('debate_secs_per_line', 3.5)}]"
               if inputs.get('debate_video_enabled') else ""))
        print(f"   🔀 Debate Merge:    {inputs.get('debate_merge_enabled', False)}")

    # ── LLM overrides ────────────────────────────────────────
    llm_keys = ['llm_researcher', 'llm_definition', 'llm_csv', 'llm_video',
                'llm_audio', 'llm_youtube', 'llm_upload', 'llm_social', 'llm_debate']
    llm_overrides = {k: inputs[k] for k in llm_keys
                     if inputs.get(k) and str(inputs[k]).strip().lower() not in ('null','none','')}
    if llm_overrides:
        print("🤖 LLM Overrides:")
        for k, v in llm_overrides.items():
            print(f"   {k}: {v}")
    else:
        print("🤖 LLMs: project default for all agents")

    print("="*60 + "\n")

    try:
        crew_instance = CrewaiVideoFactory()
        full_crew = crew_instance.crew(inputs=inputs)

        # ===== CONDITIONAL TASK EXECUTION =====
        final_tasks = []

        if not inputs.get('_skip_research', False):
            final_tasks.append(full_crew.tasks[0])  # research_data
        if not inputs.get('_skip_csv', False):
            final_tasks.append(full_crew.tasks[1])  # generate_csv
        if inputs.get('video_enabled', True):
            final_tasks.append(full_crew.tasks[4])  # create_video

        # crew.py task index map:
        # [0] research_data           [1] generate_csv             [2] define_topic
        # [3] create_definition_video [4] create_video             [5] create_bar_race_video
        # [6] create_intro_clip       [7] bar_merge                [8] add_audio
        # [9] merge_audio_video       [10] generate_youtube_metadata [11] upload_to_youtube
        # [12] share_to_social
        # [13] debate_propose  [14] debate_oppose  [15] debate_decide
        # [16] create_debate_video    [17] debate_merge

        if inputs.get('bar_race_video_enabled', False):
            final_tasks.append(full_crew.tasks[5])  # create_bar_race_video
        if inputs.get('intro_enabled', False):
            final_tasks.append(full_crew.tasks[6])  # create_intro_clip

        # define_topic runs right after generate_csv (early, so definition is ready)
        if inputs.get('definition_enabled', False):
            definition_txt = f"output/{inputs['filename']}.txt"
            use_existing_def = inputs.get('use_existing_definition', False)
            if use_existing_def and not os.path.exists(definition_txt):
                print(f"⚠️  use_existing_definition=True but .txt not found at {definition_txt}")
                print("🔄 Auto-generating definition instead...")
                use_existing_def = False
                inputs['use_existing_definition'] = False
            if not use_existing_def:
                final_tasks.append(full_crew.tasks[2])  # define_topic

        if inputs.get('audio_enabled', False):
            final_tasks.append(full_crew.tasks[8])  # add_audio
        if inputs.get('definition_video', False):
            final_tasks.append(full_crew.tasks[3])  # create_definition_video

        # bar_merge AFTER definition_video — needs definition_video_with_audio ready
        if inputs.get('bar_merge_enabled', False):
            final_tasks.append(full_crew.tasks[7])  # bar_merge

        # merge_audio_video runs before debate pipeline
        if inputs.get('merge_audio_video', False):
            final_tasks.append(full_crew.tasks[9])  # merge_audio_video

        # ── Debate pipeline ───────────────────────────────────────────────
        # Must run BEFORE generate_youtube_metadata so merged CC files exist
        if inputs.get('debate_definition_enabled', False):
            # Check for existing lang-suffixed debate files
            _debate_dir = output_dir
            _lang = inputs.get('lang_suffix', 'En')
            _propose_exists = os.path.exists(os.path.join(_debate_dir, f'propose_{_lang}.md'))
            _oppose_exists  = os.path.exists(os.path.join(_debate_dir, f'oppose_{_lang}.md'))
            _decide_exists  = os.path.exists(os.path.join(_debate_dir, f'decide_{_lang}.md'))
            # Fallback: check plain .md for backward compat
            if not (_propose_exists and _oppose_exists and _decide_exists):
                _propose_exists = _propose_exists or os.path.exists(os.path.join(_debate_dir, 'propose.md'))
                _oppose_exists  = _oppose_exists  or os.path.exists(os.path.join(_debate_dir, 'oppose.md'))
                _decide_exists  = _decide_exists  or os.path.exists(os.path.join(_debate_dir, 'decide.md'))
            if _propose_exists and _oppose_exists and _decide_exists:
                print(f"⭐️  Debate files exist ({_lang}) — skipping LLM generation (using existing)")
            else:
                final_tasks.append(full_crew.tasks[13])  # debate_propose
                final_tasks.append(full_crew.tasks[14])  # debate_oppose
                final_tasks.append(full_crew.tasks[15])  # debate_decide

        if inputs.get('debate_video_enabled', False):
            final_tasks.append(full_crew.tasks[16])  # create_debate_video

        # ✅ Debate merge AFTER debate video (needs debate_video_with_audio ready)
        if inputs.get('debate_merge_enabled', False):
            final_tasks.append(full_crew.tasks[17])  # debate_merge

        # ── generate_youtube_metadata runs LAST (after all video/merge tasks) ──
        if inputs.get('generate_youtube_metadata', False):
            # Resolve which video_formats the metadata tool should use.
            # metadata_video_formats (from metadata_prep_config.video_formats) takes
            # precedence — "debate" / "animation" tokens drive branching inside the tool.
            # Falls back to main video_formats if not set.
            _meta_fmts = inputs.get('metadata_video_formats') or inputs.get('video_formats', ['HD'])
            inputs['_metadata_video_formats'] = _meta_fmts
            final_tasks.append(full_crew.tasks[10])  # generate_youtube_metadata

        if inputs.get('upload_youtube_video', False):
            final_tasks.append(full_crew.tasks[11])  # upload_to_youtube
        if inputs.get('social_share_enabled', False):
            final_tasks.append(full_crew.tasks[12])  # share_to_social

        if not final_tasks:
            print("❌ ERROR: No tasks to execute. At least one task must be enabled.")
            sys.exit(1)

        full_crew.tasks = final_tasks

        # ── Heartbeat: print progress every 10s while crew runs ──
        import threading, time as _time
        _crew_done = threading.Event()
        _start_ts  = _time.time()

        def _heartbeat():
            step = 0
            spinners = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
            while not _crew_done.is_set():
                _time.sleep(10)
                if not _crew_done.is_set():
                    elapsed = int(_time.time() - _start_ts)
                    spin = spinners[step % len(spinners)]
                    m, s = divmod(elapsed, 60)
                    print(f"  {spin} Agent working ... {m:02d}:{s:02d} elapsed", flush=True)
                    step += 1

        _hb = threading.Thread(target=_heartbeat, daemon=True)
        _hb.start()

        try:
            result = full_crew.kickoff(inputs=inputs)
        finally:
            _crew_done.set()
            _hb.join(timeout=1)

        # Save definition from result.raw (define_topic agent writes pure text, no tool)
        if inputs.get('definition_enabled', False) and not inputs.get('use_existing_definition', False):
            try:
                filename_clean = inputs.get('filename', '')
                # Use __file__ to anchor path — CWD unreliable in crewai
                _main_dir     = os.path.dirname(os.path.abspath(__file__))
                _project_root = os.path.dirname(os.path.dirname(_main_dir))
                _output_root  = os.path.join(_project_root, 'output')
                txt_path      = os.path.join(_output_root, f"{filename_clean}.txt")

                def_text = str(result.raw if hasattr(result, 'raw') else result).strip()
                if def_text and ("WHAT IS" in def_text or "WHY DOES IT MATTER" in def_text):
                    channel = inputs.get('channel', 'PlayOwnAi')
                    start   = inputs.get('start') or None
                    end     = inputs.get('end') or None
                    sep     = "━" * 52
                    _period = f"{start}–{end}" if start and end else (str(start) if start else "")
                    header  = f"{sep}\n📖 TOPIC: {inputs['topic']}\nChannel: @{channel}" + (f"  |  Period: {_period}" if _period else "") + f"\n{sep}\n"
                    footer  = f"\n{sep}\nSubscribe to @{channel} for more data-driven insights.\n{sep}\n"
                    full    = header + def_text + footer

                    os.makedirs(_output_root, exist_ok=True)
                    with open(txt_path, 'w', encoding='utf-8') as _df:
                        _df.write(full)
                    print(f"[Definition] ✅ Saved: {txt_path} ({len(full.split())} words)")
                else:
                    print(f"[Definition] ⚠️  result does not look like a definition — not saved")
            except Exception as _de:
                print(f"[Definition] ⚠️  Save error: {_de}")

        print("\n" + "="*60)
        print("✅ VIDEO FACTORY COMPLETED")
        print("="*60)
        print("\nResult:")
        print(result)
        print("\n" + "="*60)
        print(f"\n📁 Outputs:")
        print(f"   CSV: {csv_path}")
        print(f"   Subdirectory: {output_dir}/")

        if inputs.get('video_enabled', True):
            print(f"   Videos (Standard):")
            for style in inputs['animation_styles']:
                for fmt in inputs['video_formats']:
                    video_file = f"{output_dir}/{style}_{fmt}_{style}_{fmt}.mp4"
                    if os.path.exists(video_file):
                        print(f"      ✅ {video_file}")

        if inputs.get('intro_enabled', False):
            _lang = inputs.get('lang_suffix', 'En')
            _merge_ran = inputs.get('debate_merge_enabled', False)
            _intro_files = []
            for fmt in inputs['video_formats']:
                for fpath, label in [
                    (f"{output_dir}/intro_{fmt}_{_lang}.mp4",            'video'),
                    (f"{output_dir}/intro_{fmt}_{_lang}_audio.mp3",      'audio'),
                    (f"{output_dir}/intro_{fmt}_{_lang}_with_audio.mp4", 'merged'),
                ]:
                    if os.path.exists(fpath):
                        _intro_files.append((fpath, label))
            if not _merge_ran and _intro_files:
                print(f"   Intro Clips:")
                for fpath, label in _intro_files:
                    kb = os.path.getsize(fpath) // 1024
                    print(f"      ✅ {fpath} ({kb} KB) [{label}]")

        if inputs.get('bar_race_video_enabled', False):
            print(f"   Videos (Bar Race):")
            for fmt in inputs['video_formats']:
                video_file = f"{output_dir}/bar_race_{fmt}.mp4"
                audio_file = f"{output_dir}/bar_race_{fmt}_audio.mp3"
                merged_file = f"{output_dir}/bar_race_{fmt}_with_audio.mp4"
                if os.path.exists(video_file):
                    kb = os.path.getsize(video_file) // 1024
                    print(f"      ✅ {video_file} ({kb} KB)")
                else:
                    print(f"      ❌ Not found: {video_file}")
                if os.path.exists(audio_file):
                    kb = os.path.getsize(audio_file) // 1024
                    print(f"      ✅ {audio_file} ({kb} KB)")
                if os.path.exists(merged_file):
                    kb = os.path.getsize(merged_file) // 1024
                    print(f"      ✅ {merged_file} ({kb} KB)")

        if inputs.get('audio_enabled', False):
            print(f"   Audio (Standard):")
            for style in inputs['animation_styles']:
                for fmt in inputs['video_formats']:
                    audio_file = f"{output_dir}/{style}_{fmt}_{style}_{fmt}_audio.mp3"
                    if os.path.exists(audio_file):
                        print(f"      ✅ {audio_file}")

        if inputs.get('merge_audio_video', False):
            print(f"   Merged:")
            for style in inputs['animation_styles']:
                for fmt in inputs['video_formats']:
                    merged_file = f"{output_dir}/{style}_{fmt}_{style}_{fmt}_with_audio.mp4"
                    if os.path.exists(merged_file):
                        print(f"      ✅ {merged_file}")

        # bar race merged already reported in the bar_race_video_enabled block above
        if inputs.get('bar_merge_enabled', False):
            print(f"   Bar Merged (Final):")
            import re as _re
            topic_slug = "_".join(_re.findall(r"\w+", inputs["topic"])[:4])
            for fmt in inputs['video_formats']:
                # Check renamed file first, then Final_ fallback
                renamed   = f"{output_dir}/{inputs['channel']}_{topic_slug}_{fmt}.mp4"
                final_raw = f"{output_dir}/Final_{fmt}.mp4"
                if os.path.exists(renamed):
                    size_mb = os.path.getsize(renamed) / (1024*1024)
                    print(f"      ✅ {renamed} ({size_mb:.1f} MB)")
                elif os.path.exists(final_raw):
                    size_mb = os.path.getsize(final_raw) / (1024*1024)
                    print(f"      ✅ {final_raw} ({size_mb:.1f} MB)  [yt_metadata not run — not renamed]")
                else:
                    print(f"      ❌ Not found: {renamed}")

        if inputs.get('generate_youtube_metadata', False):
            print(f"   YouTube Metadata:")
            metadata_files = [
                f"{output_dir}/cc_en.txt",
                f"{output_dir}/YT_Metadata.json",
                f"{output_dir}/YT_Metadata.txt",
            ]
            for mf in metadata_files:
                if os.path.exists(mf):
                    print(f"      ✅ {mf}")

        if inputs.get('definition_enabled', False):
            print(f"   Topic Definition:")
            _main_dir2     = os.path.dirname(os.path.abspath(__file__))
            _project_root2 = os.path.dirname(os.path.dirname(_main_dir2))
            def_file = os.path.join(_project_root2, 'output', f"{inputs['filename']}.txt")
            if os.path.exists(def_file):
                size_kb = os.path.getsize(def_file) // 1024
                print(f"      ✅ {def_file} ({size_kb} KB)")
            else:
                print(f"      ❌ Not found: {def_file}")

        if inputs.get('definition_video', False):
            print(f"   Definition Videos:")
            for fmt in inputs['video_formats']:
                vid        = f"{output_dir}/definition_video_{fmt}.mp4"
                vid_audio  = f"{output_dir}/definition_video_{fmt}_audio.mp3"
                vid_merged = f"{output_dir}/definition_video_{fmt}_with_audio.mp4"
                if os.path.exists(vid):
                    kb = os.path.getsize(vid) // 1024
                    print(f"      ✅ {vid} ({kb} KB)")
                else:
                    print(f"      ❌ Not found: {vid}")
                if os.path.exists(vid_audio):
                    kb = os.path.getsize(vid_audio) // 1024
                    print(f"      ✅ {vid_audio} ({kb} KB)")
                if os.path.exists(vid_merged):
                    kb = os.path.getsize(vid_merged) // 1024
                    print(f"      ✅ {vid_merged} ({kb} KB)")

        if inputs.get('debate_video_enabled', False):
            _lang = inputs.get('lang_suffix', 'En')
            _merge_ran = inputs.get('debate_merge_enabled', False)
            _debate_files = []
            for fmt in inputs['video_formats']:
                for suffix, label in [
                    (f'debate_video_{fmt}_{_lang}.mp4',            'silent'),
                    (f'debate_video_{fmt}_{_lang}_audio.mp3',      'audio'),
                    (f'debate_video_{fmt}_{_lang}_with_audio.mp4', 'merged'),
                ]:
                    fpath = f"{output_dir}/{suffix}"
                    if os.path.exists(fpath):
                        _debate_files.append((fpath, label))
            if not _merge_ran and _debate_files:
                print(f"   Debate Video:")
                for fpath, label in _debate_files:
                    kb = os.path.getsize(fpath) // 1024
                    print(f"      ✅ {fpath} ({kb} KB) [{label}]")

        # ✅ NEW: Debate Merge Output Summary (ADDED)
        if inputs.get('debate_merge_enabled', False):
            print(f"   Debate Merged (Final):")
            import re as _re
            topic_slug = "_".join(_re.findall(r"\w+", inputs["topic"])[:4])
            _lang = inputs.get('lang_suffix', 'En')
            for fmt in inputs['video_formats']:
                merged = f"{output_dir}/{inputs['channel']}_Debate_{topic_slug}_{fmt}_{_lang}.mp4"
                if os.path.exists(merged):
                    size_mb = os.path.getsize(merged) / (1024*1024)
                    print(f"      ✅ {merged} ({size_mb:.1f} MB)")
                else:
                    print(f"      ❌ Not found: {merged}")

        print(f"\n⏱️  Duration tip: {fps} seconds per period")
        print("="*60 + "\n")

        sys.exit(0)

    except SystemExit:
        raise  # preserve sys.exit(0) success and sys.exit(1) errors
    except Exception as e:
        print("\n" + "="*60)
        print("❌ VIDEO FACTORY FAILED")
        print("="*60)
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run()
