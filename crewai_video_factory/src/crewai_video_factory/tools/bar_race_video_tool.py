from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, List, Optional
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import bar_chart_race as bcr
import warnings

# --- GLOBAL CONFIGURATION ---
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

class BarRaceInput(BaseModel):
    """Input for BarRaceVideoTool."""
    csv_filepath: str = Field(..., description="Absolute path to the source CSV file.")
    output_dir: str = Field(..., description="Output directory for video files.")
    title: str = Field(..., description="The title of the bar chart race.")
    video_formats: List[str] = Field(
        default=["Shorts"],
        description="Video formats to generate: HD, 2K, 4K, 8K, Shorts, ShortsHD, Shorts4K"
    )
    seconds_per_period: float = Field(default=4.0, description="Animation speed (seconds per period).")
    fps_hd_offset: float = Field(default=1.0, description="Multiplier for landscape formats (HD/2K/4K/8K). e.g. 1.27 makes HD 27% longer than Shorts.")
    n_bars: Optional[int] = Field(default=None, description="Number of bars to display. None = auto (Shorts:9, HD:7)")
    use_label_mappings: bool = Field(default=True, description="Apply label_mappings.json abbreviations to bar labels. Set false to show full names.")
    watermark_enabled: bool = Field(default=False, description="Overlay semi-transparent watermark text on video.")
    watermark_text: str = Field(default="@PlayOwnAi", description="Watermark text to display.")
    watermark_opacity: int = Field(default=60, ge=0, le=255, description="Watermark opacity (0=invisible, 255=fully opaque).")
    topic: str = Field(default=" ", description="Topic name for narration script.")
    channel: str = Field(default="PlayOwnAi", description="Channel name for subscribe CTA in narration.")
    audio_speed: float = Field(default=1.0, description="TTS playback speed for Shorts via atempo (0.5-2.0). 1.0=normal.")
    audio_speed_hd: float = Field(default=0.0, description="TTS playback speed for HD/landscape formats. 0.0 = fall back to audio_speed.")

