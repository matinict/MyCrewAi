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
        # -------------------------------------------------
        # Extract Inputs — FIXED: NO TRAILING SPACES
        # -------------------------------------------------
        csv_filepath = kwargs.get("csv_filepath")
        output_path = kwargs.get("output_path")
        title = kwargs.get("title")
        mode = kwargs.get("mode", "full").strip()
        seconds_per_period = kwargs.get("seconds_per_period", 4.0)
        n_bars = kwargs.get("n_bars", 5)

        # -------------------------------------------------
        # Validate
        # -------------------------------------------------
        if not csv_filepath:
            return "❌ Missing csv_filepath"
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
        # Mode presets
        # -------------------------------------------------
        if mode == "short":
            figsize = (9.4, 19.0)
            title_size = 28
            bar_label_size = 40
            tick_label_size = 40
            bar_size = 0.85
        else:
            figsize = (17.4, 10.8)
            title_size = 36
            bar_label_size = 50
            tick_label_size = 50
            bar_size = 0.75

        # -------------------------------------------------
        # Timing
        # -------------------------------------------------
        steps_per_period = int(seconds_per_period * 15)
        period_length = int(seconds_per_period * 1000)

        # -------------------------------------------------
        # Layout — ✅ TIGHT LEFT + X-AXIS ON TOP
        # -------------------------------------------------
        plt.rcParams.update({
            "figure.subplot.left": 0.05,   # tight left
            "figure.subplot.right": 0.98,
            "figure.subplot.top": 0.40,    # more space at top for title + scale
            "figure.subplot.bottom": 0.10,
            "xtick.labeltop": True,        # labels on top
            "xtick.top": True,             # ticks on top
            "xtick.labelbottom": False,    # no labels on bottom
            "xtick.bottom": False,         # no ticks on bottom
            "axes.spines.top": True,
            "axes.spines.bottom": False,
            "axes.titlelocation": "left",
            "axes.titlepad": 50,
            "axes.titleweight": "bold",
        })

        # -------------------------------------------------
        # Dynamic year + scale on top: use period_summary_func
        # -------------------------------------------------
        def period_summary_func(values, ranks):
            year = values.name.year
            return {
                'x': 0.5,                     # ← CENTERED horizontally
                'y': 0.965,                   # ← slightly below title (adjust as needed)
                's': str(year),               # e.g., "2025"
                'ha': 'center',               # ← critical for center alignment
                'va': 'top',
                'size': title_size * 1.1,     # ← slightly larger than title
                'color': '#FF4500',           # ← bold orange-red (you can change to 'red', 'white', '#00BFFF', etc.)
                'weight': 'bold',
                'zorder': 100,                # ensure it draws on top
                'bbox': dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7, edgecolor='none')
            }

        # -------------------------------------------------
        # Render bar race — ✅ X-AXIS ON TOP, DYNAMIC YEAR, NO SUBTITLE IN TITLE
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

            title=title,                    # e.g., "LLM Popularity Over Time"
            period_label=False,             # hide default year label
            period_summary_func=period_summary_func,  # ✅ dynamic year top-right
            bar_label_size=bar_label_size,
            tick_label_size=tick_label_size,
            title_size=title_size,
        )

        if os.path.exists(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            return f"✅ Bar race video created ({size_mb:.1f} MB)"

        return "❌ Rendering failed"
