#!/usr/bin/env python
"""
🔥 ONE-COMMAND VIDEO FACTORY 🔥
Usage via CrewAI CLI:
crewai run
Or directly:
python main.py
"""
import sys
import json
import re
from crewai_video_factory.crew import CrewaiVideoFactory

# Single source of truth for default inputs
# ⚠️ DO NOT include "Race" suffix here — it's added automatically for bar race videos only
DEFAULT_INPUTS = {
    "topic": "AI Multimodal LLM",          # Clean topic (no "Race" suffix)
    "start": 2015,
    "end": 2026,
    "granularity": "yearly",               # Options: "yearly", "monthly", "daily"
    "animation_styles": ["bar"],           # Options: "bar", "line", "bubble", "map", "pie", "stream"
    "video_formats": ["Shorts"],           # Options: "HD", "2K", "4K", "8K", "Shorts", "ShortsHD", "Shorts4K"
    "fps": 1.0                             # Duration control: 1.0 = 12 sec for 12 rows (2.0=6s, 0.5=24s)
}

def run():
    inputs = DEFAULT_INPUTS.copy()
    
    # Try to get inputs from command line args
    if len(sys.argv) > 1:
        try:
            custom_inputs = json.loads(sys.argv[1])
            inputs.update(custom_inputs)
        except json.JSONDecodeError:
            print("⚠️  Invalid JSON input. Using defaults.")
    
    # Calculate filename from topic (first 3 words, no spaces)
    words = re.findall(r'\w+', inputs['topic'])[:3]
    inputs['filename'] = ''.join(words)
    
    # === CRITICAL: LOCK TOPIC TO PREVENT AGENT OVERRIDE ===
    # Store original topic to prevent LLM agents from "improving" it to "AI Growth Over Years"
    inputs['original_topic'] = inputs['topic']
    # =======================================================
    
    print("\n" + "="*60)
    print("🎬 VIDEO FACTORY STARTING")
    print("="*60)
    print(f"📊 REQUESTED Topic: {DEFAULT_INPUTS['topic']}")
    print(f"🔍 LOCKED Topic: {inputs['topic']}")          # Shows actual topic used
    print(f"📅 Period: {inputs['start']} - {inputs['end']}")
    print(f"⏱️  Granularity: {inputs['granularity']}")
    print(f"⏱️  Duration Control (fps): {inputs.get('fps', 2.0)}")
    styles = inputs.get('animation_styles') or [inputs.get('animation_style', 'bar')]
    if isinstance(styles, str): 
        styles = [styles.strip()]
    print(f"🎨 Animations: {', '.join(styles)}")
    print(f"📱 Format: {', '.join(inputs.get('video_formats', ['HD']))}")
    print(f"📁 Filename: {inputs['filename']}.csv")
    print("="*60 + "\n")
    
    try:
        crew_instance = CrewaiVideoFactory()
        result = crew_instance.crew().kickoff(inputs=inputs)
        
        print("\n" + "="*60)
        print("✅ VIDEO FACTORY COMPLETED")
        print("="*60)
        print("\nResult:")
        print(result)
        print("\n" + "="*60)
        print(f"\n📁 Check your outputs:")
        print(f"   CSV: output/{inputs['filename']}.csv")
        print(f"   Videos:")
        styles = inputs.get('animation_styles') or [inputs.get('animation_style', 'bar')]
        if isinstance(styles, str):
            styles = [styles.strip()]
        formats = inputs.get('video_formats') or [inputs.get('video_format', 'HD')]
        if isinstance(formats, str):
            formats = [formats.strip()]
        for style in styles:
            for fmt in formats:
                print(f"      - output/{inputs['filename']}_{style}_{fmt}.mp4")
        print("\n💡 Bar race videos will show: \"{topic} Race - {year}\"")
        print("   (e.g., \"AI Multimodal LLM Race - 2025\")")
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

def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = DEFAULT_INPUTS.copy()
    try:
        CrewaiVideoFactory().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        CrewaiVideoFactory().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = DEFAULT_INPUTS.copy()
    try:
        CrewaiVideoFactory().crew().test(n_iterations=int(sys.argv[1]), openai_model_name=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

if __name__ == "__main__":
    run()