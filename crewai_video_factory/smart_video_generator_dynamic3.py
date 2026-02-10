"""
Dynamic AI Trends Video Generator
Everything derived from CSV filename automatically
"""

import pandas as pd
import bar_chart_race as bcr
import matplotlib.pyplot as plt
from gtts import gTTS
from moviepy.editor import VideoFileClip, AudioFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import os
import re
from datetime import datetime

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def remove_vowels(text):
    """
    Remove vowels from text for compact display
    Examples: LangChain => LngChn, AutoGPT => AtGPT
    Preserves first character if it's a vowel
    """
    if not text:
        return text
    
    vowels = 'aeiouAEIOU'
    # Keep first character, remove vowels from rest
    if len(text) <= 1:
        return text
    
    result = text[0]  # Always keep first character
    for char in text[1:]:
        if char not in vowels:
            result += char
    
    return result if result else text

# ==========================================
# 1. CONFIGURATION
# ==========================================
csv_path = "Data/AgentFramework_Popularity_Trends_2015–26.csv"
base_output_directory = "/media/matin/MHDD500/POAi/AiTrends/Agent/Framework"

# Create versioned directory with timestamp
timestamp = datetime.now().strftime("%y%m%d%H%M")  # Format: YYMMDDHHmm (e.g., 2502071430)
output_directory = os.path.join(base_output_directory, timestamp)

# Timing settings
intro_duration = 12  # Intro screen duration in seconds
seconds_per_year_full = 5  # Seconds per year in FULL video (normal pace for quality)
seconds_per_year_short = 4  # Seconds per year in SHORT video (faster pace)

os.makedirs(output_directory, exist_ok=True)

print("="*70)
print("🎬 DYNAMIC VIDEO GENERATOR")
print("="*70)
print(f"📁 Output directory: {output_directory}")

# ==========================================
# 2. PARSE CSV FILENAME DYNAMICALLY
# ==========================================

def parse_csv_filename(csv_path):
    """
    Parse CSV filename to extract all metadata
    Expected format: Topic1_Topic2_...._YearRange.csv
    Example: AgentFramework_Popularity_Trends_2015–26.csv
    """
    base_name = os.path.basename(csv_path).replace(".csv", "")
    
    # Split by underscore
    parts = base_name.split("_")
    
    # Find year range pattern (e.g., 2015-26, 2015–26, 2015-2026)
    year_pattern = r'(\d{4})[-–](\d{2,4})'
    year_range = None
    topic_parts = []
    
    for part in parts:
        if re.match(year_pattern, part):
            year_range = part
        else:
            topic_parts.append(part)
    
    # Construct readable topic
    topic_name = " ".join(topic_parts)
    
    # For file naming (use first 2 parts or all if less than 2)
    file_prefix = "_".join(topic_parts[:2]) if len(topic_parts) >= 2 else "_".join(topic_parts)
    
    return {
        'topic_name': topic_name,
        'file_prefix': file_prefix,
        'year_range': year_range,
        'all_parts': parts,
        'base_name': base_name
    }

metadata = parse_csv_filename(csv_path)

print("\n📋 CSV Metadata:")
print(f"  Topic Name: {metadata['topic_name']}")
print(f"  File Prefix: {metadata['file_prefix']}")
print(f"  Year Range: {metadata['year_range']}")

# ==========================================
# 3. LOAD AND ANALYZE DATA
# ==========================================
print("\n📊 Loading data...")
df = pd.read_csv(csv_path)
year_col = df.columns[0]
frameworks = df.columns[1:].tolist()

years = df[year_col].values
num_years = len(years)
data_viz_duration_full = (num_years - 1) * seconds_per_year_full
data_viz_duration_short = (num_years - 1) * seconds_per_year_short
total_duration_full = intro_duration + data_viz_duration_full
total_duration_short = intro_duration + data_viz_duration_short

start_year = int(years[0])
end_year = int(years[-1])

print(f"✓ Years: {start_year} to {end_year} ({num_years} years)")
print(f"✓ Items tracked: {len(frameworks)}")
print(f"✓ Intro screen: {intro_duration}s")
print(f"✓ Full video data: {data_viz_duration_full}s (total: {total_duration_full}s)")
print(f"✓ Short video data: {data_viz_duration_short}s (total: {total_duration_short}s)")

