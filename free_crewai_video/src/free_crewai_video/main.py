from .crew import create_crew

def run():
    topic = input("Enter video topic: ")
    crew = create_crew()
    crew.kickoff(inputs={"topic": topic})


print("✅ Video generation pipeline finished")
