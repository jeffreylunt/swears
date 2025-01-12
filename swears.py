import argparse
import os
import re
import subprocess
import whisper
import json
import string

# Constants
TARGET_WORDS = [
    "fuck", 
    "shit",
    "bullshit",
    "damn", "dammit", 
    "bitch",
    "bastard",
    "dick",
    "goddamn", "goddammit",
    "motherfucker",
    "jesus"
]
# Functions
def extract_audio(video_file, audio_file):
    """Extract audio from the video file."""
    if not os.path.exists(audio_file):
        print("Extracting audio from video...")
        subprocess.run([
            "ffmpeg", "-i", video_file, "-c:a", "aac", "-strict", "-2", "-q:a", "1",
            "-map", "a", audio_file
        ])
    else:
        print("Audio already extracted. Skipping.")

def transcribe_audio(audio_file, transcription_file, model):
    """Transcribe the audio and save the transcription."""
    if not os.path.exists(transcription_file):
        print("Transcribing audio...")
        result = model.transcribe(audio_file, word_timestamps=True, verbose=True)
        with open(transcription_file, "w") as f:
            json.dump(result, f, indent=4)
        print(f"Transcription saved to '{transcription_file}'")
    else:
        print("Transcription already exists. Skipping.")

def generate_filter(transcription_file, buffer=0.1):
    """Generate FFmpeg filter string to mute specific sections."""
    print("Generating mute sections from transcription...")
    with open(transcription_file, "r") as f:
        transcription = json.load(f)

    regex_patterns = [re.compile(rf"\b{word}\w*\b", re.IGNORECASE) for word in TARGET_WORDS]
    filter_parts = []

    for segment in transcription.get("segments", []):
        for word in segment.get("words", []):
            if any(pattern.search(word["word"]) for pattern in regex_patterns):
                start = max(0, word["start"] - buffer)  # Ensure start time doesn't go below 0
                if(word["word"].rstrip(string.punctuation).endswith("ed")):
                    buffer = 0.3
                end = word["end"] + buffer
                filter_parts.append(f"volume=enable='between(t,{start},{end})':volume=0")

    if not filter_parts:
        print("No target words found in the audio.")
        return None

    filter_string = ",".join(filter_parts)
    print(f"Generated FFmpeg filter string: {filter_string}")
    return filter_string

def mute_audio(audio_file, filter_string, output_audio):
    """Apply muting to the audio file."""
    print("Applying mute sections...")
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_file, "-af", filter_string, "-c:a", "aac", "-strict", "-2",
        output_audio
    ])
    print(f"Muted audio saved to '{output_audio}'")

def add_audio_to_video(video_file, clean_audio_file, output_video_file):
    """Add the cleaned audio track back to the original video."""
    print("Adding clean audio back to the video...")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_file, "-i", clean_audio_file, "-map", "0:v", "-map", "0:a",
        "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-strict", "-2",
        "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=Clean",
        "-shortest", output_video_file
    ])
    print(f"Clean video saved")
    subprocess.run(["mv", output_video_file, video_file])

# Main Functionality
def main():
    parser = argparse.ArgumentParser(description="Process a video file to mute specific words.")
    parser.add_argument("video_file", help="Path to the input video file")
    args = parser.parse_args()

    video_file = args.video_file
    if not os.path.exists(video_file):
        print(f"Error: File '{video_file}' not found.")
        return

    base_name = os.path.splitext(os.path.basename(video_file))[0]
    output_dir = os.path.dirname(video_file)
    extracted_audio = os.path.join(output_dir, f"{base_name}_extracted_audio.m4a")
    transcription_file = os.path.join(output_dir, f"{base_name}_transcription.json")
    clean_audio = os.path.join(output_dir, f"{base_name}_clean_audio.m4a")
    clean_video = os.path.join(output_dir, f"{base_name}_clean_video.mkv")

    # Load Whisper model
    print("Loading Whisper model...")
    model = whisper.load_model("base")

    # Step 1: Extract audio
    extract_audio(video_file, extracted_audio)

    # Step 2: Transcribe audio
    transcribe_audio(extracted_audio, transcription_file, model)

    # Step 3: Generate mute sections
    filter_string = generate_filter(transcription_file)
    if not filter_string:
        print("No sections to mute. Exiting.")
        return

    # Step 4: Mute the audio
    mute_audio(extracted_audio, filter_string, clean_audio)

    # Step 5: Add muted audio back to the video
    add_audio_to_video(video_file, clean_audio, clean_video)

if __name__ == "__main__":
    main()