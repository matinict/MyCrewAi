#!/usr/bin/env python
# ============================================
# FILE: src/book_writer/main.py
# ============================================
import sys
import os
import re
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Set timeout explicitly if not already set
if not os.environ.get('LITELLM_REQUEST_TIMEOUT'):
    os.environ['LITELLM_REQUEST_TIMEOUT'] = '3600'

from book_writer.crew import BookWriter
from book_writer.utils.book_converter import convert_markdown_to_formats

def sanitize_filename(text, max_length=100):
    '''Convert text to safe filename (max 100 chars)'''
    filename = re.sub(r'[^\w\s-]', '', text)
    filename = re.sub(r'[-\s]+', '_', filename)
    return filename[:max_length].strip('_').lower()

def run():
    inputs = {
        'title': 'The PACTE Method: Turning Team Tension into Trust',
        'subtitle': 'The Self-Coaching Team: Building Trust, Autonomy, and Performance Through Micro-Actions',
        'author': 'Kalina Terzieva',
        'genre': 'Self-Help | Professional Growth | career development | Team Building',
        'target_audience': [
            'Team Leaders & Managers',
            'HR & People Development Professionals',
            'Internal & External Team Coaches',
            'Startup Founders & Scale-up Leaders',
            'Silent tensions undermining team performance'
        ],
        'chapters': 6,  # Further reduced from 5 to 3
        'words_per_chapter': 2000,  # Reduced from 600 to 400
        'total_word_count': 12000,  # 3 chapters × 400 words
        'writing_style': 'clear, descriptive, story-driven, jargon-free',
        'difficulty_level': 'beginner to intermediate',
        'tone': 'practical, future-focused, motivational',
        'use_cases_included': True,
        'case_studies': True,
        'examples_type': 'real-world, non-mathematical',
        'platforms': ['Amazon KDP', 'Gumroad', 'Leanpub']
    }
    
    # Use title for filenames
    title = inputs['title']
    safe_title = sanitize_filename(title)
    
    print("=" * 70)
    print("📚 BOOK WRITING CREW - STARTED")
    print("=" * 70)
    print(f"Title: {title}")
    print(f"Author: {inputs['author']}")
    print(f"Chapters: {inputs['chapters']}")
    print(f"Words per chapter: {inputs['words_per_chapter']}")
    print("=" * 70)
    
    # Run the crew
    print("\n🤖 Starting AI agents...")
    try:
        result = BookWriter().crew().kickoff(inputs=inputs)
        translation_successful = True
        print("\n✅ All tasks completed successfully!")
    except Exception as e:
        import traceback
        print("\n⚠️  Error occurred during crew execution")
        print(str(e))
        traceback.print_exc()
        translation_successful = False
    
    # Convert English version
    en_md = f'output/{title}_en.md'
    print(f"\nLooking for English file: {en_md}")
    
    if os.path.exists(en_md):
        print("=" * 70)
        print("📄 Converting English version to PDF and EPUB...")
        print("=" * 70)
        
        try:
            convert_markdown_to_formats(
                markdown_file=en_md,
                title=title,
                subtitle=inputs['subtitle'],
                author=inputs['author'],
                output_dir='output',
                output_prefix=f'{safe_title}_en',
                language='en'
            )
            print("\n✅ English conversion complete!")
        except Exception as e:
            print("\n❌ English conversion error:")
            print(str(e))
    else:
        print("\n⚠️  English file not found!")
        print(f"Expected location: {en_md}")
        print("\nChecking what files exist in output/:")
        if os.path.exists('output'):
            files = os.listdir('output')
            for f in files:
                print(f"  - {f}")
        else:
            print("  Output directory doesn't exist!")
    
    # Convert Bengali version
    bn_md = f'output/{title}_bn.md'
    print(f"\nLooking for bn file: {bn_md}")
    
    if os.path.exists(bn_md):
        # Check if file actually contains Bengali text
        with open(bn_md, 'r', encoding='utf-8') as f:
            content = f.read()
            # Check for Bengali Unicode range
            has_bengali = any('\u0980' <= char <= '\u09FF' for char in content)
        
        if has_bengali:
            print("=" * 70)
            print("📄 Converting Bengali version to PDF and EPUB...")
            print("=" * 70)
            
            try:
                convert_markdown_to_formats(
                    markdown_file=bn_md,
                    title=title,
                    subtitle=inputs['subtitle'],
                    author=inputs['author'],
                    output_dir='output',
                    output_prefix=f'{safe_title}_bn',
                    language='bn'
                )
                print("\n✅ bn conversion complete!")
            except Exception as e:
                print("\n❌ bn conversion error:")
                print(str(e))
        else:
            print("\n⚠️  WARNING: bn file exists but contains NO Bengali text!")
            print("The translation failed. File contains English instead of বাংলা.")
    else:
        print("\n⚠️  bn file not found!")
        print(f"Expected location: {bn_md}")
    
    # Summary
    print("\n" + "=" * 70)
    print("🎉 BOOK WRITING COMPLETE!")
    print("=" * 70)
    print("\n📦 Output files:")
    print("-" * 70)
    
    if os.path.exists(en_md):
        print(f"\n📄 English Version:")
        print(f"  ├─ Markdown: {title}_en.md")
        if os.path.exists(f'output/{safe_title}_en.pdf'):
            print(f"  ├─ PDF: {safe_title}_en.pdf")
        if os.path.exists(f'output/{safe_title}_en.epub'):
            print(f"  └─ EPUB: {safe_title}_en.epub")
    
    if os.path.exists(bn_md):
        print(f"\n📄 bn Version (বাংলা):")
        print(f"  ├─ Markdown: {title}_bn.md")
        if os.path.exists(f'output/{safe_title}_bn.pdf'):
            print(f"  ├─ PDF: {safe_title}_bn.pdf")
        if os.path.exists(f'output/{safe_title}_bn.epub'):
            print(f"  └─ EPUB: {safe_title}_bn.epub")
    
    print("\n📁 Location: output/ folder")
    print("=" * 70)

if __name__ == "__main__":
    run()