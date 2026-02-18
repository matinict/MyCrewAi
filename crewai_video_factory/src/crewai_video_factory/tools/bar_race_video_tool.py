# source .venv/bin/activate
# python --version
# Python 3.11.x only this version worked
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, List
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import bar_chart_race as bcr
import warnings
matplotlib.rcParams["animation.writer"] = "ffmpeg"
matplotlib.rcParams["animation.ffmpeg_path"] = "/usr/bin/ffmpeg"
warnings.filterwarnings("ignore", category=UserWarning)

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
    n_bars: int = Field(default=5, description="Number of bars to display.")

class BarRaceVideoTool(BaseTool):
    name: str = "Bar Race Video Tool"
    description: str = "Creates bar chart race videos in multiple formats from a CSV file."
    args_schema: Type[BaseModel] = BarRaceInput

    def _get_video_dimensions(self, video_format: str):
        """Return figsize in INCHES for target pixel resolution at dpi=96."""
        fmt = video_format.strip()

        # Target resolutions in pixels
        resolutions_px = {
            "HD": (1920, 1080),
            "2K": (2560, 1440),
            "4K": (3840, 2160),
            "8K": (7680, 4320),
            "Shorts": (1080, 1920),   # vertical
            "ShortsHD": (1080, 1920), # same as Shorts
            "Shorts4K": (2160, 3840), # vertical 4K
        }

        dpi = 96
        if fmt in resolutions_px:
            w_px, h_px = resolutions_px[fmt]
            return (w_px / dpi, h_px / dpi)

        # Fallback: 16:9 HD-like
        return (12.0, 6.75)  # = 1152×648 px

    def _get_label_mapping(self):
        """Load label mappings from data/label_mappings.json (cleaned)."""
        import json
        mapping_path = "data/label_mappings.json"

        if os.path.exists(mapping_path):
            try:
                with open(mapping_path, 'r') as f:
                    data = json.load(f)
                    # Use exact key without spaces
                    return data.get("bar_race_labels", {})
            except Exception as e:
                print(f"⚠️ Failed to load label mappings: {e}")

        # Fallback mapping (no trailing spaces!)
        return {
            "JavaScript": "JS",
            "Microsoft": "MS",
            "Google": "Gle",
            "Amazon": "AMZ",
            "Apple": "APL",
            "Meta": "MTA",
            "NVIDIA": "NVD",
            "Tesla": "TS",
            "OpenAI": "OI",
            "Anthropic": "AN",
            "Transformer": "TFormer",
            "Shiba Inu": "SHIB"
        }

    def _trim_label(self, label: str, style: str) -> str:
        """Trim labels for bar race videos only."""
        if style == "bar":
            mapping = self._get_label_mapping()
            return mapping.get(label, label)
        return label

    def _run(self, **kwargs) -> str:
        # --- Clean inputs ---
        csv_filepath = kwargs.get("csv_filepath")
        output_dir = kwargs.get("output_dir")
        title = kwargs.get("title")
        video_formats = kwargs.get("video_formats", ["Shorts"])
        seconds_per_period = kwargs.get("seconds_per_period", 4.0)
        n_bars = kwargs.get("n_bars", 5)

        # Normalize
        if isinstance(video_formats, str):
            video_formats = [video_formats.strip()]
        else:
            video_formats = [f.strip() for f in video_formats]
        title = title.strip() or "Bar Race Visualization"

        # --- Validate ---
        csv_path = os.path.abspath(csv_filepath)
        if not os.path.exists(csv_path):
            return "❌ CSV file not found"
        os.makedirs(output_dir, exist_ok=True)

        # --- Load CSV ---
        df = pd.read_csv(csv_path)
        if df.empty or len(df.columns) < 2:
            return "❌ Invalid CSV structure"

        year_col = df.columns[0]
        df_viz = df.set_index(year_col).select_dtypes(include="number")
        df_viz.index = pd.to_datetime(df_viz.index.astype(str), format="%Y")

        # --- Apply label shortening ---
        original_cols = df_viz.columns.tolist()
        compact_cols = [self._trim_label(col, "bar") for col in original_cols]
        if original_cols != compact_cols:
            print(f"📝 Compacting: {dict(zip(original_cols, compact_cols))}")
            df_viz.columns = compact_cols

        results = []
        errors = []

        for fmt in video_formats:
            try:
                # Get correct figsize
                figsize = self._get_video_dimensions(fmt)
                is_vertical = fmt.startswith("Shorts")

                title_size = 28 if is_vertical else 36
                bar_label_size = 40 if is_vertical else 50
                tick_label_size = 40 if is_vertical else 50
                bar_size = 0.85 if is_vertical else 0.75

                # Layout (tight left, scale on top)
                plt.rcParams.update({
                    "figure.subplot.left": 0.05,
                    "figure.subplot.right": 0.98,
                    "figure.subplot.top": 0.45,
                    "figure.subplot.bottom": 0.10,
                    "xtick.labeltop": True,
                    "xtick.top": True,
                    "xtick.labelbottom": False,
                    "xtick.bottom": False,
                    "axes.titlelocation": "left",
                    "axes.titlepad": 50,
                    "axes.titleweight": "bold",
                })

                # Dynamic year (centered, bold, orange)
                def period_summary_func(values, ranks):
                    year = values.name.year
                    return {
                        'x': 0.5,
                        'y': 0.965,
                        's': str(year),
                        'ha': 'center',
                        'va': 'top',
                        'size': title_size * 1.1,
                        'color': '#FF4500',
                        'weight': 'bold',
                        'zorder': 100,
                        'bbox': dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7, edgecolor='none')
                    }

                # ✅ NEW: Simple filename (no double pattern)
                output_path = os.path.join(output_dir, f"bar_race_{fmt}.mp4")

                # Render
                bcr.bar_chart_race(
                    df=df_viz,
                    filename=output_path,
                    orientation="h",
                    sort="desc",
                    n_bars=n_bars,
                    fixed_order=False,
                    fixed_max=True,
                    interpolate_period=True,
                    steps_per_period=int(seconds_per_period * 15),
                    period_length=int(seconds_per_period * 1000),
                    figsize=figsize,
                    dpi=96,
                    bar_size=bar_size,

                    title=title,
                    title_size=title_size,
                    period_label=False,
                    period_summary_func=period_summary_func,
                    bar_label_size=bar_label_size,
                    tick_label_size=tick_label_size,
                )

                if os.path.exists(output_path):
                    size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    results.append(f"✅ {fmt}: {output_path} ({size_mb:.1f} MB)")
                else:
                    errors.append(f"❌ {fmt}: failed to save")
            except Exception as e:
                errors.append(f"❌ {fmt}: {str(e)}")

        if errors:
            return "\n".join(["⚠️ Partial success"] + results + errors)
        return "\n".join(results)
