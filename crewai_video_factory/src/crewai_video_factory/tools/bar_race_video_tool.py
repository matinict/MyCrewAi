# source .venv/bin/activate
# python --version
# Python 3.11.x only this version worked
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
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
    output_path: str = Field(..., description="Where to save the .mp4 file.")
    title: str = Field(..., description="The title of the bar chart race.")
    video_format: str = Field("HD", description="Video format: HD, 2K, 4K, 8K, Shorts, ShortsHD, Shorts4K")
    seconds_per_period: float = Field(default=4.0, description="Animation speed.")
    n_bars: int = Field(default=5, description="Number of bars to display.")

class BarRaceVideoTool(BaseTool):
    name: str = "Bar Race Video Tool"
    description: str = "Creates a bar chart race video from a prepared CSV file."
    args_schema: Type[BaseModel] = BarRaceInput

    def _get_video_dimensions(self, video_format: str):
        """Get video dimensions based on format."""
        formats = {
            # Horizontal formats (16:9 aspect ratio)
            "HD": (12, 6.75),        # 1920x1080
            "2K": (12.8, 7.2),       # 2560x1440
            "4K": (19.2, 10.8),      # 3840x2160
            "8K": (38.4, 21.6),      # 7680x4320
            # Vertical formats (9:16 aspect ratio)
            "Shorts": (4.5, 8),      # 720x1280
            "ShortsHD": (6.75, 12),  # 1080x1920
            "Shorts4K": (13.5, 24)   # 2160x3840
        }
        return formats.get(video_format.strip(), (12, 6.75))

    def _run(self, **kwargs) -> str:
        # -------------------------------------------------
        # Extract Inputs
        # -------------------------------------------------
        csv_filepath = kwargs.get("csv_filepath")
        output_path = kwargs.get("output_path")
        title = kwargs.get("title")
        video_format = kwargs.get("video_format", "HD")
        seconds_per_period = kwargs.get("seconds_per_period", 4.0)
        n_bars = kwargs.get("n_bars", 5)

        # -------------------------------------------------
        # Validate
        # -------------------------------------------------
        csv_path = os.path.abspath(csv_filepath)
        if not os.path.exists(csv_path):
            return "❌ CSV file not found"

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # -------------------------------------------------
        # Load CSV
        # -------------------------------------------------
        df = pd.read_csv(csv_path)
        if df.empty or len(df.columns) < 2:
            return "❌ Invalid CSV structure"

        year_col = df.columns[0]
        df_viz = df.set_index(year_col).select_dtypes(include="number")

        df_viz.index = pd.to_datetime(
            df_viz.index.astype(int).astype(str),
            format="%Y"
        )

        # -------------------------------------------------
        # Get dimensions based on video format
        # -------------------------------------------------
        figsize = self._get_video_dimensions(video_format)

        # Determine if this is a vertical format (Shorts series)
        is_vertical = video_format.startswith("Shorts")

        # Set sizing parameters based on format
        if is_vertical:
            # Vertical formats (Shorts)
            title_size = 28
            year_size = 48
            bar_label_size = 40
            tick_label_size = 40
            bar_size = 0.85
            title_y = 0.965
            year_y = 0.92
        else:
            # Horizontal formats (HD, 2K, 4K, 8K)
            title_size = 36
            year_size = 56
            bar_label_size = 50
            tick_label_size = 50
            bar_size = 0.75
            title_y = 0.955
            year_y = 0.905

        # -------------------------------------------------
        # Timing
        # -------------------------------------------------
        steps_per_period = int(seconds_per_period * 15)
        period_length = int(seconds_per_period * 1000)

        # -------------------------------------------------
        # Layout - adjusted for different formats
        # -------------------------------------------------
        plt.rcParams.update({
            "figure.subplot.left": 0.05,   # Tight left margin for all formats
            "figure.subplot.right": 0.98,
            "figure.subplot.top": 0.40,    # More top space for title
            "figure.subplot.bottom": 0.10,  # Consistent bottom margin
            "xtick.labeltop": True,
            "xtick.top": True,
            "xtick.labelbottom": False,
            "xtick.bottom": False,
            "axes.spines.top": True,
            "axes.spines.bottom": False,
            "axes.titlelocation": "left",
            "axes.titlepad": 50,
            "axes.titleweight": "bold",
        })

        # -------------------------------------------------
        # Dynamic year + scale on top
        # -------------------------------------------------
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

        # -------------------------------------------------
        # Render bar race
        # -------------------------------------------------
        bcr.bar_chart_race(
            df=df_viz,
            filename=output_path,
            orientation="h",
            sort="desc",
            n_bars=n_bars,
            fixed_order=False,
            fixed_max=True,
            interpolate_period=True,
            steps_per_period=steps_per_period,
            period_length=period_length,
            figsize=figsize,
            dpi=96,
            bar_size=bar_size,

            title=title,
            period_label=False,
            period_summary_func=period_summary_func,
            bar_label_size=bar_label_size,
            tick_label_size=tick_label_size,
            title_size=title_size,
        )

        if os.path.exists(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            return f"✅ Bar race video created ({size_mb:.1f} MB)"

        return "❌ Rendering failed"
