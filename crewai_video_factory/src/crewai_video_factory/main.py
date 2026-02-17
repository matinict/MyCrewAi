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
DEFAULT_INPUTS = {
    "topic": "Programming Language",
    "start": 2015,
    "end": 2026,
    "granularity": "yearly",
    "animation_styles": ["bar"],
    "video_formats": ["Shorts"],
    "fps": 0.5,
    "use_existing_csv":False,
    "video_enabled": True,
    "audio_enabled": True,
    "audio_speed": 0.9,
    "merge_audio_video": True,
    "generate_youtube_metadata": True,
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

    # 🔑 KEY: Set output_dir for ALL tools (topic subdirectory)
    output_dir = f"output/{inputs['filename']}"
    os.makedirs(output_dir, exist_ok=True)
    inputs['output_dir'] = output_dir

    # FPS validation
    fps = float(inputs.get('fps', 1.0))
    if fps < 0.1 or fps > 30.0:
        print(f"⚠️  Invalid FPS {fps}. Clamping to valid range (0.1-30.0)")
        fps = max(0.1, min(30.0, fps))
    inputs['fps'] = fps

    # ===== USE_EXISTING_CSV HANDLING =====
    # 🔑 KEY: Define csv_path BEFORE using it in print statements
    csv_path = f"output/{inputs['filename']}.csv"  # CSV stays flat
    use_existing = inputs.get('use_existing_csv', False)

    print("\n" + "="*60)
    print("🎬 VIDEO FACTORY STARTING")
    print("="*60)
    print(f"📊 Topic: {inputs['topic']}")
    print(f"📁 CSV File: {csv_path}")
    print(f"📁 Output Subdirectory: {output_dir}/")
    print(f"⏱️  Animation speed: {fps} fps → ~{12/fps:.1f} sec duration (for 12 data points)")

    if use_existing:
        if not os.path.exists(csv_path):
            print(f"❌ ERROR: use_existing_csv=True but CSV not found at {csv_path}")
            print("💡 Fix: Set use_existing_csv=False to generate new data, or create the CSV manually")
            sys.exit(1)
        print("⏭️  SKIPPING data research & CSV generation (using existing file)")
        inputs['_skip_research'] = True
        inputs['_skip_csv'] = True
    else:
        print("🔍 Researching new data & generating CSV")
        inputs['_skip_research'] = False
        inputs['_skip_csv'] = False

    print(f"🎨 Animations: {', '.join(inputs['animation_styles'])}")
    print(f"📱 Formats: {', '.join(inputs['video_formats'])}")
    print(f"🎬 Video Enabled: {inputs.get('video_enabled', True)}")
    print(f"🔊 Audio Enabled: {inputs.get('audio_enabled', False)}")
    print(f"🔄 Merge Audio-Video: {inputs.get('merge_audio_video', False)}")
    print(f"📝 YouTube Metadata: {inputs.get('generate_youtube_metadata', False)}")
    print("="*60 + "\n")

    try:
        crew_instance = CrewaiVideoFactory()
        full_crew = crew_instance.crew()

        # ===== CONDITIONAL TASK EXECUTION =====
        final_tasks = []

        if not inputs.get('_skip_research', False):
            final_tasks.append(full_crew.tasks[0])  # research_data
        if not inputs.get('_skip_csv', False):
            final_tasks.append(full_crew.tasks[1])  # generate_csv

        if inputs.get('video_enabled', True):
            final_tasks.append(full_crew.tasks[2])  # create_video

        if inputs.get('audio_enabled', False):
            final_tasks.append(full_crew.tasks[3])  # add_audio

        if inputs.get('merge_audio_video', False):
            final_tasks.append(full_crew.tasks[4])  # merge_audio_video

        if inputs.get('generate_youtube_metadata', False):
            final_tasks.append(full_crew.tasks[5])  # generate_youtube_metadata

        if not final_tasks:
            print("❌ ERROR: No tasks to execute. At least one task must be enabled.")
            sys.exit(1)

        full_crew.tasks = final_tasks

        result = full_crew.kickoff(inputs=inputs)

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
            print(f"   Videos:")
            for style in inputs['animation_styles']:
                for fmt in inputs['video_formats']:
                    video_file = f"{output_dir}/{inputs['filename']}_{style}_{fmt}.mp4"
                    print(f"      - {video_file}")

        if inputs.get('audio_enabled', False):
            print(f"   Audio:")
            for style in inputs['animation_styles']:
                for fmt in inputs['video_formats']:
                    audio_file = f"{output_dir}/{inputs['filename']}_{style}_{fmt}_audio.mp3"
                    if os.path.exists(audio_file):
                        print(f"      - {audio_file}")

        if inputs.get('merge_audio_video', False):
            print(f"   Merged:")
            for style in inputs['animation_styles']:
                for fmt in inputs['video_formats']:
                    merged_file = f"{output_dir}/{inputs['filename']}_{style}_{fmt}_with_audio.mp4"
                    if os.path.exists(merged_file):
                        print(f"      - {merged_file}")

        if inputs.get('generate_youtube_metadata', False):
            print(f"   YouTube Metadata:")
            metadata_files = [
                f"{output_dir}/{inputs['filename']}_cc_en.txt",
                f"{output_dir}/{inputs['filename']}_YouTube_Metadata.json",
                f"{output_dir}/{inputs['filename']}_YouTube_Metadata.txt",
            ]
            for mf in metadata_files:
                if os.path.exists(mf):
                    print(f"      - {mf}")

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

if __name__ == "__main__":
    run()
