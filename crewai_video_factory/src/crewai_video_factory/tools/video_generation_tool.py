import subprocess
import os
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field


class VideoGenerationToolInput(BaseModel):
    """Input schema for VideoGenerationTool."""
    csv_filepath: str = Field(..., description="Path to the CSV file to use for video generation")
    topic: str = Field(..., description="The topic/title for the video")


class VideoGenerationTool(BaseTool):
    name: str = "Video Generation Tool"
    description: str = "Generates a video from CSV data using the smart video generator script"
    args_schema: Type[BaseModel] = VideoGenerationToolInput

    def _run(self, csv_filepath: str, topic: str) -> str:
        """
        Generate video from CSV data.
        
        Args:
            csv_filepath: Path to the CSV file
            topic: Topic/title for the video
            
        Returns:
            String indicating success and output path
        """
        # Ensure the CSV file exists
        #if not os.path.exists(csv_filepath):
        # Convert to absolute path and ensure the CSV file exists
        csv_filepath = os.path.abspath(csv_filepath)
        if not os.path.exists(csv_filepath):        
            return f"Error: CSV file not found at {csv_filepath}"
        
        # Path to the video generator script - check multiple locations
        possible_paths = [
            "smart_video_generator_dynamic3.py",
            "./smart_video_generator_dynamic3.py",
            "../smart_video_generator_dynamic3.py",
            "../../smart_video_generator_dynamic3.py",
        ]
        
        script_path = None
        for path in possible_paths:
            if os.path.exists(path):
                script_path = path
                break
        
        if not script_path:
            return f"Error: Video generator script not found. Searched: {possible_paths}"
        
        try:
            # Run the video generator script
            result = subprocess.run(
              ['python', os.path.abspath(script_path), csv_filepath, topic],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                return f"Successfully generated video for '{topic}'\nOutput: {result.stdout}"
            else:
                return f"Video generation failed:\n{result.stderr}"
                
        except subprocess.TimeoutExpired:
            return "Error: Video generation timed out after 5 minutes"
        except Exception as e:
            return f"Error generating video: {str(e)}"