# ==========================================
# 4. ANALYZE YEAR-BY-YEAR
# ==========================================

def analyze_year_by_year(df):
    """Analyze each year for narration"""
    year_col = df.columns[0]
    years = df[year_col].values
    
    year_insights = []
    
    for i, year in enumerate(years):
        row_data = df.iloc[i, 1:].to_dict()
        sorted_items = sorted(row_data.items(), key=lambda x: x[1], reverse=True)
        top_items = [name for name, val in sorted_items[:3] if val > 0]
        leader = top_items[0] if top_items else None
        
        year_insights.append({
            'year': int(year),
            'leader': leader,
            'top_3': top_items,
            'total_activity': sum(row_data.values())
        })
    
    return year_insights

# ==========================================
# 5. GENERATE NARRATION DYNAMICALLY
# ==========================================

def generate_full_narration(year_insights, topic_name, channel='@PlayOwnAi'):
    """Generate narration with dynamic topic"""
    
    start_year = year_insights[0]['year']
    end_year = year_insights[-1]['year']
    
    script_parts = []
    
    # INTRO
    script_parts.append(f"Welcome to {channel}.")
    script_parts.append(f"Today, we're exploring {topic_name} from {start_year} to {end_year}.")
    script_parts.append("Let's see how the landscape evolved over time.")
    script_parts.append("")
    
    # YEAR BY YEAR COMMENTARY - Ensure ALL years are mentioned
    for i, insight in enumerate(year_insights):
        year = insight['year']
        leader = insight['leader']
        
        if leader:
            if i == 0:
                script_parts.append(f"{year}. {leader} emerges.")
            elif i < 3:
                script_parts.append(f"{year}. Early growth with {leader}.")
            elif i < 6:
                script_parts.append(f"{year}. {leader} gains traction.")
            elif i < 9:
                script_parts.append(f"{year}. {leader} shows strength.")
            elif i == len(year_insights) - 1:
                # Always mention the last year explicitly
                script_parts.append(f"And in {year}, {leader} continues to lead.")
            else:
                script_parts.append(f"{year}. {leader} leads the market.")
        else:
            script_parts.append(f"{year}. The market is forming.")
    
    # CONCLUSION
    script_parts.append("")
    script_parts.append("The evolution of technology and trends continues.")
    script_parts.append(f"Subscribe to {channel} for more insights.")
    
    return " ".join(script_parts)

def generate_short_narration(year_insights, topic_name, channel='@PlayOwnAi'):
    """Generate shorter narration"""
    
    start_year = year_insights[0]['year']
    end_year = year_insights[-1]['year']
    
    script_parts = []
    
    # Intro
    script_parts.append(f"Welcome to {channel}.")
    script_parts.append(f"{topic_name}, {start_year} to {end_year}.")
    script_parts.append("")
    
    # Mention key years including ALWAYS the last year
    for i, insight in enumerate(year_insights):
        # Include every other year OR the last year (to ensure 2026 is mentioned)
        if i % 2 == 0 or i == len(year_insights) - 1:
            year = insight['year']
            leader = insight['leader']
            if leader:
                if i == len(year_insights) - 1:
                    script_parts.append(f"And {year}. {leader}.")
                else:
                    script_parts.append(f"{year}. {leader}.")
    
    script_parts.append("")
    script_parts.append(f"Follow {channel} for more trends.")
    
    return " ".join(script_parts)

print("\n🧠 Analyzing trends...")
year_insights = analyze_year_by_year(df)

print("📝 Generating narration...")
full_narration = generate_full_narration(year_insights, metadata['topic_name'])
short_narration = generate_short_narration(year_insights, metadata['topic_name'])

# Preview
print("\n" + "-"*70)
print("NARRATION PREVIEW:")
print("-"*70)
print(full_narration[:300] + "...")
print("-"*70)

# ==========================================
# 6. DYNAMIC INTRO SCREEN GENERATOR
# ==========================================

