"""
Free Python Animation Tool
- Reads env-based video settings
- Creates vertical or horizontal safe animations
- Exports MP4 using ffmpeg
"""

import os
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation


class FreeAnimationTool:
    def _run(self, research_json: str, script_text: str) -> str:
        # -----------------------------
        # Load env config
        # -----------------------------
        width = int(os.getenv("VIDEO_WIDTH", "1080"))
        height = int(os.getenv("VIDEO_HEIGHT", "1920"))
        fps = int(os.getenv("VIDEO_FPS", "30"))
        duration = int(os.getenv("VIDEO_DURATION", "45"))

        font_scale = float(os.getenv("FONT_SCALE", "1.5"))
        safe_margin = float(os.getenv("SAFE_MARGIN", "0.1"))

        frames = fps * duration

        # -----------------------------
        # Load research data
        # -----------------------------
        data = json.loads(research_json)
        points = data.get("data_points", [])

        labels = [p["label"] for p in points]
        values = [p["value"] for p in points]

        # -----------------------------
        # Figure setup
        # -----------------------------
        fig_w = width / 100
        fig_h = height / 100

        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        fig.patch.set_facecolor("black")
        ax.set_facecolor("black")

        ax.set_xlim(0, len(values))
        ax.set_ylim(0, max(values) * 1.2)

        ax.tick_params(colors="white", labelsize=28 * font_scale)
        for spine in ax.spines.values():
            spine.set_visible(False)

        bars = ax.bar(range(len(values)), values, color="#00ffcc")

        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=0, color="white")

        title = ax.set_title(
            data.get("topic", ""),
            fontsize=42 * font_scale,
            color="white",
            pad=40,
        )

        # -----------------------------
        # Animation
        # -----------------------------
        def animate(frame):
            progress = frame / frames
            for bar, val in zip(bars, values):
                bar.set_height(val * progress)
            return bars

        anim = FuncAnimation(
            fig,
            animate,
            frames=frames,
            interval=1000 / fps,
            blit=False,
        )

        # -----------------------------
        # Export MP4
        # -----------------------------
        tmp_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name

        anim.save(
            tmp_video,
            fps=fps,
            dpi=100,
            extra_args=["-pix_fmt", "yuv420p"],
        )

        plt.close(fig)

        return tmp_video
