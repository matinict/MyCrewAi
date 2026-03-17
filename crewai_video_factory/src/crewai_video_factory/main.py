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
        #
        # publisher_config is special: its sub-blocks (yt_upload, fb_upload, future
        # platforms like tiktok_upload) are ALWAYS extracted independently of the
        # parent "publisher" switch. The publisher switch only gates the legacy
        # upload_youtube_video top-level flag and shared LLM keys (llm_upload, llm_embed).
        # This lets "publisher": false + "fb_upload": true work correctly.

        # ── Step 1: Extract publisher_config sub-blocks FIRST (always) ────────
        _pub_cfg = config.pop('publisher_config', None) or {}
        if isinstance(_pub_cfg, dict):
            _pub_on = config.get('publisher', False)

            # ── yt_upload sub-block (always extract, gated by its own yt_upload switch) ──
            if 'yt_upload' in _pub_cfg:
                config.setdefault('yt_upload', _pub_cfg.pop('yt_upload'))
            _yt_cfg = _pub_cfg.pop('yt_upload_config', {})
            if _yt_cfg:
                config.setdefault('yt_upload_config', _yt_cfg)

            # ── fb_upload sub-block (always extract, gated by its own fb_upload switch) ──
            if 'fb_upload' in _pub_cfg:
                config.setdefault('fb_upload', _pub_cfg.pop('fb_upload'))
            _fb_cfg = _pub_cfg.pop('fb_upload_config', {})
            if _fb_cfg:
                if 'privacy_status' in _fb_cfg:
                    _fb_cfg['fb_privacy_status'] = _fb_cfg.pop('privacy_status')
                if 'credentials_file' in _fb_cfg:
                    _fb_cfg['fb_credentials_file'] = _fb_cfg.pop('credentials_file')
                config.setdefault('fb_upload_config', _fb_cfg)

            # ── Future platform sub-blocks follow the same pattern ─────────────
            # Example (TikTok — uncomment when tiktok_upload_tool.py is ready):
            # if 'tiktok_upload' in _pub_cfg:
            #     config.setdefault('tiktok_upload', _pub_cfg.pop('tiktok_upload'))
            # _tt_cfg = _pub_cfg.pop('tiktok_upload_config', {})
            # if _tt_cfg:
            #     config.setdefault('tiktok_upload_config', _tt_cfg)

            # ── Remaining publisher_config keys (LLM overrides etc.) ──────────
            # Only hoist when publisher=true; discard silently when false
            if _pub_on:
                config.update(_pub_cfg)
            # If publisher=false, force legacy gate flag off (does NOT affect sub-blocks)
            if not config.get('publisher', False):
                config.setdefault('upload_youtube_video', False)

        # ── Step 2: Standard block_map for non-publisher blocks ───────────────
        # intro_enabled / intro_duration / intro_duration_hd are special:
        # they live inside animation_config AND debate_config independently.
        # We must not let the second block's update() overwrite the first.
        # Rule: intro_enabled=true from ANY active block wins (OR logic).
        _intro_enabled    = False
        _intro_duration   = None
        _intro_duration_hd = None
        _block_map = [
            ("animation",     "animation_config",     "bar_race_video_enabled"),
            ("debate",        "debate_config",        "debate_video_enabled"),
            ("metadata_prep", "metadata_prep_config", "generate_youtube_metadata"),
            ("social",        "social_config",        "social_share_enabled"),
        ]
        for _switch, _block, _flag in _block_map:
            _nested = config.pop(_block, None)
            if config.get(_switch, False):
                if isinstance(_nested, dict):
                    # ── Collect intro keys before update so blocks don't clobber each other ──
                    if _switch in ('animation', 'debate'):
                        if _nested.get('intro_enabled', False):
                            _intro_enabled = True
                        if _intro_duration is None and 'intro_duration' in _nested:
                            _intro_duration = _nested['intro_duration']
                        if _intro_duration_hd is None and 'intro_duration_hd' in _nested:
                            _intro_duration_hd = _nested['intro_duration_hd']
                        # Remove from nested so update() doesn't overwrite collected values
                        _nested.pop('intro_enabled', None)
                        _nested.pop('intro_duration', None)
                        _nested.pop('intro_duration_hd', None)

                    if _switch == 'metadata_prep' and ('video_formats' in _nested or 'video_style' in _nested):
                        _key = 'video_style' if 'video_style' in _nested else 'video_formats'
                        _nested['metadata_video_formats'] = _nested[_key]
                        _nested['video_style'] = _nested.pop(_key) if _key == 'video_style' else []

                    config.update(_nested)
                else:
                    config[_flag] = False  # guarantee gate flag is off

        # Apply collected intro values — OR logic: any active block with intro_enabled=true wins
        config['intro_enabled']     = _intro_enabled
        config['intro_duration']    = _intro_duration    if _intro_duration    is not None else 7
        config['intro_duration_hd'] = _intro_duration_hd if _intro_duration_hd is not None else 10

        # ── Step 3: Flatten yt_upload_config and fb_upload_config ─────────────
        # yt_upload
        if config.get('yt_upload', False):
            _yt_cfg = config.pop('yt_upload_config', {})
            for _k, _v in _yt_cfg.items():
                config.setdefault(_k, _v)
        else:
            config.setdefault('upload_youtube_video', False)

        # fb_upload — flatten fb_upload_config keys when fb_upload=true
        if config.get('fb_upload', False):
            _fb_cfg = config.pop('fb_upload_config', {})
            for _k, _v in _fb_cfg.items():
                config.setdefault(_k, _v)
            config.setdefault('upload_facebook_video', True)
        else:
            config.setdefault('upload_facebook_video', False)

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
            'definition_max_chars':       5000,
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
            'generate_yt_thumbnail':      False,
            'yt_metadata_lang':           35,
            'yt_cc_lang':                 20,
            'metadata_video_formats':     [],
            'video_style':                [],
            '_metadata_video_formats':    [],
            'animation_video_formats':    [],
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
            'schedule_post':              False,
            'schedule_datetime':          '',
            'schedule_timezone':          'UTC',
            # fb_upload_config
            'upload_facebook_video':      False,
            'fb_privacy_status':          'SELF',
            'fb_credentials_file':        'input/fb_credentials.json',
            # yt_upload_config
            'yt_upload':                  False,
            'fb_upload':                  False,
            # watermark / branding
            'watermark_enabled':          False,
            'watermark_text':             '',
            'watermark_opacity':          60,
            # core fields with safe defaults
            'video_formats':              ['Shorts'],
            'fps_hd_offset':              1.0,
            'audio_speed':                1.0,
            'audio_speed_hd':             1.0,
            'tts_engine':                 'gtts',
            'channel_lower':              '',
            'website':                    '',
            'use_label_mappings':         False,
            # debate_config
            'debate_definition_enabled':  False,
            'debate_mini_enabled':        False,
            'debate_mini_max_chars':      5000,
            'debate_mini_merge_enabled':  False,
            'video_fps':                  24,
            'debate_video_enabled':       False,
            'debate_secs_per_line':       3.5,
            'debate_max_chars':           10000,
            'debate_merge_enabled':       False,
            'debate_background_enabled':  False,
            'debate_bg_opacity':          255,
            'debate_background_prompt':   '',
            'image_gen_backend':          'auto',
            'tts_voices':                 {},
            'intro_context':              'bar_race',
            'intro_slug':                 '',
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
_lang_flag = next((a for a in sys.argv[1:] if re.match(r'^-[a-z]{2}$', a)), None)
if _lang_flag:
    _lang_code   = _lang_flag[1:]
    _config_file = f"input/data{_lang_code.upper()}.json"
    import glob as _glob
    _candidates = _glob.glob(f"input/data{_lang_code}*.json") + \
                  _glob.glob(f"input/data{_lang_code.upper()}*.json")
    _candidates = [c for c in _candidates if c != "input/data.json"]
    if _candidates:
        _config_file = sorted(_candidates)[0]
    os.environ["INPUT_CONFIG"] = _config_file
    print(f"🌐 Lang flag: {_lang_flag}  →  {_config_file}")
    sys.argv = [a for a in sys.argv if a != _lang_flag]

