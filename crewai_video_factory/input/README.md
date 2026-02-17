# Input Configuration Guide

## How to Use

1. **Edit `data.json`** with your desired settings
2. **Run the factory**: `crewai run`
3. **Videos will be generated** in `output/` directory

## Configuration Examples

### Example 1: Quick YouTube Shorts (Bar Race)
```json
{
  "topic": "AI Frameworks",
  "start": 2020,
  "end": 2024,
  "animation_styles": ["bar"],
  "video_formats": ["Shorts"],
  "fps": 1.0,
  "audio_enabled": true,
  "merge_audio_video": true,
  "generate_youtube_metadata": true
}
```

### Example 2: Multiple Formats & Styles
```json
{
  "topic": "Programming Languages Evolution",
  "start": 2015,
  "end": 2026,
  "animation_styles": ["bar", "line", "bubble"],
  "video_formats": ["Shorts", "HD", "4K"],
  "fps": 0.5,
  "audio_enabled": true,
  "merge_audio_video": true,
  "generate_youtube_metadata": true
}
```

### Example 3: Fast Development (No Audio)
```json
{
  "topic": "Tech Market Share",
  "animation_styles": ["bar"],
  "video_formats": ["Shorts"],
  "fps": 2.0,
  "audio_enabled": false,
  "merge_audio_video": false,
  "generate_youtube_metadata": false
}
```

## Field Descriptions

| Field | Type | Options | Description |
|-------|------|---------|-------------|
| `topic` | string | Any | Video topic (used for research & titles) |
| `start` | integer | 1900+ | Start year for data |
| `end` | integer | 1900+ | End year for data |
| `granularity` | string | yearly, monthly, daily | Data time granularity |
| `animation_styles` | array | bar, line, bubble, pie, stream, map | Animation types |
| `video_formats` | array | HD, 2K, 4K, 8K, Shorts, ShortsHD, Shorts4K | Output formats |
| `fps` | float | 0.1-30.0 | Animation speed (higher = faster) |
| `use_existing_csv` | boolean | true/false | Skip research, use existing CSV |
| `video_enabled` | boolean | true/false | Generate videos |
| `audio_enabled` | boolean | true/false | Generate audio narration |
| `audio_speed` | float | 0.7-1.3 | Speech speed (0.7=slow, 1.3=fast) |
| `merge_audio_video` | boolean | true/false | Combine audio + video |
| `generate_youtube_metadata` | boolean | true/false | Create YouTube metadata |

## Common Issues

**Q: "Configuration file not found"**
- A: Create `input/data.json` in project root

**Q: "Invalid JSON"**
- A: Check JSON syntax at https://jsonlint.com/

**Q: Videos take too long**
- A: Reduce `fps` value (0.5 = slower, more frames)
- A: Disable `audio_enabled` and `merge_audio_video`

**Q: Audio out of sync**
- A: Increase `audio_speed` to 1.0-1.2

## Advanced: CLI Override

Override `data.json` via command line:
```bash
python main.py '{"topic": "My Custom Topic", "fps": 2.0}'
```
```

---

## **Directory Structure**
```
crewai_video_factory/
├── input/
│   ├── data.json                 # ✅ USER EDITS THIS
│   ├── data.schema.json          # Reference documentation
│   └── README.md                 # User guide
├── src/
│   └── crewai_video_factory/
│       ├── main.py               # Updated to load JSON
│       ├── crew.py
│       └── tools/
├── output/
│   └── [generated files]
└── config/