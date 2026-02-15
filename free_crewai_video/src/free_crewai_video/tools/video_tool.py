from crewai_tools import tool
import pandas as pd
import matplotlib.pyplot as plt
import os

@tool("generate_video_from_csv")
def generate_video_from_csv(csv_path: str) -> str:
    """
    Generate a simple animated video from a CSV file.
    CSV must contain columns: frame, value
    """

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    df = pd.read_csv(csv_path)

    frames = []

    for i, row in df.iterrows():
        plt.figure()
        plt.plot(df["frame"][: i + 1], df["value"][: i + 1])
        plt.xlabel("Frame")
        plt.ylabel("Value")
        plt.title("AI Generated Visualization")

        frame_path = f"{output_dir}/frame_{i}.png"
        plt.savefig(frame_path)
        plt.close()

        frames.append(frame_path)

    # Simple mp4 via ffmpeg
    video_path = f"{output_dir}/output.mp4"
    os.system(
        f"ffmpeg -y -framerate 2 -i {output_dir}/frame_%d.png "
        f"-c:v libx264 -pix_fmt yuv420p {video_path}"
    )

    return f"✅ Video created at {video_path}"