_LANG_SUFFIX = _lang_flag[1:].capitalize() if _lang_flag else "En"

DEFAULT_INPUTS = load_config()


def run():
    inputs = DEFAULT_INPUTS.copy()
    inputs['lang_suffix'] = _LANG_SUFFIX

    # Parse CLI arguments (override input/data.json if provided)
    if len(sys.argv) > 1:
        try:
            custom_inputs = json.loads(sys.argv[1])
            inputs.update(custom_inputs)
            print("✅ CLI arguments override applied")
        except json.JSONDecodeError:
            pass

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
            inputs['intro_context'] = 'bar_race'

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
              (f"  [existing={inputs.get('use_existing_definition',False)}, max={inputs.get('definition_max_chars',15000)}ch]"
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
        print(f"   📋 YouTube Meta{inputs.get('generate_youtube_metadata', False)}")
        print(f"   🖼️  Thumbnail:       {inputs.get('generate_yt_thumbnail', False)}")
        _meta_fmts = inputs.get('metadata_video_formats') or inputs.get('video_formats', [])
        print(f"   🎬 Meta Formats:    {_meta_fmts}")
        print(f"   🌍 MD langs:        {inputs.get('yt_metadata_lang', 35)} | CC langs: {inputs.get('yt_cc_lang', 20)}")

    # ── Publisher block ──────────────────────────────────────
    pub_on = inputs.get('publisher', False)
    fb_on  = inputs.get('fb_upload', False)
    print(f"📤 Publisher:        {pub_on}")
    if pub_on:
        upload_on  = inputs.get('upload_youtube_video', False)
        cc_only_on = inputs.get('upload_cc', False) and not upload_on
        yt_upload_on = inputs.get('yt_upload', False)
        print(f"   ▶️  YouTube Upload:  {upload_on or yt_upload_on}" +
              (f"  [{inputs.get('upload_privacy','private')}]" if (upload_on or yt_upload_on) else ""))
        if cc_only_on:
            print(f"   📝 CC/MD Update:    True  "
                  f"[cc_limit={inputs.get('upload_cc_limit',0)}, md_limit={inputs.get('upload_md_limit',0)}]")
        if fb_on:
            print(f"   📘 Facebook Upload: {inputs.get('upload_facebook_video', False)}" +
                  (f"  [{inputs.get('fb_privacy_status','SELF')}]" if inputs.get('upload_facebook_video') else ""))

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
        print(f"   ✍️  Mini Debate:     {inputs.get('debate_mini_enabled', False)}" +
              (f"  [max={inputs.get('debate_mini_max_chars',5200)}ch, ~1-1.5min TTS]"
               if inputs.get('debate_mini_enabled') else ""))
        print(f"   🔀 Mini Merge:       {inputs.get('debate_mini_merge_enabled', False)}")
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

    # ── YOUTUBE ID MODE AUTO-DETECTION (NEW) ──────────────────────────────────
    topic_val = inputs.get('topic', '')
    is_youtube_id = bool(re.match(r'^[a-zA-Z0-9_-]{11}$', topic_val.strip()))

    if is_youtube_id and inputs.get('metadata_prep', False):
        print("🔄 MODE: YouTube ID detected — CC/Metadata scrape + update only")
        print(f"   🎬 Video ID: {topic_val}")

        # Force video_style to yt_id mode
        inputs.setdefault('metadata_prep_config', {})['video_style'] = ['yt_id']
        inputs['metadata_video_formats'] = ['yt_id']
        inputs['video_style'] = ['yt_id']

        # Skip video generation tasks (video already exists on YouTube)
        for key in ['animation', 'debate', 'video_enabled', 'audio_enabled',
                    'bar_race_video_enabled', 'definition_video', 'merge_audio_video',
                    'debate_video_enabled', 'debate_merge_enabled', 'debate_definition_enabled',
                    'debate_mini_enabled', 'debate_mini_merge_enabled']:
            inputs[key] = False

        # Configure for CC/MD update only (no video re-upload)
        inputs['upload_youtube_video'] = False  # Update CC/MD only
        inputs['upload_cc'] = True
        inputs['generate_youtube_metadata'] = True
        inputs['generate_thumbnail'] = False  # Skip thumbnail (use existing)

        print("   📝 Active Units: metadata_prep → publisher (CC+MD only)")
        print("   ⏭️  Skipped: animation, debate, video generation")

    try:
        crew_instance = CrewaiVideoFactory()
        full_crew = crew_instance.crew(inputs=inputs)

        # ===== CONDITIONAL TASK EXECUTION =====
        final_tasks = []

        # crew.py task index map (matches @task declaration order in crew.py):
        # [0]  research_data           [1]  generate_csv            [2]  define_topic
        # [3]  create_definition_video [4]  create_video            [5]  create_bar_race_video
        # [6]  create_intro_clip       [7]  bar_merge               [8]  add_audio
        # [9]  merge_audio_video       [10] debate_propose_m        [11] debate_oppose_m
        # [12] debate_decide_m         [13] debate_merge_m
        # [14] debate_propose          [15] debate_oppose           [16] debate_decide
        # [17] create_debate_video     [18] debate_merge
        # [19] generate_youtube_metadata [20] upload_to_youtube     [21] upload_to_facebook
        # [22] share_to_social   ← always last

        if not inputs.get('_skip_research', False):
            final_tasks.append(full_crew.tasks[0])  # research_data

        if not inputs.get('_skip_csv', False):
            final_tasks.append(full_crew.tasks[1])  # generate_csv

        if inputs.get('video_enabled', True):
            final_tasks.append(full_crew.tasks[4])  # create_video

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

        # ── Mini Debate pipeline (-m.md) ──────────────────────────────────────
        # Short version: ~120-180 words per file → 1–1.5 min TTS audio each
        # Outputs: propose-m.md / oppose-m.md / decide-m.md
        if inputs.get('debate_mini_enabled', False) and not is_youtube_id:
            _debate_dir = output_dir
            _lang = inputs.get('lang_suffix', 'En')
            _propose_m_exists = (
                os.path.exists(os.path.join(_debate_dir, f'propose-m_{_lang}.md')) or
                os.path.exists(os.path.join(_debate_dir, 'propose-m.md'))
            )
            _oppose_m_exists = (
                os.path.exists(os.path.join(_debate_dir, f'oppose-m_{_lang}.md')) or
                os.path.exists(os.path.join(_debate_dir, 'oppose-m.md'))
            )
            _decide_m_exists = (
                os.path.exists(os.path.join(_debate_dir, f'decide-m_{_lang}.md')) or
                os.path.exists(os.path.join(_debate_dir, 'decide-m.md'))
            )
            if _propose_m_exists and _oppose_m_exists and _decide_m_exists:
                print(f"⭐️  Mini debate files exist ({_lang}) — skipping LLM generation (using existing)")
            else:
                final_tasks.append(full_crew.tasks[10])  # debate_propose_m
                final_tasks.append(full_crew.tasks[11])  # debate_oppose_m
                final_tasks.append(full_crew.tasks[12])  # debate_decide_m

        if inputs.get('debate_mini_merge_enabled', False) and not is_youtube_id:
            final_tasks.append(full_crew.tasks[13])  # debate_merge_m

        # ── Full Debate pipeline ───────────────────────────────────────────────
        # Must run BEFORE generate_youtube_metadata so merged CC files exist
        if inputs.get('debate_definition_enabled', False) and not is_youtube_id:
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
                final_tasks.append(full_crew.tasks[14])  # debate_propose
                final_tasks.append(full_crew.tasks[15])  # debate_oppose
                final_tasks.append(full_crew.tasks[16])  # debate_decide

        if inputs.get("debate_video_enabled", False) and not is_youtube_id:
            final_tasks.append(full_crew.tasks[17])  # create_debate_video

        if inputs.get("debate_merge_enabled", False) and not is_youtube_id:
            final_tasks.append(full_crew.tasks[18])  # debate_merge

        # ── generate_youtube_metadata runs after all video/merge tasks ──
        if inputs.get('generate_youtube_metadata', False):
            # Resolve which video_formats the metadata tool should use.
            # metadata_video_formats (from metadata_prep_config.video_formats) takes
            # precedence — "debate" / "animation" / "yt_id" tokens drive branching inside the tool.
            # Falls back to main video_formats if not set.
            _meta_fmts = inputs.get('metadata_video_formats') or inputs.get('video_formats', ['HD'])
            inputs['_metadata_video_formats'] = _meta_fmts
            final_tasks.append(full_crew.tasks[19])  # generate_youtube_metadata

        # Run upload task if uploading video OR if CC/MD update needed for existing video
        if inputs.get('upload_youtube_video', False) or inputs.get('upload_cc', False):
            final_tasks.append(full_crew.tasks[20])  # upload_to_youtube

        # Social share — LAST unit always.
        # Parent switch "social" MUST be true AND social_share_enabled must be true.
        # "social": false hard-blocks the task regardless of any inner flag value.
        if inputs.get('social', False) and inputs.get('social_share_enabled', False):
            # For yt_id mode, social share can run without upload_to_youtube
            if is_youtube_id:
                print("📢 Social Share: Will use existing YouTube video URL")
                inputs['social_video_url'] = f"https://youtu.be/{topic_val}"
            final_tasks.append(full_crew.tasks[22])  # share_to_social  ← always last

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


        # ── Generate Shorts mobile debate files (-m.md) ──────────────────────
        # CrewAI output_file writes the .md files directly to disk.
        # Delegate all compression + writing to DebateDefinitionTool.
        if inputs.get('debate_definition_enabled', False) and not is_youtube_id:
            from crewai_video_factory.tools.debate_definition_tool import DebateDefinitionTool
            DebateDefinitionTool().post_process_from_disk(output_dir, inputs.get('lang_suffix', 'En'))

        # Save definition from result.raw (define_topic agent writes pure text, no tool)
        if inputs.get('definition_enabled', False) and not inputs.get('use_existing_definition', False):
            try:
                filename_clean = inputs.get('filename', '')
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

        if inputs.get('bar_merge_enabled', False):
            print(f"   Bar Merged (Final):")
            import re as _re
            topic_slug = "_".join(_re.findall(r"\w+", inputs["topic"])[:4])
            for fmt in inputs['video_formats']:
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
            print(f"   YouTube Meta")
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
        raise
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
