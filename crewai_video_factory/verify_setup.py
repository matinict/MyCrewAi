#!/usr/bin/env python3
"""
Setup Verification Script
Checks that smart_video_generator_dynamic3.py is in the correct location
"""

import os
import sys
import shutil

def verify_setup():
    """Verify the video generator script is in the project root"""
    
    # Get project root (where this script is)
    project_root = os.path.dirname(os.path.abspath(__file__))
    script_name = "smart_video_generator_dynamic3.py"
    expected_path = os.path.join(project_root, script_name)
    
    print("🔍 Checking project setup...")
    print(f"📁 Project root: {project_root}")
    print(f"🎬 Looking for: {script_name}")
    print()
    
    # Check if script exists in project root
    if os.path.exists(expected_path):
        print(f"✅ Found video generator at: {expected_path}")
        return True
    
    print(f"❌ Video generator NOT found at: {expected_path}")
    print()
    
    # Search for the script in common locations
    print("🔍 Searching for the script in other locations...")
    search_paths = [
        os.path.join(project_root, "src", script_name),
        os.path.join(project_root, "src", "crewai_video_factory", script_name),
        os.path.join(os.path.expanduser("~"), "Downloads", script_name),
        os.path.join(os.getcwd(), script_name),
    ]
    
    found_path = None
    for path in search_paths:
        if os.path.exists(path):
            print(f"✅ Found at: {path}")
            found_path = path
            break
        else:
            print(f"   Not at: {path}")
    
    if found_path:
        print()
        response = input(f"📋 Copy from {found_path} to {expected_path}? (y/n): ")
        if response.lower() == 'y':
            shutil.copy2(found_path, expected_path)
            print(f"✅ Copied to: {expected_path}")
            return True
    
    print()
    print("❌ Setup incomplete!")
    print()
    print("📋 To fix this:")
    print(f"   1. Locate your 'smart_video_generator_dynamic3.py' file")
    print(f"   2. Copy it to: {expected_path}")
    print(f"   3. Run this script again to verify")
    print()
    
    return False

if __name__ == "__main__":
    success = verify_setup()
    
    if success:
        print()
        print("✅ Setup verified! You're ready to run:")
        print("   crewai run")
        print()
        sys.exit(0)
    else:
        sys.exit(1)
