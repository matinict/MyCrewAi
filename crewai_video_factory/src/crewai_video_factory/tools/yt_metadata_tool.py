import os
import json
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field
from datetime import datetime

class YouTubeMetadataToolInput(BaseModel):
    """Input schema for YouTubeMetadataTool."""
    topic: str = Field(..., description="Topic/title for the video")
    filename: str = Field(..., description="Base filename (first 3 words of topic)")
    start_year: int = Field(default=2015, description="Start year of data")
    end_year: int = Field(default=2026, description="End year of data")
    video_duration: float = Field(default=60.0, description="Video duration in seconds")
    generate_narration: bool = Field(default=True, description="Whether to generate narration text")
    generate_youtube_metadata: bool = Field(default=True, description="Whether to generate YouTube metadata")

class YouTubeMetadataTool(BaseTool):
    name: str = "YouTube Metadata Generator"
    description: str = "Generates narration text file (_cc_en.txt) and YouTube metadata (title, description, tags, chapters) with SEO optimization"
    args_schema: Type[BaseModel] = YouTubeMetadataToolInput

    def _run(
        self,
        topic: str,
        filename: str,
        start_year: int = 2015,
        end_year: int = 2026,
        video_duration: float = 60.0,
        generate_narration: bool = True,
        generate_youtube_metadata: bool = True
    ) -> str:
        output_dir = "output"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        import re
        clean_words = re.findall(r'\w+', topic)[:3]
        clean_filename = ''.join(clean_words)

        results = []

        if generate_narration:
            narration_result = self._generate_narration_file(topic, clean_filename, start_year, end_year, output_dir)
            results.append(narration_result)

        if generate_youtube_metadata:
            metadata_result = self._generate_youtube_metadata(topic, clean_filename, start_year, end_year, video_duration, output_dir)
            results.append(metadata_result)

        return "\n\n".join(results)

    def _generate_narration_file(self, topic: str, filename: str, start_year: int, end_year: int, output_dir: str) -> str:
        """Generate professional narration text file from CSV data"""
        csv_path = f"{output_dir}/{filename}.csv"
        narration_text = ""

        if os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)

                time_col = df.columns[0]
                data_cols = df.columns[1:]

                years = df[time_col].tolist()
                start_year = int(years[0])
                end_year = int(years[-1])

                yearly_leaders = []
                for idx, row in df.iterrows():
                    leader = row[data_cols].idxmax()
                    value = row[leader]
                    year = int(row[time_col])
                    yearly_leaders.append((year, leader, value))

                narration_parts = [
                    "Welcome to @PlayOwnAi.",
                    f"Today, we're exploring {topic} Race from {start_year} to {end_year}.",
                    "Only for basic idea about trending",
                    "Let's see how the landscape evolved over time."
                ]

                for year, leader, value in yearly_leaders:
                    if value <= 20:
                        narration_parts.append(f"{year}. The market is forming.")
                    elif value <= 40:
                        narration_parts.append(f"{year}. {leader} gains traction.")
                    elif value <= 70:
                        narration_parts.append(f"{year}. {leader} shows strength.")
                    else:
                        narration_parts.append(f"{year}. {leader} leads the market.")

                final_year, final_leader, _ = yearly_leaders[-1]
                narration_parts.append(f"And in {final_year}, {final_leader} continues to lead.")
                narration_parts.append("The evolution of technology and trends continues.")
                narration_parts.append("Subscribe to @PlayOwnAi for more insights.")

                narration_text = " ".join(narration_parts)

            except Exception as e:
                print(f"[WARN] CSV reading failed: {e}")
                narration_text = self._get_fallback_narration(topic, start_year, end_year)
        else:
            narration_text = self._get_fallback_narration(topic, start_year, end_year)

        # 🔑 Save narration text file with _cc_en.txt naming convention
        narration_file_path = f"{output_dir}/{filename}_cc_en.txt"
        with open(narration_file_path, 'w', encoding='utf-8') as f:
            f.write(narration_text)

        return f"📝 Narration text saved to: {filename}_cc_en.txt"

    def _generate_youtube_metadata(self, topic: str, filename: str, start_year: int, end_year: int, video_duration: float, output_dir: str) -> str:
        """Generate YouTube metadata with SEO optimization"""

        title = self._generate_youtube_title(topic, start_year, end_year)
        description = self._generate_youtube_description(topic, start_year, end_year, video_duration)
        tags = self._generate_youtube_tags(topic)
        chapters = self._generate_youtube_chapters(start_year, end_year, video_duration)

        metadata = {
            "title": title,
            "description": description,
            "tags": tags,
            "chapters": chapters,
            "category": "Science & Technology",
            "language": "en",
            "created_at": datetime.now().isoformat()
        }

        metadata_json_path = f"{output_dir}/{filename}_YouTube_Metadata.json"
        with open(metadata_json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        metadata_txt_path = f"{output_dir}/{filename}_YouTube_Metadata.txt"
        with open(metadata_txt_path, 'w', encoding='utf-8') as f:
            f.write(f"TITLE:\n{title}\n\n")
            f.write(f"DESCRIPTION:\n{description}\n\n")
            f.write(f"TAGS:\n{', '.join(tags)}\n\n")
            f.write(f"CHAPTERS:\n{chapters}\n")

        return f"🎬 YouTube metadata saved to:\n   • {filename}_YouTube_Metadata.json\n   • {filename}_YouTube_Metadata.txt"

    def _generate_youtube_title(self, topic: str, start_year: int, end_year: int) -> str:
        """Generate SEO-optimized YouTube title"""

        title_templates = [
            f"{topic} Race {start_year}-{end_year}: Complete Evolution & Trends",
            f"The {topic} Evolution ({start_year}-{end_year}): Who Dominates?",
            f"{topic} Comparison {start_year}-{end_year}: Shocking Results!",
            f"How {topic} Changed Forever ({start_year}-{end_year}) | Data Visualization",
            f"{topic} Market Share {start_year}-{end_year}: The Full Story",
            f"Ultimate {topic} Race: {start_year} vs {end_year} (Data-Driven)",
            f"{topic} Trends Explained: {start_year}-{end_year} Analysis",
            f"Watch {topic} Dominate: {start_year}-{end_year} Timeline",
        ]

        if len(topic) > 20:
            return title_templates[3]
        elif len(topic) > 10:
            return title_templates[0]
        else:
            return title_templates[1]

    def _generate_youtube_description(self, topic: str, start_year: int, end_year: int, video_duration: float) -> str:
        """Generate SEO-optimized YouTube description"""

        description = f"""🎬 {topic} Race {start_year}-{end_year}: Complete Data Visualization

📊 In this video, we explore the evolution of {topic} from {start_year} to {end_year}. Watch how the market leaders changed over time and discover which {topic.lower()} dominated each year!

🔔 Subscribe to @PlayOwnAi for more data-driven insights and visualizations!

⏱️ TIMESTAMPS:
See chapters below for year-by-year breakdown.

📈 DATA SOURCE:
This visualization is based on comprehensive market data tracking {topic.lower()} popularity, adoption rates, and market share from {start_year} to {end_year}.

🎯 KEY INSIGHTS:
• Market trends and shifts
• Year-by-year leader changes
• Growth patterns and adoption rates
• Competitive landscape evolution

💡 ABOUT THIS CHANNEL:
@PlayOwnAi creates professional data visualizations and insights on technology trends, market analysis, and industry evolution. Subscribe for weekly content!

📱 FOLLOW US:
• YouTube: @PlayOwnAi
• Facebook: facebook.com/PlayOwnAi
• Website: playownai.com

#DataVisualization #{topic.replace(' ', '')} #MarketAnalysis #TechTrends #{start_year}To{end_year}

---
⚠️ Disclaimer: This video is for educational and informational purposes only. Data is compiled from various public sources and may vary from official statistics.
"""
        return description.strip()

    def _generate_youtube_tags(self, topic: str) -> list:
        """Generate SEO-optimized YouTube tags"""

        base_tags = [
            "data visualization",
            "market analysis",
            "tech trends",
            "industry insights",
            "animated chart",
            "bar chart race",
            "data animation",
            "PlayOwnAi",
        ]

        topic_tags = [
            topic.lower(),
            f"{topic.lower()} trends",
            f"{topic.lower()} comparison",
            f"{topic.lower()} evolution",
            f"{topic.lower()} market share",
            f"{topic.lower()} analysis",
            f"{topic.lower()} ranking",
            f"{topic.lower()} history",
        ]

        year_tags = [
            f"{datetime.now().year}",
            f"{datetime.now().year - 1}",
            "trend analysis",
            "market trends",
            "data driven",
            "visualization",
        ]

        all_tags = base_tags + topic_tags + year_tags
        return all_tags[:25]

    def _generate_youtube_chapters(self, start_year: int, end_year: int, video_duration: float) -> str:
        """Generate YouTube chapters/timestamps"""

        total_years = end_year - start_year + 1
        seconds_per_year = video_duration / total_years if total_years > 0 else 5

        chapters = []
        chapters.append("0:00 Introduction")

        for year in range(start_year, end_year + 1):
            timestamp_seconds = int((year - start_year) * seconds_per_year)
            minutes = timestamp_seconds // 60
            seconds = timestamp_seconds % 60
            chapters.append(f"{minutes:02d}:{seconds:02d} {year}")

        conclusion_seconds = int(video_duration)
        minutes = conclusion_seconds // 60
        seconds = conclusion_seconds % 60
        chapters.append(f"{minutes:02d}:{seconds:02d} Conclusion")

        return "\n".join(chapters)

    def _get_fallback_narration(self, topic: str, start_year: int, end_year: int) -> str:
        """Fallback narration if CSV reading fails"""
        return (
            f"Welcome to @PlayOwnAi. Today, we're exploring {topic} Race from {start_year} to {end_year}. "
            "Only for basic idea about trending. Let's see how the landscape evolved over time. "
            "The evolution of technology and trends continues. Subscribe to @PlayOwnAi for more insights."
        )