def create_intro_screen_dynamic(duration, output_path, topic_name, start_year, end_year, 
                                resolution='1080p', channel='@PlayOwnAi'):
    """
    Create intro screen dynamically from CSV data
    Everything is derived from the input parameters
    """
    
    if resolution == '1080p':
        width, height = 1920, 1080
        title_fontsize = 120  # Bigger watermark
        subtitle_fontsize = 65
    else:  # vertical/shorts
        width, height = 1080, 1920
        title_fontsize = 85  # Bigger watermark
        subtitle_fontsize = 48
    
    # Create image
    img = Image.new('RGB', (width, height), color=(20, 20, 40))
    draw = ImageDraw.Draw(img)
    
    # Try to load fonts
    try:
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
            '/System/Library/Fonts/Helvetica.ttc',
            'C:\\Windows\\Fonts\\arial.ttf'
        ]
        
        title_font = None
        for font_path in font_paths:
            if os.path.exists(font_path):
                title_font = ImageFont.truetype(font_path, title_fontsize)
                subtitle_font = ImageFont.truetype(font_path, subtitle_fontsize)
                break
        
        if title_font is None:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
    except:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
    
    # Draw channel name
    title_x = width // 2
    title_y = height // 3
    draw.text((title_x, title_y), channel, fill='white', font=title_font, anchor='mm')
    
    # DYNAMIC subtitle lines from topic name
    # Split topic name intelligently
    topic_words = topic_name.split()
    
    # Group words into lines (max 3-4 words per line for readability)
    subtitle_lines = []
    current_line = []
    
    for word in topic_words:
        current_line.append(word)
        if len(current_line) >= 3 or len(' '.join(current_line)) > 20:
            subtitle_lines.append(' '.join(current_line))
            current_line = []
    
    if current_line:
        subtitle_lines.append(' '.join(current_line))
    
    # Add year range
    subtitle_lines.append(f"{start_year} - {end_year}")
    
    # Draw subtitle lines
    y_offset = height // 2 + 50
    line_spacing = subtitle_fontsize + 20
    
    for line in subtitle_lines:
        draw.text((width // 2, y_offset), line, fill='lightblue', font=subtitle_font, anchor='mm')
        y_offset += line_spacing
    
    # Save as temporary image
    temp_img_path = output_path.replace('.mp4', '.png')
    img.save(temp_img_path)
    
    # Convert to video clip
    intro_clip = ImageClip(temp_img_path, duration=duration)
    
    # Save as video with high quality settings
    intro_clip.write_videofile(
        output_path,
        codec='libx264',
        fps=30,  # Consistent 30fps
        preset='slow',
        bitrate='20000k',  # High bitrate for static intro
        ffmpeg_params=[
            '-crf', '15',  # Very high quality
            '-pix_fmt', 'yuv420p'
        ],
        logger=None
    )
    
    intro_clip.close()
    
    # Clean up temporary image
    if os.path.exists(temp_img_path):
        os.remove(temp_img_path)
    
    print(f"  📝 Intro lines: {subtitle_lines}")
    
    return output_path

def create_watermark_image(channel='@PlayOwnAi', resolution='1080p', output_path=None):
    """
    Create a large centered semi-transparent watermark covering ~70% of screen
    """
    if resolution == '1080p':
        width, height = 1920, 1080
        fontsize = 180  # Huge watermark covering ~70% screen
    else:  # vertical/shorts
        width, height = 1080, 1920
        fontsize = 140  # Huge watermark for vertical
    
    # Create transparent image
    img = Image.new('RGBA', (width, height), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Try to load fonts
    try:
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
            '/System/Library/Fonts/Helvetica.ttc',
            'C:\\Windows\\Fonts\\arial.ttf'
        ]
        
        watermark_font = None
        for font_path in font_paths:
            if os.path.exists(font_path):
                watermark_font = ImageFont.truetype(font_path, fontsize)
                break
        
        if watermark_font is None:
            watermark_font = ImageFont.load_default()
    except:
        watermark_font = ImageFont.load_default()
    
    # Position watermark at CENTER of screen
    bbox = draw.textbbox((0, 0), channel, font=watermark_font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # Center position
    text_x = (width - text_width) // 2
    text_y = (height - text_height) // 2
    
    # Draw large centered watermark with low opacity (70 = ~27% opacity, very subtle)
    draw.text((text_x, text_y), channel, fill=(255, 255, 255, 70), font=watermark_font)
    
    # Save watermark
    if output_path is None:
        output_path = f"/tmp/watermark_{resolution}.png"
    
    img.save(output_path)
    print(f"  💧 Large centered watermark created: {fontsize}px font, 27% opacity")
    
    return output_path

# ==========================================
# 7. PREPARE DATA VISUALIZATION
# ==========================================
print("\n📊 Preparing data visualization...")
df_viz = df.set_index(year_col).select_dtypes(include='number')

# Remove vowels from column names for compact display
print("📝 Compacting names (removing vowels)...")
original_names = df_viz.columns.tolist()
compact_names = [remove_vowels(name) for name in original_names]
name_mapping = dict(zip(original_names, compact_names))

# Show mapping
for orig, compact in name_mapping.items():
    if orig != compact:
        print(f"  {orig} => {compact}")

df_viz.columns = compact_names
df_viz.index = pd.to_datetime(df_viz.index.astype(int).astype(str), format='%Y')

# Dynamic title from CSV
title_text = "\n" + metadata['topic_name']

def get_timing(seconds_per_year, data_len):
    num_transitions = data_len - 1
    period_length = seconds_per_year * 1000
    steps = int(seconds_per_year * 30)
    return steps, period_length

def summary_func_year_only(values, ranks):
    dt = values.name
    return {
        'x': .95, 'y': .08,  # Position at top-right
        's': f'{dt.year}',
        'ha': 'right', 'va': 'top',
        'size': 90, 'color': 'yellow', 'weight': 'bold'
    }

# ==========================================
# 8. MATPLOTLIB SETUP
# ==========================================
plt.rcParams.update({
    'xtick.labeltop': True,
    'xtick.top': True,
    'xtick.labelbottom': False,
    'xtick.bottom': False,
    'axes.spines.top': True,
    'axes.spines.bottom': False,
    'figure.autolayout': False,
    'savefig.bbox': 'standard',
    'axes.titlepad': -10,
    'axes.titleweight': 'bold',
    'figure.subplot.top': 0.85
})

common_params = {
    "df": df_viz,
    "orientation": "h",
    "sort": "desc",
    "n_bars": 5,
    "fixed_order": False,
    "fixed_max": 100,
    "interpolate_period": True,
    "title": title_text,
    "bar_size": 0.75,
    "period_label": False,
}

# ==========================================
# 9. GENERATE VIDEOS WITH DYNAMIC NAMES
# ==========================================
print("\n🎥 Generating videos...")

videos_to_create = []

# FULL VIDEO (1080p)
print("\n[1/2] Full 1080p Video:")

# Create intro screen
print("  Creating intro screen...")
intro_full_path = f"{output_directory}/Intro_Full.mp4"
create_intro_screen_dynamic(
    intro_duration, 
    intro_full_path, 
    metadata['topic_name'],
    start_year,
    end_year,
    '1080p'
)
print(f"  ✓ Intro screen created")

# Create data visualization
print("  Creating data visualization...")
steps, period_length = get_timing(seconds_per_year_full, len(df_viz))  # Normal pace for quality
data_full_path = f"{output_directory}/Data_Full.mp4"

bcr.bar_chart_race(
    **common_params,
    period_summary_func=summary_func_year_only,
    steps_per_period=steps,
    period_length=period_length,
    filename=data_full_path,
    figsize=(17.4, 10.8),
    dpi=100,
    title_size=45,
    bar_label_size=50,
    tick_label_size=50
)
print(f"  ✓ Data visualization created")

# Combine intro + data
print("  Combining intro + data...")
intro_clip = VideoFileClip(intro_full_path)
data_clip = VideoFileClip(data_full_path)

# Create watermark for data visualization part only
watermark_path = f"{output_directory}/watermark_full.png"
create_watermark_image(channel='@PlayOwnAi', resolution='1080p', output_path=watermark_path)
watermark = ImageClip(watermark_path).set_duration(data_clip.duration).set_position("center")  # Center position

# Apply watermark to data clip
data_with_watermark = CompositeVideoClip([data_clip, watermark])

# Concatenate intro (no watermark) + data with watermark
full_video = concatenate_videoclips([intro_clip, data_with_watermark], method="compose")

# DYNAMIC OUTPUT NAME
full_video_path = f"{output_directory}/PlayOwnAiTrends_{metadata['file_prefix']}_1080p.mp4"
full_video.write_videofile(
    full_video_path, 
    codec='libx264',
    fps=30,  # Consistent frame rate
    preset='slow',  # Better quality encoding
    bitrate='25000k',  # High bitrate for maximum quality (~25 Mbps)
    audio=False,  # No audio yet
    ffmpeg_params=[
        '-crf', '15',  # Higher quality CRF (lower = better, 15 = very high quality)
        '-pix_fmt', 'yuv420p'
    ],
    logger=None
)
full_video.close()
intro_clip.close()
data_clip.close()
watermark.close()
data_with_watermark.close()

print(f"✓ Full video: {os.path.basename(full_video_path)}")
videos_to_create.append(('full', full_video_path, full_narration))

# SHORT VIDEO (Vertical)
print("\n[2/2] Short Vertical Video:")

# Create intro screen
print("  Creating intro screen...")
intro_short_path = f"{output_directory}/Intro_Short.mp4"
create_intro_screen_dynamic(
    intro_duration,
    intro_short_path,
    metadata['topic_name'],
    start_year,
    end_year,
    'vertical'
)
print(f"  ✓ Intro screen created")

# Create data visualization
print("  Creating data visualization...")
steps_short, period_short = get_timing(seconds_per_year_short, len(df_viz))  # Faster pace
data_short_path = f"{output_directory}/Data_Short.mp4"

bcr.bar_chart_race(
    **common_params,
    period_summary_func=summary_func_year_only,
    steps_per_period=steps_short,
    period_length=period_short,
    filename=data_short_path,
    figsize=(9.4, 19.0),
    dpi=100,
    title_size=24,  # Smaller for vertical
    bar_label_size=40,
    tick_label_size=40
)
print(f"  ✓ Data visualization created")

# Combine intro + data
print("  Combining intro + data...")
intro_clip_short = VideoFileClip(intro_short_path)
data_clip_short = VideoFileClip(data_short_path)

# Create watermark for data visualization part only
watermark_path_short = f"{output_directory}/watermark_short.png"
create_watermark_image(channel='@PlayOwnAi', resolution='vertical', output_path=watermark_path_short)
watermark_short = ImageClip(watermark_path_short).set_duration(data_clip_short.duration).set_position("center")  # Center position

# Apply watermark to data clip
data_with_watermark_short = CompositeVideoClip([data_clip_short, watermark_short])

# Concatenate intro (no watermark) + data with watermark
short_video = concatenate_videoclips([intro_clip_short, data_with_watermark_short], method="compose")

# DYNAMIC OUTPUT NAME
short_video_path = f"{output_directory}/PlayOwnAiTrends_{metadata['file_prefix']}_Shorts.mp4"
short_video.write_videofile(
    short_video_path, 
    codec='libx264',
    fps=30,  # Consistent frame rate
    preset='slow',  # Better quality encoding
    bitrate='18000k',  # High bitrate for shorts (~18 Mbps)
    audio=False,  # No audio yet
    ffmpeg_params=[
        '-crf', '15',  # High quality
        '-pix_fmt', 'yuv420p'
    ],
    logger=None
)
short_video.close()
intro_clip_short.close()
data_clip_short.close()
watermark_short.close()
data_with_watermark_short.close()

print(f"✓ Short video: {os.path.basename(short_video_path)}")
videos_to_create.append(('short', short_video_path, short_narration))

# ==========================================
# 10. GENERATE AUDIO
# ==========================================
print("\n🎙️  Generating audio...")

audio_files = {}
for video_type, _, narration in videos_to_create:
    audio_filename = f"Audio_{video_type.capitalize()}.mp3"
    audio_path = os.path.join(output_directory, audio_filename)
    
    print(f"  {audio_filename}...")
    # Use slow=True for slower, clearer speech that better matches video duration
    tts = gTTS(text=narration, lang='en', slow=True)
    tts.save(audio_path)
    audio_files[video_type] = audio_path

print("✓ Audio generated with slower speech for better timing")

# ==========================================
# 11. COMBINE VIDEO + AUDIO
# ==========================================
print("\n🎬 Adding audio to videos...")

final_videos = []

for video_type, video_path, narration in videos_to_create:
    audio_path = audio_files[video_type]
    
    # DYNAMIC FINAL OUTPUT NAME
    if video_type == 'full':
        output_path = f"{output_directory}/PlayOwnAiTrends_{metadata['file_prefix']}_1080p_FINAL.mp4"
    else:
        output_path = f"{output_directory}/PlayOwnAiTrends_{metadata['file_prefix']}_Shorts_FINAL.mp4"
    
    print(f"\n[{video_type.upper()}]")
    
    try:
        video = VideoFileClip(video_path)
        audio = AudioFileClip(audio_path)
        
        print(f"  Video: {video.duration:.1f}s | Audio: {audio.duration:.1f}s")
        
        # Adjust if needed - add buffer to ensure audio isn't cut off
        if audio.duration > video.duration:
            print(f"  Extending video to match audio duration...")
            extension_needed = audio.duration - video.duration + 1.0  # Add 1s buffer
            last_frame = video.to_ImageClip(t=video.duration - 0.1)
            last_frame = last_frame.set_duration(extension_needed)
            video = concatenate_videoclips([video, last_frame], method="compose")
            print(f"  New video duration: {video.duration:.1f}s")
        elif video.duration > audio.duration + 2.0:
            # If video is much longer than audio, trim it slightly
            print(f"  Video is longer, keeping small buffer...")
        
        # Add audio with gentle fade
        audio = audio.audio_fadein(0.5).audio_fadeout(1.5)
        final = video.set_audio(audio)
        
        # High quality rendering settings
        bitrate = "25000k" if video_type == 'full' else "18000k"
        print(f"  Rendering final video with high quality...")
        
        final.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            audio_bitrate='320k',  # High quality audio
            fps=30,  # Consistent 30fps
            bitrate=bitrate,
            preset='slow',  # Slower = better quality
            ffmpeg_params=[
                '-crf', '15',  # Very high quality (15-18 is near-lossless)
                '-pix_fmt', 'yuv420p',  # Pixel format for compatibility
                '-movflags', '+faststart'  # Fast start for web playback
            ],
            threads=4,
            logger=None
        )
        
        video.close()
        audio.close()
        final.close()
        
        file_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  ✅ Complete ({file_size:.1f} MB)")
        final_videos.append((video_type, output_path, file_size))
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()

# ==========================================
# 12. CLEANUP INTERMEDIATE FILES
# ==========================================
print("\n🧹 Cleaning up intermediate files...")

# List of patterns to keep
keep_patterns = ['_FINAL.mp4', '.txt']

# Get all files in output directory
all_files = os.listdir(output_directory)
removed_count = 0

for filename in all_files:
    filepath = os.path.join(output_directory, filename)
    
    # Skip if it's a directory
    if os.path.isdir(filepath):
        continue
    
    # Check if file should be kept
    should_keep = any(pattern in filename for pattern in keep_patterns)
    
    if not should_keep:
        try:
            os.remove(filepath)
            removed_count += 1
            print(f"  🗑️  Removed: {filename}")
        except Exception as e:
            print(f"  ⚠️  Could not remove {filename}: {e}")

print(f"✓ Cleaned up {removed_count} intermediate files")

# ==========================================
# 13. SUMMARY
# ==========================================
print("\n" + "="*70)
print("🎉 COMPLETE!")
print("="*70)
print(f"\n📂 Output Directory: {output_directory}")
print(f"📂 Version: {timestamp}\n")

print("📹 Final Videos:")
for vtype, path, size in final_videos:
    print(f"  ✓ {os.path.basename(path)} ({size:.1f} MB)")

print(f"\n✨ All content dynamically generated from CSV:")
print(f"   • Topic: {metadata['topic_name']}")
print(f"   • Years: {start_year} - {end_year}")
print(f"   • File prefix: {metadata['file_prefix']}")
print(f"   • Names compacted: Vowels removed")
print(f"   • Watermark: 70% screen, center, 27% opacity")
print(f"   • Quality: CRF 15 (Very High)")
print(f"   • Bitrate: 25Mbps (Full) / 18Mbps (Short)")
print("="*70)

# Save narration with dynamic names
narration_full_path = f"{output_directory}/PlayOwnAiTrends_{metadata['file_prefix']}_Narration_Full.txt"
narration_short_path = f"{output_directory}/PlayOwnAiTrends_{metadata['file_prefix']}_Narration_Short.txt"

with open(narration_full_path, 'w') as f:
    f.write(full_narration)
with open(narration_short_path, 'w') as f:
    f.write(short_narration)

print(f"\n📝 Narration files saved")
print(f"\n📦 Final output contains only:")
print(f"   • 2 FINAL video files (.mp4)")
print(f"   • 2 Narration text files (.txt)")