#!/usr/bin/env python
"""
🔥 ONE-COMMAND VIDEO FACTORY 🔥

Usage:
    python run.py '{"topic": "AI Agent Framework Popularity", "start": 2015, "end": 2026, "granularity": "yearly"}'
    
    Or simply:
    python run.py
    
    (will use default inputs)
"""

import sys
import json
from crew import VideoFactoryCrew


def main():
    # Default inputs
    default_inputs = {
        "topic": "AI Agent Framework Popularity",
        "start": 2015,
        "end": 2026,
        "granularity": "yearly"
    }
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        try:
            inputs = json.loads(sys.argv[1])
        except json.JSONDecodeError:
            print("❌ Invalid JSON input. Using defaults.")
            inputs = default_inputs
    else:
        print("ℹ️  No input provided. Using defaults:")
        print(json.dumps(default_inputs, indent=2))
        inputs = default_inputs
    
    # Validate inputs
    required_keys = ['topic', 'start', 'end', 'granularity']
    for key in required_keys:
        if key not in inputs:
            print(f"❌ Missing required input: {key}")
            sys.exit(1)
    
    # Validate granularity
    valid_granularities = ['yearly', 'monthly', 'daily']
    if inputs['granularity'].lower() not in valid_granularities:
        print(f"❌ Invalid granularity: {inputs['granularity']}")
        print(f"   Valid options: {', '.join(valid_granularities)}")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("🎬 VIDEO FACTORY STARTING")
    print("="*60)
    print(f"📊 Topic: {inputs['topic']}")
    print(f"📅 Period: {inputs['start']} - {inputs['end']}")
    print(f"⏱️  Granularity: {inputs['granularity']}")
    print("="*60 + "\n")
    
    # Initialize and run the crew
    try:
        crew = VideoFactoryCrew(inputs=inputs)
        result = crew.crew().kickoff(inputs=inputs)
        
        print("\n" + "="*60)
        print("✅ VIDEO FACTORY COMPLETED")
        print("="*60)
        print("\nResult:")
        print(result)
        print("\n" + "="*60)
        
        # Calculate output filename
        import re
        words = re.findall(r'\w+', inputs['topic'])[:3]
        filename = ''.join(words)
        
        print(f"\n📁 Check your outputs:")
        print(f"   CSV: output/{filename}.csv")
        print(f"   Video: output/{filename}.mp4 (or similar)")
        print("\n")
        
    except Exception as e:
        print("\n" + "="*60)
        print("❌ VIDEO FACTORY FAILED")
        print("="*60)
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
