#!/usr/bin/env python
"""
🔥 ONE-COMMAND VIDEO FACTORY 🔥
Usage via CrewAI CLI:
crewai run
Or directly:
python main.py
"""
import os
import sys
import json
import re
from crewai_video_factory.crew import CrewaiVideoFactory

# Single source of truth for default inputs
# ⚠️ DO NOT include "Race" suffix here — it's added automatically for bar race videos only
DEFAULT_INPUTS = {
    "topic": "Programming Language",          # Clean topic (no "Race" suffix)
    "start": 2015,
    "end": 2026,
    "granularity": "yearly",               # Options: "yearly", "monthly", "daily"
    "animation_styles": ["bar"],           # Options: "bar", "line", "bubble", "map", "pie", "stream"
    "video_formats": ["Shorts"],           # Options: "HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"
    "fps": 0.5,                             # Duration control: 1.0 = 12 sec for 12 rows (2.0=6s, 0.5=24s)
    "use_existing_csv": True,              # if True/False use existing output/{topics} .csv
    "audio_enabled": True,                  # NEW PARAM - tool checks this internally
    "audio_speed": 0.9,                     # NEW PARAM - passed to audio tool
    "merge_audio_video": True,              # NEW PARAM - controls execution of merge tool
}

def run():
    inputs = DEFAULT_INPUTS.copy()

    # Parse CLI arguments
    if len(sys.argv) > 1:
        try:
            custom_inputs = json.loads(sys.argv[1])
            inputs.update(custom_inputs)
        except json.JSONDecodeError:
            print("⚠️  Invalid JSON input. Using defaults.")

    # Generate filename from topic
    words = re.findall(r'\w+', inputs['topic'])[:3]
    inputs['filename'] = ''.join(words)
    inputs['original_topic'] = inputs['topic']

    # FPS validation
    fps = float(inputs.get('fps', 1.0))
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
    print(f"⏱️  Animation speed: {fps} fps → ~{12/fps:.1f} sec duration (for 12 data points)")
    print(f"📁 CSV File: {csv_path}")

    if use_existing:
        if not os.path.exists(csv_path):
            print(f"❌ ERROR: use_existing_csv=True but CSV not found at {csv_path}")
            print("💡 Fix: Set use_existing_csv=False to generate new data, or create the CSV manually")
            sys.exit(1)
        print("⏭️  SKIPPING data research & CSV generation (using existing file)")
        # Skip research/generation tasks - only run video creation
        inputs['_skip_research'] = True
        inputs['_skip_csv'] = True
    else:
        print("🔍 Researching new data & generating CSV")
        inputs['_skip_research'] = False
        inputs['_skip_csv'] = False
    # =====================================

    print(f"🎨 Animations: {', '.join(inputs['animation_styles'])}")
    print(f"📱 Formats: {', '.join(inputs['video_formats'])}")
    print(f"🔊 Audio Enabled: {inputs.get('audio_enabled', False)}")
    print(f"🔄 Merge Audio-Video: {inputs.get('merge_audio_video', False)}")
    print("="*60 + "\n")

    try:
        crew_instance = CrewaiVideoFactory()

        # ===== CONDITIONAL TASK EXECUTION (BEFORE KICKOFF) =====
        full_crew = crew_instance.crew()

        # Determine tasks based on inputs AFTER parsing, BEFORE kickoff
        final_tasks = []
        for task_obj in full_crew.tasks:
            # Assuming task names correspond to method names in crew.py
            if task_obj.name == 'merge_audio_video' and not inputs.get('merge_audio_video', False):
                print(f"⏭️  Skipping merge task as 'merge_audio_video' is False.")
                continue # Skip adding the merge task
            final_tasks.append(task_obj)

        # Set the filtered tasks list on the crew instance
        full_crew.tasks = final_tasks

        # Decide whether to run full pipeline or just video creation
        if inputs.get('_skip_research', False) and inputs.get('_skip_csv', False):
             # Filter to only video creation and subsequent tasks (audio, merge if enabled)
             # This assumes 'create_video' is the first task that *always* runs in the sequence after potential skips.
             # A more robust way might involve defining task dependencies explicitly.
             # For now, find the index of 'create_video' and take everything from there.
             create_video_idx = None
             for i, t in enumerate(final_tasks):
                 if t.name == 'create_video':
                     create_video_idx = i
                     break
             if create_video_idx is not None:
                 full_crew.tasks = final_tasks[create_video_idx:]
             else:
                 # Fallback if 'create_video' somehow isn't found in final_tasks
                 print("❌ Error: Could not find 'create_video' task after filtering.")
                 sys.exit(1)
        # Otherwise, proceed with the full list of tasks (research, csv, video, audio, merge_if_enabled)

        result = full_crew.kickoff(inputs=inputs)
        # =======================================

        print("\n" + "="*60)
        print("✅ VIDEO FACTORY COMPLETED")
        print("="*60)
        print("\nResult:")
        print(result)
        print("\n" + "="*60)
        print(f"\n📁 Outputs:")
        print(f"   CSV: {csv_path}")
        print(f"   Videos:")
        for style in inputs['animation_styles']:
            for fmt in inputs['video_formats']:
                video_file = f"output/{inputs['filename']}_{style}_{fmt}.mp4"
                print(f"      - {video_file}")
                # Print merged file if merge was enabled
                if inputs.get('merge_audio_video', False):
                    merged_file = video_file.replace('.mp4', '_with_audio.mp4')
                    if os.path.exists(merged_file):
                         print(f"      - {merged_file} (Merged)")
        print(f"\n⏱️  Duration tip: With {fps} fps and {12} data points → ~{12/fps:.1f} seconds")
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

# ... [train/replay/test functions unchanged] ...

if __name__ == "__main__":
    run()
