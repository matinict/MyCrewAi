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
    mode: str = Field("full", description="Video mode: short | full")
    seconds_per_period: float = Field(default=4.0, description="Animation speed.")
    n_bars: int = Field(default=5, description="Number of bars to display.")

class BarRaceVideoTool(BaseTool):
    name: str = "Bar Race Video Tool"
    description: str = "Creates a bar chart race video from a prepared CSV file."
    args_schema: Type[BaseModel] = BarRaceInput

    def _run(self, **kwargs) -> str:
        # Extract Inputs
        csv_filepath = kwargs.get("csv_filepath")
        output_path = kwargs.get("output_path")
        title = kwargs.get("title")
        mode = kwargs.get("mode", "full")
        seconds_per_period = kwargs.get("seconds_per_period", 4.0)
        n_bars = kwargs.get("n_bars", 5)

        # Validate
        csv_path = os.path.abspath(csv_filepath)
        if not os.path.exists(csv_path):
            return "❌ CSV file not found"

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Load CSV
        df = pd.read_csv(csv_path)
        if df.empty or len(df.columns) < 2:
            return "❌ Invalid CSV structure"

        year_col = df.columns[0]
        df_viz = df.set_index(year_col).select_dtypes(include="number")

        df_viz.index = pd.to_datetime(
            df_viz.index.astype(int).astype(str),
            format="%Y"
        )

        # Mode presets (Shorts vs Full HD)
        if mode == "short":
            figsize = (9.4, 19.0)   # 9:16 YouTube Shorts
            title_size = 28
            year_size = 48
            bar_label_size = 40
            tick_label_size = 40
            bar_size = 0.85
            title_y = 0.965
            year_y = 0.92
        else:
            figsize = (17.4, 10.8)  # 16:9 Full HD
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
        period_length = int(seconds_per_period * 1000)  # ✅ fixed typo: was "perio d_length"

        # -------------------------------------------------
        # Layout — ✅ LEFT PADDING DECREASED TO 0.08
        # -------------------------------------------------
        plt.rcParams.update({
            "figure.subplot.left": 0.08,   # ← changed from 0.15
            "figure.subplot.right": 0.98,
            "figure.subplot.top": 0.70,
            "figure.subplot.bottom": 0.08,
        })

        # -------------------------------------------------
        # Render bar race — ✅ 2-line title via title + period_fmt
        # -------------------------------------------------
        # To get 2 static lines: use title = "Line 1\nLine 2", and disable period_label
        # But since period_fmt="\n%Y" adds a 3rd line (year), we instead:
        #   → Use title = "Main Title\nSubtitle" (2 lines)
        #   → Set period_label=False (hide dynamic year)
        final_title = f"{title}\nPopularity Score"

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
            period_length=period_length,  # ✅ fixed
            figsize=figsize,
            dpi=96,
            bar_size=bar_size,

            title=final_title,           # ✅ 2-line title via \n
            period_label=False,          # ✅ prevents year from overlapping
            bar_label_size=bar_label_size,
            tick_label_size=tick_label_size,
        )
        if os.path.exists(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            return f"✅ Bar race video created ({size_mb:.1f} MB)"

        return "❌ Rendering failed"