class BarRaceVideoTool(BaseTool):
    name: str = "Bar Race Video Tool"
    description: str = "Creates bar chart race videos in multiple formats from a CSV file."
    args_schema: Type[BaseModel] = BarRaceInput

    def _get_video_dimensions(self, video_format: str):
        fmt = video_format.strip()

        resolutions_px = {
            "HD": (1920, 1080),
            "2K": (2560, 1440),
            "4K": (3840, 2160),
            "8K": (7680, 4320),
            "Shorts": (1080, 1920),
            "ShortsHD": (1080, 1920),
            "Shorts4K": (2160, 3840),
        }

        dpi = 100

        if fmt not in resolutions_px:
            fmt = "HD"

        w_px, h_px = resolutions_px[fmt]

        # Ensure pixel dimensions are divisible by 2 (required by ffmpeg h264 codec).
        w_px = w_px if w_px % 2 == 0 else w_px - 1
        h_px = h_px if h_px % 2 == 0 else h_px - 1

        return (w_px / dpi, h_px / dpi)

    def _load_label_mappings(self, use_label_mappings: bool = True) -> dict:
        """Load label mappings from label_mappings.json (cached after first load)."""
        import json
        if not use_label_mappings:
            if not getattr(self, '_label_disabled_logged', False):
                print("ℹ️  Label mappings DISABLED (use_label_mappings=false) — showing full bar names.")
                object.__setattr__(self, '_label_disabled_logged', True)
            return {}
        if hasattr(self, '_label_mapping_cache'):
            return self._label_mapping_cache
        # Search for label_mappings.json in multiple locations:
        # 1. Same dir as this tool file
        # 2. Project data/ folder (walk up from tool to find project root)
        tool_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(tool_dir, "label_mappings.json"),                          # next to tool
            os.path.join(tool_dir, "..", "data", "label_mappings.json"),            # ../data/
            os.path.join(tool_dir, "..", "..", "data", "label_mappings.json"),      # ../../data/
            os.path.join(tool_dir, "..", "..", "..", "data", "label_mappings.json"),# ../../../data/
        ]
        json_path = next((p for p in candidates if os.path.exists(os.path.normpath(p))), None)
        if json_path:
            json_path = os.path.normpath(json_path)
        if json_path and os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                # Support nested { "bar_race_labels": {...}} or flat { "Label": "Short" } format
                self._label_mapping_cache = raw.get("bar_race_labels", raw)
                print(f"✅ Loaded {len(self._label_mapping_cache)} label mappings from label_mappings.json")
                return self._label_mapping_cache
            except Exception as e:
                print(f"⚠️  Could not load label_mappings.json: {e}. Using empty mapping.")
        else:
            print(f"⚠️  label_mappings.json not found in any expected location. No label trimming applied.")
        self._label_mapping_cache = {}
        return self._label_mapping_cache

    def _trim_label(self, label: str, use_label_mappings: bool = True) -> str:
        """Trim labels using mappings loaded from label_mappings.json."""
        return self._load_label_mappings(use_label_mappings).get(label, label)

    def _run(self, **kwargs) -> str:
        # --- 1. SETUP FFMPEG ---
        try:
            import static_ffmpeg
            static_ffmpeg.add_paths()
            matplotlib.rcParams["animation.ffmpeg_path"] = "ffmpeg"
        except Exception:
            matplotlib.rcParams["animation.ffmpeg_path"] = "/usr/bin/ffmpeg"

        # --- 2. CLEAN INPUTS ---
        csv_filepath = kwargs.get("csv_filepath")
        output_dir = kwargs.get("output_dir")
        title_text = kwargs.get("title", "Data Visualization").strip()
        video_formats = kwargs.get("video_formats", ["Shorts"])
        seconds_per_period = kwargs.get("seconds_per_period", 4.0)
        fps_hd_offset = float(kwargs.get("fps_hd_offset", 1.0))
        n_bars_input = kwargs.get("n_bars") or None  # None = use format-based default
        use_label_mappings = kwargs.get("use_label_mappings", True)
        watermark_enabled = kwargs.get("watermark_enabled", False)
        watermark_text    = kwargs.get("watermark_text", "@PlayOwnAi")
        watermark_opacity = int(kwargs.get("watermark_opacity", 60))
        topic             = kwargs.get("topic", " ")
        channel           = kwargs.get("channel", "PlayOwnAi")
        audio_speed       = float(kwargs.get("audio_speed", 1.0))
        audio_speed_hd    = float(kwargs.get("audio_speed_hd", 0.0))

        if isinstance(video_formats, str):
            video_formats = [video_formats.strip()]

        # --- 3. LOAD DATA ---
        csv_path = os.path.abspath(csv_filepath)
        if not os.path.exists(csv_path):
            return "❌ CSV file not found"
        os.makedirs(output_dir, exist_ok=True)

        df = pd.read_csv(csv_path)
        year_col = df.columns[0]
        df_viz = df.set_index(year_col).select_dtypes(include="number")
        df_viz.index = pd.to_datetime(df_viz.index.astype(str), format="%Y")
        df_viz.columns = [self._trim_label(col, use_label_mappings) for col in df_viz.columns]

        results = []

        for fmt in video_formats:
            try:
                # ✅ SMART SKIP — check what already exists
                silent_video = os.path.join(output_dir, f"bar_race_{fmt}.mp4")
                audio_file   = os.path.join(output_dir, f"bar_race_{fmt}_audio.mp3")
                final_merged = os.path.join(output_dir, f"bar_race_{fmt}_with_audio.mp4")

                # Skip everything if final merged exists
                if os.path.exists(final_merged):
                    results.append(f"⏭️ {fmt}: Skipped (final exists: {os.path.basename(final_merged)})")
                    continue

                # Get figure size (in inches)
                figsize = self._get_video_dimensions(fmt)

                dpi = 100
                fig_w, fig_h = figsize
                width_px = fig_w * dpi

                # Scale relative to 1920 width
                scale_factor = width_px / 1920

                # Dynamic font scaling
                # Per-format font multiplier: HD -10%, Shorts/portrait +10%, others neutral
                is_portrait = fig_h > fig_w
                font_mult = 1.10 if is_portrait else 0.90
                # Format-aware n_bars: Shorts=9, HD/landscape=7 (user override takes priority)
                n_bars = n_bars_input if n_bars_input else (9 if is_portrait else 7)

                title_size       = int(54  * scale_factor * font_mult)
                bar_label_size   = int(43  * scale_factor * font_mult)  # value numbers at bar end
                tick_label_size  = int(22  * scale_factor * font_mult)  # passed to bcr (will be overridden below)
                x_tick_label_size= int(43  * scale_factor * font_mult)  # x-axis scale numbers (0, 25, 50...)
                bar_name_size    = int(27  * scale_factor * font_mult)  # y-axis bar names — applied via draw_event
                period_label_size= int(65  * scale_factor * font_mult)

                plt.rcParams.update({
                    "axes.titlesize": title_size,
                    "axes.titleweight": "bold",
                    "axes.titlepad": 40,
                    "figure.autolayout": False,
                    "figure.constrained_layout.use": False,
                })

                def period_summary_func(values, ranks):
                    return {
                        'x': 0.97,
                        'y': 0.08,
                        's': str(values.name.year),
                        'ha': 'right',
                        'size': period_label_size,
                        'color': '#FF4500',
                        'weight': 'bold'
                    }

                # Pre-configure figure: x-axis ticks on TOP, y-axis labels large + 45°
                pre_fig, pre_ax = plt.subplots(figsize=figsize, dpi=dpi)

                # X-axis: move to top with correct size
                pre_ax.xaxis.set_ticks_position('top')
                pre_ax.xaxis.set_label_position('top')
                pre_ax.tick_params(
                    axis='x',
                    which='both',
                    bottom=False,
                    top=True,
                    labelbottom=False,
                    labeltop=True,
                    labelsize=x_tick_label_size,
                    pad=-x_tick_label_size * 0.4,
                )

                # Hook into matplotlib's draw cycle to enforce y-axis label size + rotation
                # on every frame (bcr resets these each update).
                def on_draw(event):
                    ax = pre_fig.axes[0] if pre_fig.axes else None
                    if ax is None:
                        return
                    for lbl in ax.get_yticklabels():
                        lbl.set_fontsize(bar_name_size)
                        lbl.set_rotation(77)
                        lbl.set_ha('right')
                        lbl.set_va('center')
                    # Also re-enforce x-axis size in case bcr reset it
                    for lbl in ax.get_xticklabels():
                        lbl.set_fontsize(x_tick_label_size)

                pre_fig.canvas.mpl_connect('draw_event', on_draw)

                # --- WATERMARK ---
                if watermark_enabled:
                    self._add_watermark(pre_fig, watermark_text, watermark_opacity,
                                        int(fig_w * dpi), int(fig_h * dpi))

                # Reserve space at top for suptitle
                # Landscape (HD/2K/4K/8K): tight margins so bars use full width.
                # Portrait (Shorts): more left room for rotated bar names.
                if is_portrait:
                    top_margin   = 0.93
                    left_margin  = 0.12
                    right_margin = 0.95
                else:
                    top_margin   = 0.85
                    left_margin  = 0.08
                    right_margin = 0.97
                pre_fig.subplots_adjust(top=top_margin, bottom=0.02, left=left_margin, right=right_margin)
                # y set to just above top_margin so title sits ~1px above axes
                title_y = top_margin + (1.0 - top_margin) * 0.5
                pre_fig.suptitle(
                    title_text,
                    fontsize=title_size,
                    fontweight="bold",
                    y=title_y,
                    va='bottom',
                )

                output_path = os.path.join(output_dir, f"bar_race_{fmt}.mp4")
                n_periods = len(df_viz)
                fmt_spp = seconds_per_period if is_portrait else seconds_per_period * fps_hd_offset
                if not is_portrait and fps_hd_offset != 1.0:
                    print(f"   ⚙️  [{fmt}] spp {seconds_per_period:.2f}s × fps_hd_offset {fps_hd_offset} = {fmt_spp:.2f}s/period")
                total_frames = n_periods * int(fmt_spp * 15)
                est_secs = total_frames / 15
                print(f"")
                print(f"🎬 [{fmt}] Starting render")
                print(f"   Resolution : {int(fig_w*dpi)} x {int(fig_h*dpi)}")
                print(f"   Periods    : {n_periods}  |  spp: {fmt_spp:.2f}s  |  Frames: {total_frames}")
                print(f"   ⏱️  Estimated: ~{est_secs/60:.1f} min ({est_secs:.0f}s) — please wait …")

                # If silent video exists but merged doesn't, skip rendering
                if os.path.exists(silent_video):
                    print(f"   ⏭️ [{fmt}] Silent video exists — skipping render")
                    output_path = silent_video
                else:
                    import time as _time
                    import threading as _threading
                    t_start = _time.time()
                    _stop_ticker = _threading.Event()

                    def _progress_bar_thread(stop_event, est_total_secs, label):
                        """
                        Time-based tqdm progress bar in a background thread.
                        Advances by real elapsed time (bcr gives no frame callbacks).
                        Falls back to plain-text ticker if tqdm not installed.
                        """
                        try:
                            from tqdm import tqdm
                            bar = tqdm(
                                total=int(est_total_secs),
                                desc=f"   🎬 [{label}] Rendering",
                                unit="s",
                                bar_format=(
                                    "{desc}: {percentage:3.0f}%|{bar:30}|  "
                                    "{n:.0f}/{total:.0f}s  "
                                    "[{elapsed} <{remaining}] "
                                ),
                                dynamic_ncols=True,
                                leave=True,
                            )
                            last_n = 0
                            while not stop_event.is_set():
                                stop_event.wait(0.5)
                                elapsed = _time.time() - t_start
                                new_n = min(int(elapsed), int(est_total_secs))
                                if new_n > last_n:
                                    bar.update(new_n - last_n)
                                    last_n = new_n
                            # Fill to 100% on completion
                            if last_n < int(est_total_secs):
                                bar.update(int(est_total_secs) - last_n)
                            bar.close()
                        except ImportError:
                            # tqdm not installed — plain-text fallback every 5s
                            while not stop_event.is_set():
                                stop_event.wait(5)
                                if not stop_event.is_set():
                                    elapsed = _time.time() - t_start
                                    pct = min(100, int(elapsed / est_total_secs * 100)) if est_total_secs else 0
                                    remaining = max(0, est_total_secs - elapsed)
                                    print(
                                        f"   ⏳ [{label}] Rendering … {elapsed:.0f}s elapsed  "
                                        f"| ~{pct}% | ~{remaining:.0f}s remaining"
                                    )

                    ticker_thread = _threading.Thread(
                        target=_progress_bar_thread,
                        args=(_stop_ticker, est_secs, fmt),
                        daemon=True,
                    )
                    ticker_thread.start()

                    try:
                        bcr.bar_chart_race(
                            df=df_viz,
                            filename=output_path,
                            orientation="h",
                            sort="desc",
                            n_bars=n_bars,
                            steps_per_period=int(fmt_spp * 15),
                            period_length=int(fmt_spp * 1000),
                            fig=pre_fig,
                            title=title_text,
                            period_label=False,
                            period_summary_func=period_summary_func,
                            bar_label_size=bar_label_size,
                            tick_label_size=tick_label_size,
                            title_size=title_size,
                            writer='ffmpeg',
                        )
                    finally:
                        _stop_ticker.set()
                        ticker_thread.join(timeout=3)
                    plt.close(pre_fig)
                    elapsed = _time.time() - t_start
                    print(f"   ✅ Render done in {elapsed:.0f}s ({elapsed/60:.1f} min)")

                    if os.path.exists(output_path):
                        w_px = int(fig_w * dpi)
                        h_px = int(fig_h * dpi)
                        hold_secs = fmt_spp * 2
                        print(f"   🔧 Re-encoding {w_px}x{h_px}, holding last frame {hold_secs:.1f}s …")
                        fixed_path = output_path.replace(".mp4", "_fixed.mp4")
                        os.system(
                            f'ffmpeg -y -i "{output_path}" '
                            f'-vf "scale={w_px}:{h_px},tpad=stop_mode=clone:stop_duration={hold_secs:.2f}" '
                            f'-c:v libx264 -crf 18 -preset fast '
                            f'"{fixed_path}" -loglevel error'
                        )
                        if os.path.exists(fixed_path):
                            os.replace(fixed_path, output_path)

                # ── Audio: generate TTS synced to video duration ───────
                if os.path.exists(output_path):  # audio always generated with video
                    video_dur   = self._get_duration(output_path)
                    audio_path  = os.path.join(output_dir, f"bar_race_{fmt}_audio.mp3")
                    final_path  = os.path.join(output_dir, f"bar_race_{fmt}_with_audio.mp4")

                    # Shorts = concise narration + audio_speed
                    # HD/landscape = full narration with data points + audio_speed_hd
                    _spd = audio_speed if is_portrait else (audio_speed_hd if audio_speed_hd > 0.0 else audio_speed)
                    narration = self._build_narration(
                        df_viz, topic, channel,
                        with_points=not is_portrait    # Shorts=short, HD=full with values
                    )

                    # Save narration as cc_en.txt alongside video
                    cc_path = os.path.join(output_dir, f"bar_race_{fmt}_cc_en.txt")
                    with open(cc_path, 'w', encoding='utf-8') as _f:
                        _f.write(narration)
                    print(f"[BarRace] 📝 Narration saved: {cc_path} ({len(narration)} chars)")

                    self._generate_tts(narration, audio_path, video_dur, _spd)
                    if os.path.exists(audio_path):
                        self._merge_audio_video(output_path, audio_path, final_path, video_dur)
                        merged_kb = os.path.getsize(final_path) // 1024 if os.path.exists(final_path) else 0
                        kb = os.path.getsize(output_path) // 1024
                        results.append(
                            f"✅ {fmt}: {output_path} ({kb} KB)  "
                            f"+ audio → bar_race_{fmt}_with_audio.mp4 ({merged_kb} KB)  "
                            f"[{len(narration.split())} words, speed={_spd}]"
                        )
                    else:
                        kb = os.path.getsize(output_path) // 1024
                        results.append(f"✅ {fmt}: {output_path} ({kb} KB) [audio failed]")
                else:
                    kb = os.path.getsize(output_path) // 1024 if os.path.exists(output_path) else 0
                    results.append(f"✅ {fmt}: {output_path} ({kb} KB)")

            except Exception as e:
                results.append(f"❌ {fmt}: {str(e)}")

        return "\n".join(results)

    # ──────────────────────────────────────────────────────────────────
    def _build_narration(self, df_viz, topic: str, channel: str,
                         with_points: bool = False) -> str:
        """
        Build year-by-year narration matched to audio_tool.py logic.
        with_points=False → concise Shorts version (fewer words, faster pace)
        with_points=True  → full HD version (leader + value + context sentence)
        """
        topic_str = topic if topic else "this topic"

        # Derive start/end years from index
        years = [p.year if hasattr(p, 'year') else int(str(p)) for p in df_viz.index]
        start_year = years[0]
        end_year   = years[-1]

        if not with_points:
            parts = [
                f"{topic_str} Race {start_year} to {end_year}. ",
                "Basic trending idea. Let's go year by year. ",
            ]
        else:
            parts = [
                f"Today, we're exploring the {topic_str} Race from {start_year} to {end_year}. ",
                "This is for a basic idea about trending. ",
                "Let's see how the landscape evolved, year by year. ",
            ]

        for period, row in df_viz.iterrows():
            year       = period.year if hasattr(period, 'year') else int(str(period))
            sorted_row = row.dropna().sort_values(ascending=False)
            if sorted_row.empty:
                continue
            leader     = sorted_row.index[0]
            value      = int(sorted_row.iloc[0])

            if value == 0:
                parts.append(f"{year}. Race not yet begun. " if not with_points
                             else f"{year}. The race has not yet begun. ")
            elif value <= 20:
                parts.append(f"{year}. {leader} leads. Market forming. " if not with_points
                             else f"{year}. {leader} leads with {value} points. The market is forming. ")
            elif value <= 40:
                parts.append(f"{year}. {leader} leads. Gaining traction. " if not with_points
                             else f"{year}. {leader} leads with {value} points. Gaining traction. ")
            elif value <= 70:
                parts.append(f"{year}. {leader} leads. Showing strength. " if not with_points
                             else f"{year}. {leader} leads with {value} points. Showing real strength. ")
            else:
                parts.append(f"{year}. {leader} dominates. " if not with_points
                             else f"{year}. {leader} dominates with {value} points. ")

        final_row  = df_viz.iloc[-1].dropna().sort_values(ascending=False)
        final_lead = final_row.index[0] if not final_row.empty else "the leader"

        if with_points:
            parts.extend([
                f"And that brings us to {end_year}, where {final_lead} continues to lead the pack. ",
                "The evolution of technology and trends never stops. ",
                f" Next Basic definition. ",
            ])
        else:
            parts.extend([
                f"{end_year}. {final_lead} leads the pack. ",
                "Evolution continues. ",
                f"Basic definition. ",
            ])

        return "  ".join(parts)

    # ──────────────────────────────────────────────────────────────────
    def _get_duration(self, video_path: str) -> float:
        """Get video duration in seconds via ffprobe."""
        import subprocess
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True
        )
        try:
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    # ──────────────────────────────────────────────────────────────────
    def _generate_tts(self, text: str, audio_path: str, video_dur: float,
                      audio_speed: float = 1.0):
        """
        Generate TTS MP3 and apply audio_speed preference (same as audio_tool.py).

        Strategy:
        - Apply audio_speed directly as atempo (user clarity preference).
        - If the resulting audio is longer than video_dur → slow it down
          a bit more so it fits (avoids cut-off speech).
        - If shorter → leave it; _merge_audio_video pads with silence.
        - This avoids the "compounding sync×speed" bug that made Shorts
          audio impossibly fast.
        """
        import subprocess, os
        try:
            from gtts import gTTS
        except ImportError:
            print("[BarRace] ⚠️  gTTS not installed — no audio. Run: pip install gTTS")
            return

        def atempo_chain(ratio: float) -> str:
            """Build atempo filter string, chaining if outside 0.5–2.0."""
            ratio = max(0.25, min(4.0, ratio))
            if ratio < 0.5:
                return f"atempo=0.5000,atempo={ratio/0.5:.4f}"
            elif ratio > 2.0:
                return f"atempo=2.0000,atempo={ratio/2.0:.4f}"
            return f"atempo={ratio:.4f}"

        tmp = audio_path.replace('.mp3', '_raw.mp3')
        try:
            print(f"[BarRace] 🔊 Generating TTS ({len(text)} chars, speed={audio_speed}) ...")
            slow_mode = audio_speed <= 0.85
            tts = gTTS(text=text, lang='en', slow=slow_mode)
            tts.save(tmp)

            raw_dur = self._get_duration(tmp)
            if raw_dur <= 0:
                os.rename(tmp, audio_path)
                return

            # Step 1: apply user speed preference
            final_ratio = audio_speed

            # Step 2: if speech still won't fit in video, slow it down just enough
            adjusted_dur = raw_dur / max(audio_speed, 0.01)
            if adjusted_dur > video_dur * 1.05:          # >5% overflow
                fit_ratio = raw_dur / max(video_dur, 1)  # compress to fit
                final_ratio = fit_ratio
                print(f"[BarRace] ⚠️  Narration too long ({adjusted_dur:.1f}s > {video_dur:.1f}s video)  "
                      f"— auto-compressing to fit: atempo={fit_ratio:.3f}")
            else:
                print(f"[BarRace] 🔊 TTS {raw_dur:.1f}s, video {video_dur:.1f}s,  "
                      f"atempo={final_ratio:.3f} → est {raw_dur/final_ratio:.1f}s  "
                      f"({'padded with silence' if raw_dur/final_ratio < video_dur else 'fits'})")

            af = atempo_chain(final_ratio)
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp, "-filter:a", af, audio_path],
                capture_output=True, check=False
            )
            if os.path.exists(tmp):
                os.remove(tmp)
            if result.returncode != 0:
                print(f"[BarRace] ⚠️  atempo failed: {result.stderr.decode()[:120]}")
        except Exception as e:
            print(f"[BarRace] ⚠️  TTS error: {e}")
            if os.path.exists(tmp):
                os.rename(tmp, audio_path)

    # ──────────────────────────────────────────────────────────────────
    def _merge_audio_video(self, video_path: str, audio_path: str,
                           output_path: str, video_dur: float):
        """Merge TTS audio into bar race video; pad audio with silence if shorter."""
        import subprocess
        print(f"[BarRace] 🎬 Merging audio+video → {os.path.basename(output_path)}")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac",
            "-filter_complex", f"[1:a]apad,atrim=duration={video_dur:.3f}[aout]",
            "-map", "0:v", "-map", "[aout]",
            output_path
        ], capture_output=True, check=False)
        if result.returncode != 0:
            print(f"[BarRace] ⚠️  merge failed: {result.stderr.decode()[:150]}")

    def _add_watermark(self, fig, text: str, opacity: int, width_px: int, height_px: int):
        """
        Add a semi-transparent centered watermark text to a matplotlib figure
        using a PIL RGBA image composited as a figimage.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
            import numpy as np

            # Create transparent RGBA canvas same size as figure
            wm_img = Image.new('RGBA', (width_px, height_px), (0, 0, 0, 0))
            draw = ImageDraw.Draw(wm_img)

            # Font size: ~6% of width
            font_size = max(24, int(width_px * 0.06))
            font_paths = [
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
                '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
                '/System/Library/Fonts/Helvetica.ttc',
                'C:\\Windows\\Fonts\\arialbd.ttf',
            ]
            font = None
            for fp in font_paths:
                if os.path.exists(fp):
                    try:
                        font = ImageFont.truetype(fp, font_size)
                        break
                    except Exception:
                        continue
            if font is None:
                font = ImageFont.load_default()

            # Measure text and center it
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = (width_px - tw) // 2
            ty = (height_px - th) // 2

            # Draw watermark with configured opacity
            draw.text((tx, ty), text, fill=(255, 255, 255, opacity), font=font)

            # Convert to numpy RGBA array and overlay on figure
            wm_array = np.array(wm_img).astype(float) / 255.0  # shape: (H, W, 4)

            # figimage: bottom-left origin, so flip vertically
            wm_array = wm_array[::-1]

            fig.figimage(wm_array, xo=0, yo=0, alpha=1.0, zorder=10, origin='lower')

        except ImportError:
            print("⚠️  Pillow not installed — watermark skipped. Run: pip install Pillow")
        except Exception as e:
            print(f"⚠️  Watermark error: {e}")
