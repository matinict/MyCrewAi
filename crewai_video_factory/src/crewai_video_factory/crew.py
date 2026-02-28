import re
import os
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_video_factory.tools.csv_tool import CSVTool
from crewai_video_factory.tools.smart_video_tool import SmartVideoTool
from crewai_video_factory.tools.bar_race_video_tool import BarRaceVideoTool
from crewai_video_factory.tools.audio_tool import AudioGenerationTool
from crewai_video_factory.tools.intro_clip_tool import IntroClipTool
from crewai_video_factory.tools.bar_merge_tool import BarMergeTool
from crewai_video_factory.tools.merge_tool import MergeAudioVideoTool
from crewai_video_factory.tools.yt_metadata_tool import YouTubeMetadataTool
from crewai_video_factory.tools.definition_tool import DefinitionTool
from crewai_video_factory.tools.definition_video_tool import DefinitionVideoTool
from crewai_video_factory.tools.yt_upload_tool import YTUploadTool
from crewai_video_factory.tools.social_share_tool import SocialShareTool

@CrewBase
class CrewaiVideoFactory:
    """Video Factory Crew for generating data-driven videos"""
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self):
        self.filename = None
        self._inputs = {}

    def _llm(self, key: str):
        """Return LLM override from inputs, or None to use project default."""
        val = self._inputs.get(key)
        return val if val and str(val).strip().lower() not in ('null', 'none', '') else None

    @agent
    def data_researcher(self) -> Agent:
        kwargs = dict(config=self.agents_config['data_researcher'], verbose=True)
        if self._llm('llm_researcher'):
            kwargs['llm'] = self._llm('llm_researcher')
        return Agent(**kwargs)

    @agent
    def csv_generator(self) -> Agent:
        kwargs = dict(config=self.agents_config['csv_generator'], tools=[CSVTool()], verbose=True)
        if self._llm('llm_csv'):
            kwargs['llm'] = self._llm('llm_csv')
        return Agent(**kwargs)

    @agent
    def video_producer(self) -> Agent:
        kwargs = dict(config=self.agents_config['video_producer'], tools=[SmartVideoTool()], verbose=True)
        if self._llm('llm_video'):
            kwargs['llm'] = self._llm('llm_video')
        return Agent(**kwargs)

    @agent
    def bar_race_video_producer(self) -> Agent:
        return Agent(
            config=self.agents_config['bar_race_video_producer'],
            tools=[BarRaceVideoTool()],
            verbose=True
        )

    @agent
    def intro_clip_producer(self) -> Agent:
        return Agent(
            config=self.agents_config['intro_clip_producer'],
            tools=[IntroClipTool()],
            verbose=True
        )

    @agent
    def bar_merge_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config['bar_merge_specialist'],
            tools=[BarMergeTool()],
            verbose=True
        )

    @agent
    def bar_race_audio_engineer(self) -> Agent:
        from crewai_video_factory.tools.bar_race_audio_tool import BarRaceAudioTool
        return Agent(
            config=self.agents_config['bar_race_audio_engineer'],
            tools=[BarRaceAudioTool()],
            verbose=True
        )

    @agent
    def audio_engineer(self) -> Agent:
        kwargs = dict(config=self.agents_config['audio_engineer'], tools=[AudioGenerationTool()], verbose=True)
        if self._llm('llm_audio'):
            kwargs['llm'] = self._llm('llm_audio')
        return Agent(**kwargs)

    @agent
    def merge_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config['merge_specialist'],
            tools=[MergeAudioVideoTool()],
            verbose=True
        )

    @agent
    def youtube_metadata_specialist(self) -> Agent:
        kwargs = dict(config=self.agents_config['youtube_metadata_specialist'], tools=[YouTubeMetadataTool()], verbose=True)
        if self._llm('llm_youtube'):
            kwargs['llm'] = self._llm('llm_youtube')
        return Agent(**kwargs)

    @agent
    def definition_specialist(self) -> Agent:
        kwargs = dict(config=self.agents_config['definition_specialist'], tools=[DefinitionTool()], verbose=True)
        if self._llm('llm_definition'):
            kwargs['llm'] = self._llm('llm_definition')
        return Agent(**kwargs)

    @agent
    def definition_video_producer(self) -> Agent:
        return Agent(
            config=self.agents_config['definition_video_producer'],
            tools=[DefinitionVideoTool()],
            verbose=True
        )

    @agent
    def youtube_upload_specialist(self) -> Agent:
        kwargs = dict(config=self.agents_config['youtube_upload_specialist'], tools=[YTUploadTool()], verbose=True)
        if self._llm('llm_upload'):
            kwargs['llm'] = self._llm('llm_upload')
        return Agent(**kwargs)

    @agent
    def social_share_specialist(self) -> Agent:
        kwargs = dict(config=self.agents_config['social_share_specialist'], tools=[SocialShareTool()], verbose=True)
        if self._llm('llm_social'):
            kwargs['llm'] = self._llm('llm_social')
        return Agent(**kwargs)

    @task
    def research_data(self) -> Task:
        return Task(config=self.tasks_config['research_data'])

    @task
    def generate_csv(self) -> Task:
        return Task(config=self.tasks_config['generate_csv'])

    @task
    def define_topic(self) -> Task:
        return Task(config=self.tasks_config['define_topic'])

    @task
    def create_definition_video(self) -> Task:
        return Task(config=self.tasks_config['create_definition_video'])

    @task
    def create_video(self) -> Task:
        return Task(config=self.tasks_config['create_video'])

    @task
    def create_bar_race_video(self) -> Task:
        return Task(config=self.tasks_config['create_bar_race_video'])

    @task
    def create_intro_clip(self) -> Task:
        return Task(config=self.tasks_config['create_intro_clip'])

    @task
    def bar_merge(self) -> Task:
        return Task(config=self.tasks_config['bar_merge'])

    @task
    def add_audio(self) -> Task:
        return Task(config=self.tasks_config['add_audio'])

    @task
    def merge_audio_video(self) -> Task:
        return Task(config=self.tasks_config['merge_audio_video'])

    @task
    def generate_youtube_metadata(self) -> Task:
        return Task(config=self.tasks_config['generate_youtube_metadata'])

    @task
    def upload_to_youtube(self) -> Task:
        return Task(config=self.tasks_config['upload_to_youtube'])

    @task
    def share_to_social(self) -> Task:
        return Task(config=self.tasks_config['share_to_social'])

    @crew
    def crew(self, inputs: dict = None) -> Crew:
        """Creates the Video Factory crew with all potential agents and tasks.
        Conditional execution is handled in main.py"""
        if inputs:
            self._inputs = inputs
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True
        )
