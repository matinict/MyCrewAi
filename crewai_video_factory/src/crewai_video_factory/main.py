#!/usr/bin/env python
"""
🔥 ONE-COMMAND VIDEO FACTORY 🔥
Usage via CrewAI CLI:
crewai run
Or directly:
python main.py

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
    """Load configuration from input/data.json"""
    config_path = "input/data.json"

    if not os.path.exists(config_path):
        print("❌ Configuration file not found: input/data.json")
        print("📝 Please create input/data.json with your settings")
        print("📖 See input/data.schema.json for available options\n")

        # Create example file
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
        with open(config_path, 'w') as f:
            json.dump(example_config, f, indent=2)
        print(f"✅ Created example config at: {config_path}")
        print("⚠️  Please edit it and run again\n")
        sys.exit(1)

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in {config_path}: {e}")
        print("💡 Check syntax at https://jsonlint.com/")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        sys.exit(1)

# Load configuration from input/data.json
DEFAULT_INPUTS = load_config()

def run():
    inputs = DEFAULT_INPUTS.copy()

    # Parse CLI arguments (override input/data.json if provided)
    if len(sys.argv) > 1:
        try:
            custom_inputs = json.loads(sys.argv[1])
            inputs.update(custom_inputs)
            print("✅ CLI arguments override applied\n")
        except json.JSONDecodeError:
            print("⚠️  Invalid JSON in CLI args. Using input/data.json values\n")

    # Generate filename from topic
    words = re.findall(r'\w+', inputs['topic'])[:3]
    inputs['filename'] = ''.join(words)
    inputs['original_topic'] = inputs['topic']

    # 🔑 KEY: Set output_dir for ALL tools (topic subdirectory)
    output_dir = f"output/{inputs['filename']}"
    os.makedirs(output_dir, exist_ok=True)
    inputs['output_dir'] = output_dir

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

    if use_existing:
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

    print(f"🎨 Animations: {', '.join(inputs['animation_styles'])}")
    print(f"📱 Formats: {', '.join(inputs['video_formats'])}")
    print(f"🎬 Video Enabled: {inputs.get('video_enabled', True)}")
    print(f"✨ Bar Race Video Enabled: {inputs.get('bar_race_video_enabled', False)}")
    print(f"🎙️ Bar Race Audio Enabled: {inputs.get('bar_race_audio_enabled', False)}")
    print(f"🎬 Intro Clip Enabled: {inputs.get('intro_enabled', False)}")
    print(f"🔊 Audio Enabled: {inputs.get('audio_enabled', False)}")
    print(f"📹 Merge Audio-Video: {inputs.get('merge_audio_video', False)}")
    print(f"📺 YouTube Metadata: {inputs.get('generate_youtube_metadata', False)}")
    print(f"🎬 Definition Video: {inputs.get('definition_video', False)}")

    # LLM overrides banner
    llm_keys = ['llm_researcher', 'llm_definition', 'llm_csv', 'llm_video', 'llm_audio', 'llm_youtube']
    llm_overrides = {k: inputs[k] for k in llm_keys if inputs.get(k) and str(inputs[k]).strip().lower() not in ('null','none','')}
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
        # [6] create_intro_clip       [7] bar_merge                [8] add_bar_race_audio
        # [9] add_audio               [10] merge_audio_video       [11] generate_youtube_metadata

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

        if inputs.get('bar_race_audio_enabled', False):
            final_tasks.append(full_crew.tasks[8])  # add_bar_race_audio

        if inputs.get('audio_enabled', False):
            final_tasks.append(full_crew.tasks[9])  # add_audio

        if inputs.get('definition_video', False):
            final_tasks.append(full_crew.tasks[3])  # create_definition_video

        # bar_merge AFTER definition_video — needs definition_video_with_audio ready
        if inputs.get('bar_merge_enabled', False):
            final_tasks.append(full_crew.tasks[7])  # bar_merge

        # merge_audio_video and generate_youtube_metadata run LAST
        if inputs.get('merge_audio_video', False):
            final_tasks.append(full_crew.tasks[10])  # merge_audio_video

        if inputs.get('generate_youtube_metadata', False):
            final_tasks.append(full_crew.tasks[11])  # generate_youtube_metadata



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

        # Definition tool saves file directly — just verify it exists
        if inputs.get('definition_enabled', False):
            filename_clean = inputs.get('filename', '')
            txt_path = f"output/{filename_clean}.txt"
            if os.path.exists(txt_path):
                size = os.path.getsize(txt_path)
                print(f"[Definition] ✅ Saved: {txt_path} ({size} bytes)")
            else:
                print(f"[Definition] ⚠️  File not found: {txt_path}")

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
            print(f"   Intro Clips:")
            for fmt in inputs['video_formats']:
                intro_file = f"{output_dir}/intro_{fmt}.mp4"
                if os.path.exists(intro_file):
                    print(f"      ✅ {intro_file}")
                else:
                    print(f"      ❌ Not found: {intro_file}")

        if inputs.get('bar_race_video_enabled', False):
            print(f"   Videos (Bar Race):")
            for fmt in inputs['video_formats']:
                video_file = f"{output_dir}/bar_race_{fmt}_bar_race_{fmt}.mp4"
                if os.path.exists(video_file):
                    print(f"      ✅ {video_file}")

        if inputs.get('bar_race_audio_enabled', False):
            print(f"   Audio (Bar Race):")
            for fmt in inputs['video_formats']:
                audio_file = f"{output_dir}/bar_race_{fmt}_audio.mp3"
                if os.path.exists(audio_file):
                    print(f"      ✅ {audio_file}")

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
            if inputs.get('bar_race_video_enabled', False):
                for fmt in inputs['video_formats']:
                    merged_file = f"{output_dir}/bar_race_{fmt}_bar_race_{fmt}_with_audio.mp4"
                    if os.path.exists(merged_file):
                        print(f"      ✅ {merged_file}")

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
            def_file = f"output/{inputs['filename']}.txt"
            if os.path.exists(def_file):
                print(f"      ✅ {def_file}")
            else:
                print(f"      ❌ Not found: {def_file}")

        if inputs.get('definition_video', False):
            print(f"   Definition Videos:")
            for fmt in inputs['video_formats']:
                vid = f"{output_dir}/definition_video_{fmt}.mp4"
                if os.path.exists(vid):
                    print(f"      ✅ {vid}")
                else:
                    print(f"      ❌ Not found: {vid}")

        print(f"\n⏱️  Duration tip: {fps} seconds per period")
        print("="*60 + "\n")
        return result

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
