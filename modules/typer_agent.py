from typing import List
import os
import logging
from datetime import datetime
from modules.assistant_config import get_config
from modules.utils import (
    build_file_name_session,
    create_session_logger_id,
    setup_logging,
)
from modules.deepseek import prefix_prompt, prefix_then_stop_prompt
from modules.execute_python import execute_uv_python, execute
from elevenlabs import play
from elevenlabs.client import ElevenLabs
import time


class TyperAgent:
    def __init__(self, logger: logging.Logger, session_id: str):
        self.logger = logger
        self.session_id = session_id
        self.log_file = build_file_name_session("session.log", session_id)
        self.elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVEN_API_KEY"))
        self.previous_successful_requests = []
        self.previous_responses = []
        self.memory_file = None
        self.previous_interactions = []

    def _validate_markdown(self, file_path: str) -> bool:
        """Validate that file is markdown and has expected structure"""
        if not file_path.endswith((".md", ".markdown")):
            self.logger.error(f"📄 Scratchpad file {file_path} must be a markdown file")
            return False

        try:
            with open(file_path, "r") as f:
                content = f.read()
                # Basic validation - could be expanded based on needs
                if not content.strip():
                    self.logger.warning("📄 Markdown file is empty")
                return True
        except Exception as e:
            self.logger.error(f"📄 Error reading markdown file: {str(e)}")
            return False

    @classmethod
    def build_agent(cls, typer_file: str, scratchpad: List[str]):
        """Create and configure a new TyperAssistant instance"""
        session_id = create_session_logger_id()
        logger = setup_logging(session_id)
        logger.info(f"🚀 Starting STT session {session_id}")

        if not os.path.exists(typer_file):
            logger.error(f"📂 Typer file {typer_file} does not exist")
            raise FileNotFoundError(f"Typer file {typer_file} does not exist")

        # Validate markdown scratchpad
        agent = cls(logger, session_id)
        if scratchpad and not agent._validate_markdown(scratchpad[0]):
            raise ValueError(f"Invalid markdown scratchpad file: {scratchpad[0]}")

        return agent, typer_file, scratchpad[0]

    def build_prompt(
        self,
        typer_file: str,
        scratchpad: str,
        context_files: List[str],
        prompt_text: str,
    ) -> str:
        """Build and format the prompt template with current state"""
        try:
            # Load typer file
            self.logger.info("📂 Loading typer file...")
            with open(typer_file, "r") as f:
                typer_content = f.read()

            # Load scratchpad file
            self.logger.info("📝 Loading scratchpad file...")
            if not os.path.exists(scratchpad):
                self.logger.error(f"📄 Scratchpad file {scratchpad} does not exist")
                raise FileNotFoundError(f"Scratchpad file {scratchpad} does not exist")

            with open(scratchpad, "r") as f:
                scratchpad_content = f.read()

            # Load context files
            context_content = ""
            for file_path in context_files:
                if not os.path.exists(file_path):
                    self.logger.error(f"📄 Context file {file_path} does not exist")
                    raise FileNotFoundError(f"Context file {file_path} does not exist")

                with open(file_path, "r") as f:
                    file_content = f.read()
                    file_name = os.path.basename(file_path)
                    context_content += f'\t<context name="{file_name}">\n{file_content}\n</context>\n\n'

            # Load and format prompt template
            self.logger.info("📝 Loading prompt template...")
            with open("prompts/typer-commands.xml", "r") as f:
                prompt_template = f.read()

            # Replace template placeholders
            formatted_prompt = (
                prompt_template.replace("{{typer-commands}}", typer_content)
                .replace("{{scratch_pad}}", scratchpad_content)
                .replace("{{context_files}}", context_content)
                .replace("{{natural_language_request}}", prompt_text)
            )

            # Log the filled prompt template to file only (not stdout)
            with open(self.log_file, "a") as log:
                log.write("\n📝 Filled prompt template:\n")
                log.write(formatted_prompt)
                log.write("\n\n")

            return formatted_prompt

        except Exception as e:
            self.logger.error(f"❌ Error building prompt: {str(e)}")
            raise

    def set_memory_file(self, memory_file: str):
        """Set and validate memory file path"""
        if not memory_file.endswith((".md", ".markdown")):
            raise ValueError("Memory file must be a markdown file")
        self.memory_file = memory_file

    def write_to_memory(self, entry: dict):
        """Write interaction to memory file in Markdown format"""
        if not self.memory_file:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        memory_entry = (
            f"\n## Interaction - {timestamp}\n\n"
            f"### Input\n{entry.get('input', '')}\n\n"
            f"### Response\n{entry.get('response', '')}\n\n"
            f"### Context\n"
            f"- Command: `{entry.get('command', '')}`\n"
            f"- Status: {entry.get('status', '')}\n"
        )

        if entry.get("output"):
            memory_entry += f"\n### Output\n```\n{entry['output']}\n```\n"

        if entry.get("error"):
            memory_entry += f"\n### Error\n```\n{entry['error']}\n```\n"

        with open(self.memory_file, "a") as f:
            f.write(memory_entry)

        self.previous_interactions.append(entry)

    def process_text(
        self,
        text: str,
        typer_file: str,
        scratchpad: str,
        context_files: List[str],
        mode: str,
    ) -> str:
        try:
            formatted_prompt = self.build_prompt(
                typer_file, scratchpad, context_files, text
            )
            prefix = f"uv run python {typer_file}"
            command = prefix_prompt(prompt=formatted_prompt, prefix=prefix)

            memory_entry = {
                "input": text,
                "command": command,
                "timestamp": datetime.now().isoformat(),
            }

            if command == prefix.strip():
                memory_entry.update({"status": "failed", "error": "Command not found"})
                self.write_to_memory(memory_entry)
                self.speak("I couldn't find that command")
                return "Command not found"

            assistant_name = get_config("typer_assistant.assistant_name")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if mode == "execute" or mode == "execute-no-scratch":
                try:
                    output = execute(command)
                    memory_entry.update({"status": "executed", "output": output})
                    self.think_speak(f"Command generated and executed")
                except Exception as e:
                    memory_entry.update({"status": "error", "error": str(e)})
                    self.think_speak(f"Error executing command")
            else:
                memory_entry.update(
                    {
                        "status": "generated",
                        "explanation": generate_explanation(text, command),
                    }
                )
                self.think_speak(f"Command generated")

            self.write_to_memory(memory_entry)
            return memory_entry.get("output", command)

        except Exception as e:
            self.logger.error(f"❌ Error occurred: {str(e)}")
            raise

    def think_speak(self, text: str):
        response_prompt_base = ""
        with open("prompts/concise-assistant-response.xml", "r") as f:
            response_prompt_base = f.read()

        assistant_name = get_config("typer_assistant.assistant_name")
        human_companion_name = get_config("typer_assistant.human_companion_name")

        response_prompt = response_prompt_base.replace("{{latest_action}}", text)
        response_prompt = response_prompt.replace(
            "{{human_companion_name}}", human_companion_name
        )
        response_prompt = response_prompt.replace(
            "{{personal_ai_assistant_name}}", assistant_name
        )
        prompt_prefix = f"Your Conversational Response: "
        response = prefix_prompt(
            prompt=response_prompt, prefix=prompt_prefix, no_prefix=True
        )
        self.logger.info(f"🤖 Response: '{response}'")
        self.speak(response)

    def speak(self, text: str):
        start_time = time.time()
        model = "eleven_flash_v2_5"
        # model="eleven_flash_v2"
        # model = "eleven_turbo_v2"
        # model = "eleven_turbo_v2_5"
        # model="eleven_multilingual_v2"
        voice = get_config("typer_assistant.elevenlabs_voice")

        audio_generator = self.elevenlabs_client.generate(
            text=text,
            voice=voice,
            model=model,
            stream=False,
        )
        audio_bytes = b"".join(list(audio_generator))
        duration = time.time() - start_time
        self.logger.info(f"Model {model} completed tts in {duration:.2f} seconds")
        play(audio_bytes)


def generate_explanation(request: str, command: str) -> str:
    prompt = (
        f"Explain why the command '{command}' was chosen for the request: '{request}'. "
        "Keep it concise and in a bullet point format if necessary."
    )
    explanation = prefix_then_stop_prompt(
        prompt=prompt,
        prefix="Explanation:",
        suffix=".",
        model=get_config("typer_assistant.brain"),
    )
    return explanation
