import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import Rectangle
from datetime import datetime
from crewai.tools import BaseTool
from typing import Type, Optional
from pydantic import BaseModel, Field

class SmartVideoToolInput(BaseModel):
    """Input schema for SmartVideoTool."""
    csv_filepath: str = Field(..., description="Path to the CSV file")
    topic: str = Field(..., description="Topic/title for the video")
    animation_styles: list = Field(default=["bar", "line"], description="styles: bar, line, bubble, map, pie, stream")
    video_formats: list = Field(default=["HD"], description="Video formats: HD, 2K, 4K, 8K, Shorts, ShortsHD, Shorts4K")
    fps: float = Field(default=2.0, ge=0.1, le=30.0, description="Frames per second for animation (0.1-30.0)")

class SmartVideoTool(BaseTool):
    name: str = "Smart Video Generator"
    description: str = "Generates animated video from CSV data with configurable FPS and multi-style visualization"
    args_schema: Type[BaseModel] = SmartVideoToolInput

    def _run(
        self,
        csv_filepath: str,
        topic: str,
        animation_styles: Optional[list] = None,
        video_formats: Optional[list] = None,
        fps: float = 2.0
    ) -> str:
        # Normalize inputs - remove whitespace and handle single values
        if animation_styles is None:
            animation_styles = ["bar", "line"]
        elif isinstance(animation_styles, str):
            animation_styles = [animation_styles.strip()]
        else:
            animation_styles = [s.strip() for s in animation_styles]

        if video_formats is None:
            video_formats = ["HD"]
        elif isinstance(video_formats, str):
            video_formats = [video_formats.strip()]
        else:
            video_formats = [f.strip() for f in video_formats]

        try:
            # Convert to absolute path and validate
            csv_path = os.path.abspath(csv_filepath)
            
            if not os.path.exists(csv_path):
                return f"ERROR: CSV file not found at {csv_path}"
            
            # Read CSV
            df = pd.read_csv(csv_path)
            
            if df.empty:
                return "ERROR: CSV file is empty"
            
            # Get time column (first column) and data columns
            time_col = df.columns[0]
            data_cols = df.columns[1:].tolist()
            
            if len(data_cols) < 5 or len(data_cols) > 10:
                return f"WARNING: CSV has {len(data_cols)} data columns (recommended: 5-10)"
            
            # Prepare output directory
            output_dir = "output"
            os.makedirs(output_dir, exist_ok=True)
            
            filename = os.path.splitext(os.path.basename(csv_path))[0]
            
            results = []
            errors = []
            
            # Generate video for each style and format combination
            for style in animation_styles:
                for video_format in video_formats:
                    output_path = os.path.join(output_dir, f"{filename}_{style}_{video_format}.mp4")
                    
                    try:
                        if style == "bar":
                            self._create_racing_bars(df, time_col, data_cols, topic, output_path, video_format, fps)
                        elif style == "line":
                            self._create_line_chart(df, time_col, data_cols, topic, output_path, video_format, fps)
                        elif style == "bubble":
                            self._create_bubble_race(df, time_col, data_cols, topic, output_path, video_format, fps)
                        elif style == "map":
                            self._create_choropleth(df, time_col, data_cols, topic, output_path, video_format, fps)
                        elif style == "pie":
                            self._create_pie_race(df, time_col, data_cols, topic, output_path, video_format, fps)
                        elif style == "stream":
                            self._create_streamgraph(df, time_col, data_cols, topic, output_path, video_format, fps)
                        else:
                            errors.append(f"Unsupported style '{style}' skipped")
                            continue
                        
                        results.append(f"✅ {style}/{video_format}: {output_path}")
                    except Exception as e:
                        errors.append(f"❌ {style}/{video_format}: {str(e)}")
            
            # Build summary report
            summary = ["🎬 VIDEO GENERATION COMPLETE"]
            if results:
                summary.append("\n✅ SUCCESSFUL:")
                summary.extend(results)
            if errors:
                summary.append("\n⚠️ ERRORS:")
                summary.extend(errors)
            summary.append(f"\n📊 Data: {len(df)} time periods × {len(data_cols)} items")
            summary.append(f"⏱️ Animation speed: {fps} fps → ~{len(df)/fps:.1f} seconds duration")
            
            return "\n".join(summary)
            
        except Exception as e:
            return f"🎬 VIDEO GENERATION FAILED: {str(e)}\n💡 Tip: Check CSV format (first column=time, 5-10 data columns)"

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

    def _format_title(self, title: str, time_value, style: str) -> str:
        """Format title with topic on first line, visualization type + year on second line.
        
        Args:
            title: Main topic name (e.g., "AI Multimodal LLM")
            time_value: Current time period value (e.g., 2025)
            style: Animation style code ("bar", "line", etc.)
        
        Returns:
            Formatted 2-line title string:
            "AI Multimodal LLM\nRace - 2025"
        """
        # Map style codes to human-readable visualization names
        style_names = {
            "bar": "Race",
            "line": "Line Chart",
            "bubble": "Bubble Chart",
            "pie": "Pie Chart",
            "stream": "Streamgraph",
            "map": "Heatmap"
        }
        viz_type = style_names.get(style.strip(), style.strip().title())
        
        # ALWAYS use 2-line format: Topic on first line, visualization + year on second
        return f"{title}\n{viz_type} - {time_value}"

    def _create_line_chart(self, df, time_col, data_cols, title, output_path, video_format="HD", fps=2.0):
        """Create animated line chart video"""
        figsize = self._get_video_dimensions(video_format)
        fig, ax = plt.subplots(figsize=figsize)
        
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_cols)))
        lines = []
        
        for i, col in enumerate(data_cols):
            line, = ax.plot([], [], label=col, color=colors[i], linewidth=2.5)
            lines.append(line)
        
        ax.set_xlim(0, len(df) - 1)
        ax.set_ylim(0, df[data_cols].max().max() * 1.1)
        ax.set_xlabel(time_col, fontsize=14)
        ax.set_ylabel('Value', fontsize=14)
        ax.legend(loc='upper left', fontsize=10)
        ax.grid(True, alpha=0.3)
        
        def animate(frame):
            for i, (line, col) in enumerate(zip(lines, data_cols)):
                line.set_data(range(frame + 1), df[col].iloc[:frame + 1])
            # Set title with 2-line format
            ax.set_title(self._format_title(title, df[time_col].iloc[frame], "line"),
                        fontsize=16, fontweight='bold', pad=20)
            return lines
        
        anim = animation.FuncAnimation(
            fig, animate, frames=len(df),
            interval=1000/fps, blit=True, repeat=False
        )
        
        anim.save(output_path, writer='ffmpeg', fps=fps, dpi=150)
        plt.close()

    def _create_racing_bars(self, df, time_col, data_cols, title, output_path, video_format="HD", fps=2.0):
        """Create racing bar chart animation"""
        figsize = self._get_video_dimensions(video_format)
        fig, ax = plt.subplots(figsize=figsize)
        
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_cols)))
        color_map = {col: colors[i] for i, col in enumerate(data_cols)}
        
        def animate(frame):
            ax.clear()
            
            # Get current data sorted for racing effect
            current_data = df.iloc[frame][data_cols].sort_values(ascending=True)
            
            # Create horizontal bars
            bars = ax.barh(range(len(current_data)), current_data.values, 
                          color=[color_map[col] for col in current_data.index])
            
            # Add value labels on bars
            for i, (idx, val) in enumerate(current_data.items()):
                ax.text(val, i, f' {val:.1f}', va='center', fontsize=10, fontweight='bold')
            
            # Styling
            ax.set_yticks(range(len(current_data)))
            ax.set_yticklabels(current_data.index, fontsize=11)
            ax.set_xlim(0, df[data_cols].max().max() * 1.15)
            ax.set_xlabel('Value', fontsize=12, fontweight='bold')
            # === CRITICAL: 2-LINE TITLE FORMAT ===
            ax.set_title(self._format_title(title, df[time_col].iloc[frame], "bar"),
                        fontsize=16, fontweight='bold', pad=20)
            # =====================================
            ax.grid(axis='x', alpha=0.3)
            
            return bars
        
        anim = animation.FuncAnimation(
            fig, animate, frames=len(df),
            interval=1000/fps, blit=False, repeat=False
        )
        
        anim.save(output_path, writer='ffmpeg', fps=fps, dpi=150)
        plt.close()

    def _create_bubble_race(self, df, time_col, data_cols, title, output_path, video_format="HD", fps=2.0):
        """Create animated bubble chart race"""
        figsize = self._get_video_dimensions(video_format)
        fig, ax = plt.subplots(figsize=figsize)
        
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_cols)))
        color_map = {col: colors[i] for i, col in enumerate(data_cols)}
        
        def animate(frame):
            ax.clear()
            
            # Get current data
            current_data = df.iloc[frame][data_cols]
            
            # Create bubble positions
            x_pos = np.arange(len(current_data))
            y_pos = current_data.values
            sizes = (current_data.values / current_data.max()) * 3000
            
            # Plot bubbles
            for i, col in enumerate(current_data.index):
                ax.scatter(x_pos[i], y_pos[i], s=sizes[i], 
                          color=color_map[col], alpha=0.6, edgecolors='black', linewidth=2)
                ax.text(x_pos[i], y_pos[i], f'{y_pos[i]:.1f}', 
                       ha='center', va='center', fontsize=10, fontweight='bold')
            
            # Styling
            ax.set_xticks(x_pos)
            ax.set_xticklabels(current_data.index, rotation=45, ha='right', fontsize=10)
            ax.set_ylim(0, df[data_cols].max().max() * 1.2)
            ax.set_ylabel('Value', fontsize=12, fontweight='bold')
            # === 2-LINE TITLE FORMAT ===
            ax.set_title(self._format_title(title, df[time_col].iloc[frame], "bubble"),
                        fontsize=16, fontweight='bold', pad=20)
            # ==========================
            ax.grid(True, alpha=0.3, axis='y')
        
        anim = animation.FuncAnimation(
            fig, animate, frames=len(df),
            interval=1000/fps, blit=False, repeat=False
        )
        
        anim.save(output_path, writer='ffmpeg', fps=fps, dpi=150)
        plt.close()

    def _create_pie_race(self, df, time_col, data_cols, title, output_path, video_format="HD", fps=2.0):
        """Create animated pie chart race"""
        figsize = self._get_video_dimensions(video_format)
        fig, ax = plt.subplots(figsize=figsize)
        
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_cols)))
        
        def animate(frame):
            ax.clear()
            
            # Get current data
            current_data = df.iloc[frame][data_cols]
            
            # Create pie chart
            wedges, texts, autotexts = ax.pie(
                current_data.values,
                labels=current_data.index,
                colors=colors,
                autopct='%1.1f%%',
                startangle=90,
                textprops={'fontsize': 10, 'fontweight': 'bold'}
            )
            
            # Enhance percentage visibility
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontsize(9)
            
            # === 2-LINE TITLE FORMAT ===
            ax.set_title(self._format_title(title, df[time_col].iloc[frame], "pie"),
                        fontsize=16, fontweight='bold', pad=20)
            # ==========================
        
        anim = animation.FuncAnimation(
            fig, animate, frames=len(df),
            interval=1000/fps, blit=False, repeat=False
        )
        
        anim.save(output_path, writer='ffmpeg', fps=fps, dpi=150)
        plt.close()

    def _create_streamgraph(self, df, time_col, data_cols, title, output_path, video_format="HD", fps=2.0):
        """Create animated streamgraph (stacked area chart)"""
        figsize = self._get_video_dimensions(video_format)
        fig, ax = plt.subplots(figsize=figsize)
        
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_cols)))
        
        def animate(frame):
            ax.clear()
            
            # Get data up to current frame
            current_df = df.iloc[:frame+1]
            x = np.arange(len(current_df))
            
            # Create stacked area chart
            ax.stackplot(x, *[current_df[col].values for col in data_cols],
                        labels=data_cols, colors=colors, alpha=0.8)
            
            ax.set_xlim(0, len(df) - 1)
            ax.set_ylim(0, df[data_cols].sum(axis=1).max() * 1.1)
            ax.set_xlabel(time_col, fontsize=14)
            ax.set_ylabel('Cumulative Value', fontsize=14)
            ax.legend(loc='upper left', fontsize=9, ncol=2)
            ax.grid(True, alpha=0.3, axis='y')
            # === 2-LINE TITLE FORMAT ===
            ax.set_title(self._format_title(title, df[time_col].iloc[frame], "stream"),
                        fontsize=16, fontweight='bold', pad=20)
            # ==========================
        
        anim = animation.FuncAnimation(
            fig, animate, frames=len(df),
            interval=1000/fps, blit=False, repeat=False
        )
        
        anim.save(output_path, writer='ffmpeg', fps=fps, dpi=150)
        plt.close()

    def _create_choropleth(self, df, time_col, data_cols, title, output_path, video_format="HD", fps=2.0):
        """Create animated choropleth-style heatmap"""
        figsize = self._get_video_dimensions(video_format)
        fig, ax = plt.subplots(figsize=figsize)
        
        # Prepare data matrix for heatmap
        data_matrix = df[data_cols].T.values
        
        def animate(frame):
            ax.clear()
            
            # Get current column data
            current_column = data_matrix[:, :frame+1]
            
            # Create heatmap
            im = ax.imshow(current_column, aspect='auto', cmap='YlOrRd', 
                          interpolation='nearest', vmin=0, vmax=df[data_cols].max().max())
            
            # Set ticks and labels
            ax.set_yticks(np.arange(len(data_cols)))
            ax.set_yticklabels(data_cols, fontsize=10)
            ax.set_xticks(np.arange(frame+1))
            ax.set_xticklabels(df[time_col].iloc[:frame+1], rotation=45, ha='right', fontsize=9)
            
            # Add colorbar on first frame
            if frame == 0:
                cbar = plt.colorbar(im, ax=ax)
                cbar.set_label('Value', fontsize=12, fontweight='bold')
            
            # Add value annotations
            for i in range(len(data_cols)):
                for j in range(frame+1):
                    text = ax.text(j, i, f'{current_column[i, j]:.0f}',
                                 ha="center", va="center", color="black", fontsize=8)
            
            # === 2-LINE TITLE FORMAT ===
            ax.set_title(self._format_title(title, df[time_col].iloc[frame], "map"),
                        fontsize=16, fontweight='bold', pad=20)
            # ==========================
        
        anim = animation.FuncAnimation(
            fig, animate, frames=len(df),
            interval=1000/fps, blit=False, repeat=False
        )
        
        anim.save(output_path, writer='ffmpeg', fps=fps, dpi=150)
        plt.close()