import re
import os

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_video_factory.tools.csv_tool import CSVTool
from crewai_video_factory.tools.smart_video_tool import SmartVideoTool
from crewai_video_factory.tools.bar_race_video_tool import BarRaceVideoTool  # NEW - Optional bar race
from crewai_video_factory.tools.audio_tool import AudioGenerationTool
from crewai_video_factory.tools.bar_race_audio_tool import BarRaceAudioTool
from crewai_video_factory.tools.intro_clip_tool import IntroClipTool
from crewai_video_factory.tools.bar_merge_tool import BarMergeTool
from crewai_video_factory.tools.merge_tool import MergeAudioVideoTool
from crewai_video_factory.tools.yt_metadata_tool import YouTubeMetadataTool
from crewai_video_factory.tools.definition_tool import DefinitionTool
from crewai_video_factory.tools.definition_video_tool import DefinitionVideoTool

@CrewBase
class CrewaiVideoFactory:
    """Video Factory Crew for generating data-driven videos"""
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self):
        self.filename = None

    @agent
    def data_researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['data_researcher'],
            verbose=True
        )

    @agent
    def csv_generator(self) -> Agent:
        return Agent(
            config=self.agents_config['csv_generator'],
            tools=[CSVTool()],
            verbose=True
        )

    @agent
    def video_producer(self) -> Agent:
        return Agent(
            config=self.agents_config['video_producer'],
            tools=[SmartVideoTool()],
            verbose=True
        )

    @agent
    def bar_race_video_producer(self) -> Agent:
        """NEW - Optional bar race video producer"""
        return Agent(
            config=self.agents_config['bar_race_video_producer'],
            tools=[BarRaceVideoTool()],
            verbose=True
        )

    @agent
    def intro_clip_producer(self) -> Agent:
        """Intro clip producer triggered by intro_enabled"""
        return Agent(
            config=self.agents_config['intro_clip_producer'],
            tools=[IntroClipTool()],
            verbose=True
        )

    @agent
    def bar_merge_specialist(self) -> Agent:
        """Bar merge specialist triggered by bar_merge_enabled"""
        return Agent(
            config=self.agents_config['bar_merge_specialist'],
            tools=[BarMergeTool()],
            verbose=True
        )

    @agent
    def bar_race_audio_engineer(self) -> Agent:
        """Bar race audio producer triggered by bar_race_audio_enabled"""
        return Agent(
            config=self.agents_config['bar_race_audio_engineer'],
            tools=[BarRaceAudioTool()],
            verbose=True
        )

    @agent
    def audio_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['audio_engineer'],
            tools=[AudioGenerationTool()],
            verbose=True
        )

    @agent
    def merge_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config['merge_specialist'],
            tools=[MergeAudioVideoTool()],
            verbose=True
        )

    @agent
    def youtube_metadata_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config['youtube_metadata_specialist'],
            tools=[YouTubeMetadataTool()],
            verbose=True
        )

    @agent
    def definition_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config['definition_specialist'],
            tools=[],  # no tools — agent writes definition as pure text output
            verbose=True
        )

    @agent
    def definition_video_producer(self) -> Agent:
        return Agent(
            config=self.agents_config['definition_video_producer'],
            tools=[DefinitionVideoTool()],
            verbose=True
        )

    @task
    def research_data(self) -> Task:
        return Task(
            config=self.tasks_config['research_data'],
        )

    @task
    def generate_csv(self) -> Task:
        return Task(
            config=self.tasks_config['generate_csv'],
        )

    @task
    def define_topic(self) -> Task:
        return Task(
            config=self.tasks_config['define_topic'],
        )

    @task
    def create_definition_video(self) -> Task:
        return Task(
            config=self.tasks_config['create_definition_video'],
        )

    @task
    def create_video(self) -> Task:
        return Task(
            config=self.tasks_config['create_video'],
        )

    @task
    def create_bar_race_video(self) -> Task:
        """NEW - Optional bar race video creation"""
        return Task(
            config=self.tasks_config['create_bar_race_video'],
        )

    @task
    def create_intro_clip(self) -> Task:
        """Intro clip task triggered by intro_enabled"""
        return Task(
            config=self.tasks_config['create_intro_clip'],
        )

    @task
    def bar_merge(self) -> Task:
        """Bar merge task triggered by bar_merge_enabled"""
        return Task(
            config=self.tasks_config['bar_merge'],
        )

    @task
    def add_bar_race_audio(self) -> Task:
        """Bar race audio task triggered by bar_race_audio_enabled"""
        return Task(
            config=self.tasks_config['add_bar_race_audio'],
        )

    @task
    def add_audio(self) -> Task:
        return Task(
            config=self.tasks_config['add_audio'],
        )

    @task
    def merge_audio_video(self) -> Task:
        return Task(
            config=self.tasks_config['merge_audio_video'],
        )

    @task
    def generate_youtube_metadata(self) -> Task:
        return Task(
            config=self.tasks_config['generate_youtube_metadata'],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Video Factory crew with all potential agents and tasks.
        Conditional execution is handled in main.py"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True
        )
