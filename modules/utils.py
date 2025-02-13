import datetime
import json
import os
from typing import Union, Dict, List
import uuid
import sounddevice as sd
import numpy as np
import logging
import sys

OUTPUT_DIR = "output"


# List all available audio devices
def list_audio_devices():
    print("Available audio devices:")
    for i, device_info in enumerate(sd.query_devices()):
        print(
            f"Index: {i}, Name: {device_info['name']}, Max Output Channels: {device_info['max_output_channels']}"
        )


# list_audio_devices()
# Available audio devices:
# Index: 0, Name: Chip iPhone 16 Pro Max Microphone, Max Output Channels: 0
# Index: 1, Name: MacBook Pro Microphone, Max Output Channels: 0
# Index: 2, Name: MacBook Pro Speakers, Max Output Channels: 2
# Index: 3, Name: Wave Link MicrophoneFX, Max Output Channels: 0
# Index: 4, Name: Wave Link Stream, Max Output Channels: 0
# Index: 5, Name: Immersed, Max Output Channels: 2
# Index: 6, Name: Microsoft Teams Audio, Max Output Channels: 1
# Index: 7, Name: ZoomAudioDevice, Max Output Channels: 2
# Specify the index of your Elgato WaveLink virtual output device
elgato_device_index = 2  # Change this to the correct index
elgato_device_info = sd.query_devices(elgato_device_index, "output")
max_output_channels = elgato_device_info["max_output_channels"]
print(f"Elgato WaveLink Device Max Output Channels: {max_output_channels}")


# Generate a simple sine wave audio signal with the correct number of channels
def generate_sine_wave(duration=2, frequency=440.0, sample_rate=44100, num_channels=2):
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    sine_wave = 0.5 * np.sin(frequency * 2 * np.pi * t)

    # Ensure the audio signal has the correct number of channels
    if num_channels > 1:
        sine_wave = np.repeat(sine_wave[:, np.newaxis], num_channels, axis=1)

    return sine_wave


# Play the sine wave on the specified device
def play_audio_on_device(device_index, audio_signal, sample_rate=44100):
    sd.play(
        audio_signal,
        samplerate=sample_rate,
        device=device_index,
        channels=max_output_channels,
    )
    sd.wait()


def build_file_path(name: str):
    session_dir = f"{OUTPUT_DIR}"
    os.makedirs(session_dir, exist_ok=True)
    return os.path.join(session_dir, f"{name}")


def build_file_name_session(name: str, session_id: str):
    session_dir = f"{OUTPUT_DIR}/{session_id}"
    os.makedirs(session_dir, exist_ok=True)
    return os.path.join(session_dir, f"{name}")


def to_json_file_pretty(name: str, content: Union[Dict, List]):
    def default_serializer(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        raise TypeError(
            f"Object of type {obj.__class__.__name__} is not JSON serializable"
        )

    with open(f"{name}.json", "w") as outfile:
        json.dump(content, outfile, indent=2, default=default_serializer)


def current_date_time_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def current_date_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def dict_item_diff_by_set(
    previous_list: List[Dict], current_list: List[Dict], set_key: str
) -> List[str]:
    previous_set = {item[set_key] for item in previous_list}
    current_set = {item[set_key] for item in current_list}
    return list(current_set - previous_set)


def create_session_logger_id() -> str:
    return (
        datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    )


def setup_logging(session_id: str):
    """Configure logging with session-specific log file and stdout"""
    log_file = build_file_name_session("session.log", session_id)

    # Create a new logger specific to our application
    logger = logging.getLogger("main")
    logger.setLevel(logging.INFO)

    # Clear any existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create formatter with emoji mapping
    class EmojiFormatter(logging.Formatter):
        EMOJI_MAP = {
            logging.INFO: "ℹ️",
            logging.WARNING: "⚠️",
            logging.ERROR: "❌",
            logging.CRITICAL: "🔥",
            logging.DEBUG: "🐛",
        }

        def format(self, record):
            # Skip stdout for messages with skip_stdout flag
            if hasattr(record, "skip_stdout") and record.skip_stdout:
                return ""

            emoji = self.EMOJI_MAP.get(record.levelno, "📝")
            self._style._fmt = f"{emoji} %(asctime)s - %(levelname)s - %(message)s"
            return super().format(record)

    # Create file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(EmojiFormatter())

    # Create stdout handler with filter
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_formatter = EmojiFormatter()
    stdout_handler.setFormatter(stdout_formatter)

    # Add filter to skip messages with skip_stdout flag
    stdout_handler.addFilter(lambda record: not getattr(record, "skip_stdout", False))

    # Add both handlers
    logger.addHandler(file_handler)
    logger.addHandler(stdout_handler)

    return logger


def parse_markdown_backticks(str) -> str:
    if "```" not in str:
        return str.strip()
    # Remove opening backticks and language identifier
    str = str.split("```", 1)[-1].split("\n", 1)[-1]
    # Remove closing backticks
    str = str.rsplit("```", 1)[0]
    # Remove any leading or trailing whitespace
    return str.strip()


# if __name__ == "__main__":
#     audio_signal = generate_sine_wave(num_channels=max_output_channels)
#     play_audio_on_device(elgato_device_index, audio_signal)
