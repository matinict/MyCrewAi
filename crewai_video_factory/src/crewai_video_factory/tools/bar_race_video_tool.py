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
    n_bars: int = Field(default=5, description="Number of bars to display.")

class BarRaceVideoTool(BaseTool):
    name: str = "Bar Race Video Tool"
    description: str = "Creates bar chart race videos in multiple formats from a CSV file."
    args_schema: Type[BaseModel] = BarRaceInput

    def _get_video_dimensions(self, video_format: str):
        """Return figsize in INCHES for target pixel resolution at dpi=96."""
        fmt = video_format.strip()
        resolutions_px = {
            "HD": (1920, 1080), "2K": (2560, 1440), "4K": (3840, 2160), "8K": (7680, 4320),
            "Shorts": (1080, 1920), "ShortsHD": (1080, 1920), "Shorts4K": (2160, 3840),
        }
        dpi = 96
        w_px, h_px = resolutions_px.get(fmt, (1920, 1080))
        return (w_px / dpi, h_px / dpi)

    def _trim_label(self, label: str) -> str:
        """Trim labels for bar race videos."""
        mapping = {
            "JavaScript": "JS", "Microsoft": "MS", "Google": "Gle", "Amazon": "AMZ",
            "Apple": "APL", "Meta": "MTA", "NVIDIA": "NVD", "Tesla": "TS",
            "Transformer": "TFormer", "Shiba Inu": "SHIB"
        }
        return mapping.get(label, label)

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
        n_bars = kwargs.get("n_bars", 5)

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
                base_figsize = self._get_video_dimensions(fmt)
                # Increase physical rendering size for clearer text
                figsize = (base_figsize[0] * 1.3, base_figsize[1] * 1.3)
                dpi = 100  # Higher DPI = sharper + bigger text

                is_vertical = fmt.startswith("Shorts")

                # --- 4. STYLE CONFIGURATION ---
                title_size = 65 if is_vertical else 85
                bar_label_size = 55 if is_vertical else 75
                tick_label_size = 55 if is_vertical else 75

                plt.rcParams.update({
                    "axes.titlesize": title_size,
                    "axes.titleweight": "bold",
                    "axes.titlepad": 50
                })

                def period_summary_func(values, ranks):
                    return {
                        'x': 0.97,
                        'y': 0.08,
                        's': str(values.name.year),
                        'ha': 'right',
                        'size': title_size,
                        'color': '#FF4500',
                        'weight': 'bold'
                    }


                output_path = os.path.join(output_dir, f"bar_race_{fmt}.mp4")

                # --- 5. RENDER ---
                bcr.bar_chart_race(
                    df=df_viz,
                    filename=output_path,
                    orientation="h",
                    sort="desc",
                    n_bars=n_bars,
                    steps_per_period=int(seconds_per_period * 15),
                    period_length=int(seconds_per_period * 1000),
                    figsize=figsize,
                    dpi=dpi,
                    title=title_text,
                    period_label=False,
                    period_summary_func=period_summary_func,
                    bar_label_size=bar_label_size,
                    tick_label_size=tick_label_size,
                    writer='ffmpeg'
                )


                if os.path.exists(output_path):
                    results.append(f"✅ {fmt}: {output_path}")
            except Exception as e:
                results.append(f"❌ {fmt}: {str(e)}")

        return "\n".join(results)
