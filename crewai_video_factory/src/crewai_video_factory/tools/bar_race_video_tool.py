import os
import warnings
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from crewai.tools import BaseTool
from typing import Type, Optional
from pydantic import BaseModel, Field

warnings.filterwarnings('ignore')

class BarRaceVideoToolInput(BaseModel):
    csv_filepath: str = Field(..., description="Path to the CSV file")
    topic: str = Field(..., description="Topic/title for the video")
    output_dir: str = Field(..., description="Output directory for video files")
    filename: str = Field(..., description="Base filename")
    video_formats: list = Field(default=["HD"], description="Video formats: HD, 2K, 4K, Shorts")
    fps: float = Field(default=0.5, ge=0.1, le=30.0, description="Seconds per period")

class BarRaceVideoTool(BaseTool):
    name: str = "Bar Race Video Generator"
    description: str = "Creates smooth racing bar chart animations with visible transitions"
    args_schema: Type[BaseModel] = BarRaceVideoToolInput

    def _run(
        self,
        csv_filepath: str,
        topic: str,
        output_dir: str,
        filename: str,
        video_formats: Optional[list] = None,
        fps: float = 0.5
    ) -> str:
        
        if video_formats is None:
            video_formats = ["HD"]

        try:
            # Load and validate CSV
            csv_path = os.path.abspath(csv_filepath)
            if not os.path.exists(csv_path):
                return f"ERROR: CSV not found at {csv_path}"

            df = pd.read_csv(csv_path)
            if df.empty:
                return "ERROR: CSV is empty"

            # Clean topic
            topic = topic.split("\n")[0].split(" - ")[0].strip()
            
            # Get columns
            year_col = df.columns[0]
            data_cols = list(df.columns[1:])
            
            if len(data_cols) < 2:
                return "ERROR: Need at least 2 data columns"

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Prepare data
            df_data = df.set_index(year_col)[data_cols].copy()
            
            # Convert to numeric
            for col in df_data.columns:
                df_data[col] = pd.to_numeric(df_data[col], errors='coerce')
            df_data = df_data.fillna(0)

            # Get year range
            try:
                start_year = int(df[year_col].iloc[0])
                end_year = int(df[year_col].iloc[-1])
            except:
                start_year = 0
                end_year = len(df) - 1

            # Configure matplotlib
            self._configure_matplotlib()
            
            results = []
            
            # Generate for each format
            for video_format in video_formats:
                figsize = self._get_figsize(video_format)
                title = f"{topic} ({start_year}-{str(end_year)[-2:]}) Race"
                output_path = os.path.join(output_dir, f"bar_race_{video_format}_{video_format}.mp4")
                
                print(f"\n🏁 Creating smooth racing {video_format}...")
                print(f"   Title: {title}")
                print(f"   Speed: {fps} seconds per period")
                print(f"   Items: {len(data_cols)}")

                try:
                    title_size, bar_size, tick_size = self._get_text_settings(video_format)
                    
                    self._create_smooth_racing_animation(
                        df_data=df_data,
                        title=title,
                        output_path=output_path,
                        figsize=figsize,
                        fps=fps,
                        title_size=title_size,
                        start_year=start_year
                    )
                    
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        file_size = os.path.getsize(output_path) / (1024 * 1024)
                        results.append(f"✅ {video_format}: {os.path.basename(output_path)} ({file_size:.1f} MB)")
                        print(f"   ✅ Created successfully! ({file_size:.1f} MB)")
                    else:
                        results.append(f"❌ {video_format}: File not created")
                        print(f"   ❌ Failed to create file")
                        
                except Exception as e:
                    error_msg = str(e)
                    results.append(f"❌ {video_format}: {error_msg[:50]}")
                    print(f"   ❌ Error: {error_msg[:80]}")

            # Summary
            summary = ["🏁 RACING BAR ANIMATION COMPLETE"]
            summary.extend(results)
            summary.append(f"\n✅ Smooth bar transitions - bars race up/down!")
            summary.append(f"📊 Data: {len(df)} periods × {len(data_cols)} items")
            summary.append(f"📁 Location: {output_dir}/")
            
            return "\n".join(summary)

        except Exception as e:
            error_msg = str(e)
            return f"❌ GENERATION FAILED: {error_msg}"

    def _create_smooth_racing_animation(
        self,
        df_data: pd.DataFrame,
        title: str,
        output_path: str,
        figsize: tuple,
        fps: float,
        title_size: int,
        start_year: int
    ):
        """Create smooth racing bar animation with interpolation"""
        
        # Create figure and axis
        fig, ax = plt.subplots(figsize=figsize, facecolor='#0d0d0d')
        
        # Setup colors
        n_cols = len(df_data.columns)
        colors = plt.cm.Set3(np.linspace(0, 1, n_cols))
        
        # Animation parameters
        fps_render = 30  # Render at 30 fps for smooth playback
        frames_per_period = int(fps_render * fps)  # More frames = smoother transitions
        n_periods = len(df_data)
        total_frames = max(1, (n_periods - 1) * frames_per_period)
        
        print(f"   Animation: {fps_render} fps, {frames_per_period} frames per period")
        print(f"   Total frames: {total_frames}")
        
        # Animation function
        def animate(frame_num):
            ax.clear()
            
            try:
                # Calculate period index and progress within period
                period_idx = min(frame_num // frames_per_period, n_periods - 2)
                frame_in_period = frame_num % frames_per_period
                progress = frame_in_period / max(1, frames_per_period)
                
                # Get current and next period values
                current_values = df_data.iloc[period_idx].values.astype(float)
                next_values = df_data.iloc[period_idx + 1].values.astype(float)
                
                # Smooth interpolation between periods
                interpolated = current_values * (1 - progress) + next_values * progress
                
                # Sort by value (descending)
                sorted_indices = np.argsort(interpolated)[::-1]
                sorted_values = interpolated[sorted_indices]
                sorted_names = df_data.columns[sorted_indices].tolist()
                sorted_colors = colors[sorted_indices]
                
                # Create horizontal bar chart
                y_pos = np.arange(len(sorted_names))
                bars = ax.barh(
                    y_pos,
                    sorted_values,
                    color=sorted_colors,
                    height=0.75,
                    edgecolor='white',
                    linewidth=1.2,
                    alpha=0.95
                )
                
                # Add value labels on bars
                for i, val in enumerate(sorted_values):
                    if val > 0:
                        ax.text(
                            val,
                            i,
                            f' {val:.1f}',
                            va='center',
                            ha='left',
                            fontsize=title_size * 0.45,
                            fontweight='bold',
                            color='white'
                        )
                
                # Set y-axis labels (bar names)
                ax.set_yticks(y_pos)
                ax.set_yticklabels(sorted_names, fontsize=title_size * 0.5, fontweight='bold')
                
                # Set x-axis limits
                max_val = df_data.max().max()
                ax.set_xlim(0, max_val * 1.2)
                ax.set_xlabel('Value', fontsize=title_size * 0.6, fontweight='bold', color='white')
                
                # Title with current year
                current_year = int(start_year + period_idx)
                ax.set_title(
                    f"{title.split('(')[0].strip()} - {current_year}",
                    fontsize=title_size,
                    fontweight='bold',
                    loc='left',
                    pad=20,
                    color='white'
                )
                
                # Styling - dark theme
                ax.invert_yaxis()
                ax.grid(axis='x', alpha=0.3, linestyle='--', color='gray')
                ax.set_facecolor('#1a1a1a')
                
                # Remove and style spines
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_visible(False)
                ax.spines['bottom'].set_color('white')
                
                # Tick colors
                ax.tick_params(colors='white', labelsize=title_size * 0.45)
                
                return bars
                
            except Exception as e:
                print(f"   Animation frame error: {str(e)[:50]}")
                ax.text(0.5, 0.5, 'Error', ha='center', va='center')
                return []
        
        # Create and save animation
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore')
                
                # Create animation
                anim = animation.FuncAnimation(
                    fig,
                    animate,
                    frames=total_frames,
                    interval=1000 / fps_render,
                    blit=False,
                    repeat=False
                )
                
                # Save animation using ffmpeg writer
                anim.save(
                    output_path,
                    writer='ffmpeg',
                    fps=fps_render,
                    dpi=96
                )
                
        except Exception as e:
            print(f"   Save error: {str(e)[:80]}")
            raise
        finally:
            plt.close(fig)

    def _configure_matplotlib(self):
        """Configure matplotlib for professional appearance"""
        plt.rcParams.update({
            'figure.subplot.left': 0.1,
            'figure.subplot.right': 0.95,
            'figure.subplot.top': 0.90,
            'figure.subplot.bottom': 0.12,
            'font.size': 10,
            'font.weight': 'bold',
            'axes.labelcolor': 'white',
            'text.color': 'white',
        })

    def _get_figsize(self, video_format: str) -> tuple:
        """Get figure size based on video format"""
        sizes = {
            "HD": (17.4, 10.8),
            "2K": (17.6, 9.9),
            "4K": (19.2, 10.8),
            "Shorts": (9.4, 19.0),
            "ShortsHD": (10.1, 17.9),
            "Shorts4K": (13.5, 24.0),
        }
        return sizes.get(video_format, (17.4, 10.8))

    def _get_text_settings(self, video_format: str) -> tuple:
        """Get text settings (title_size, bar_size, tick_size) for video format"""
        settings = {
            "HD": (36, 0.75, 50),
            "2K": (40, 0.75, 55),
            "4K": (48, 0.75, 65),
            "Shorts": (28, 0.65, 40),
            "ShortsHD": (32, 0.65, 45),
            "Shorts4K": (40, 0.65, 55),
        }
        return settings.get(video_format, (36, 0.75, 50))