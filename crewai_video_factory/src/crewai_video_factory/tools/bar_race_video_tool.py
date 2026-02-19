# source .venv/bin/activate
# python --version
# Python 3.11.x only this version worked
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
    n_bars: Optional[int] = Field(default=None, description="Number of bars to display. None = auto (Shorts:9, HD:7)")

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

    def _load_label_mappings(self) -> dict:
        """Load label mappings from label_mappings.json (cached after first load)."""
        import json
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
                # Support nested {"bar_race_labels": {...}} or flat {"Label": "Short"} format
                self._label_mapping_cache = raw.get("bar_race_labels", raw)
                print(f"✅ Loaded {len(self._label_mapping_cache)} label mappings from label_mappings.json")
                return self._label_mapping_cache
            except Exception as e:
                print(f"⚠️  Could not load label_mappings.json: {e}. Using empty mapping.")
        else:
            print(f"⚠️  label_mappings.json not found in any expected location. No label trimming applied.")
        self._label_mapping_cache = {}
        return self._label_mapping_cache

    def _trim_label(self, label: str) -> str:
        """Trim labels using mappings loaded from label_mappings.json."""
        return self._load_label_mappings().get(label, label)

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
        n_bars_input = kwargs.get("n_bars") or None  # None = use format-based default

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
        df_viz.columns = [self._trim_label(col) for col in df_viz.columns]

        results = []

        for fmt in video_formats:
            try:
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
                        lbl.set_rotation(70)
                        lbl.set_ha('right')
                        lbl.set_va('center')
                    # Also re-enforce x-axis size in case bcr reset it
                    for lbl in ax.get_xticklabels():
                        lbl.set_fontsize(x_tick_label_size)

                pre_fig.canvas.mpl_connect('draw_event', on_draw)

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
                print(f"{fmt} Resolution: {int(fig_w*dpi)} x {int(fig_h*dpi)}")

                bcr.bar_chart_race(
                    df=df_viz,
                    filename=output_path,
                    orientation="h",
                    sort="desc",
                    n_bars=n_bars,
                    steps_per_period=int(seconds_per_period * 15),
                    period_length=int(seconds_per_period * 1000),
                    fig=pre_fig,
                    title=title_text,
                    period_label=False,
                    period_summary_func=period_summary_func,
                    bar_label_size=bar_label_size,
                    tick_label_size=tick_label_size,
                    title_size=title_size,
                    writer='ffmpeg',
                )
                plt.close(pre_fig)

                if os.path.exists(output_path):
                    # Post-process: re-encode with exact pixel dimensions
                    w_px = int(fig_w * dpi)
                    h_px = int(fig_h * dpi)
                    fixed_path = output_path.replace(".mp4", "_fixed.mp4")
                    os.system(
                        f'ffmpeg -y -i "{output_path}" '
                        f'-vf "scale={w_px}:{h_px}" '
                        f'-c:v libx264 -crf 18 -preset fast '
                        f'"{fixed_path}" -loglevel error'
                    )
                    if os.path.exists(fixed_path):
                        os.replace(fixed_path, output_path)
                    results.append(f"✅ {fmt}: {output_path}")

            except Exception as e:
                results.append(f"❌ {fmt}: {str(e)}")

        return "\n".join(results)
