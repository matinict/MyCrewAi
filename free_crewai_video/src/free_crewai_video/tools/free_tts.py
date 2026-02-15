"""
Free Text-to-Speech Tool
- Uses pyttsx3 (offline)
- Controlled by env vars
"""

import os
import pyttsx3
from pathlib import Path


class FreeTextToSpeechTool:
    def _run(self, script_text: str, output_path: str) -> str:
        voice_lang = os.getenv("VOICE_LANGUAGE", "en")
        voice_rate = int(os.getenv("VOICE_RATE", "155"))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        engine = pyttsx3.init()
        engine.setProperty("rate", voice_rate)

        # Select voice by language (best-effort)
        for voice in engine.getProperty("voices"):
            if voice_lang.lower() in voice.id.lower():
                engine.setProperty("voice", voice.id)
                break

        engine.save_to_file(script_text, output_path)
        engine.runAndWait()

        return output_path
