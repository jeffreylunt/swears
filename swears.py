import argparse
import os
import re
import subprocess
import whisper
import json
import string
import tempfile

# Constants
DEFAULT_TARGET_WORDS = [
    "fuck", "fucking", "fucked",
    "asshole", "^ass$",
    "shit", "bullshit",
    "damn", "dammit", 
    "bitch",
    "bastard",
    "dick",
    "goddamn", "goddammit",
    "motherfucker",
    "jesus",
    "cunt"
]

# Functions
def extract_audio(video_file):
    """Extract audio from the video file and return the temporary audio file path."""
    temp_audio = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    temp_audio.close()
    print("Extracting audio from video...")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_file, "-c:a", "aac", "-strict", "-2", "-q:a", "1",
        "-map", "a", temp_audio.name
    ])
    return temp_audio.name

def transcribe_audio(audio_file, transcription_file):
    """Transcribe the audio and save the transcription."""
    if not os.path.exists(transcription_file):
        print("Loading Whisper model...")
        model = whisper.load_model("base.en")
        print("Transcribing audio...")
        result = model.transcribe(audio_file, word_timestamps=True, verbose=True)
        with open(transcription_file, "w") as f:
            json.dump(result, f, indent=4)
        print(f"Transcription saved to '{transcription_file}'")
    else:
        print("Transcription already exists. Skipping.")

def generate_filter(transcription_file, buffer=0.1, target_words=None):
    """Generate FFmpeg filter string to mute specific sections."""
    print("Generating mute sections from transcription...")
    with open(transcription_file, "r") as f:
        transcription = json.load(f)

    words_to_target = target_words if target_words is not None else DEFAULT_TARGET_WORDS
    regex_patterns = [re.compile(rf"\b{word}\w*\b", re.IGNORECASE) for word in words_to_target]
    filter_parts = []

    for segment in transcription.get("segments", []):
        for word in segment.get("words", []):
            if any(pattern.search(word["word"]) for pattern in regex_patterns):
                start = max(0, word["start"] - buffer)
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

def mute_audio(audio_file, filter_string):
    """Apply muting to the audio file and return the path of the muted audio."""
    temp_muted_audio = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    temp_muted_audio.close()
    print("Applying mute sections...")
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_file, "-af", filter_string, "-c:a", "aac", "-strict", "-2",
        temp_muted_audio.name
    ])
    print(f"Muted audio temporarily saved to '{temp_muted_audio.name}'")
    return temp_muted_audio.name

def check_clean_audio(video_file):
    """Check if the video file has an audio track with title 'Clean'."""
    result = subprocess.run([
        "ffmpeg", "-i", video_file, "-hide_banner"
    ], capture_output=True, text=True)
    
    # Look for any of our identifying metadata in audio streams
    audio_streams = result.stderr.split("Stream #")
    
    for i, stream in enumerate(audio_streams):
        if "Audio" in stream:
            identifiers = [
                r"handler_name\s*:\s*CleanAudio",
                r"comment\s*:\s*Clean audio track",
                r"title\s*:\s*Clean"
            ]
            for identifier in identifiers:
                if re.search(identifier, stream):
                    return True
    
    return False

def remove_clean_audio(video_file):
    """Remove audio tracks with the title 'Clean'."""
    temp_file = video_file + ".temp" + os.path.splitext(video_file)[1]  # Use same extension as source
    print("Removing existing 'Clean' audio track...")
    
    # Identify all streams except 'Clean' audio tracks
    streams = subprocess.run(
        ["ffprobe", "-i", video_file, "-show_streams", "-select_streams", "a", 
         "-show_entries", "stream=index:stream_tags=title", "-of", "csv=p=0"],
        capture_output=True, text=True
    ).stdout.strip().split("\n")
    
    # Collect stream indexes to remove
    clean_track_indexes = [
        line.split(",")[0] for line in streams if "Clean" in line
    ]
    
    # Generate the `-map` commands to exclude 'Clean' tracks
    map_options = ["-map", "0"]
    for index in clean_track_indexes:
        map_options += ["-map", f"-0:{index}"]
    
    # Run ffmpeg to remove the 'Clean' tracks
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_file, *map_options, "-c", "copy", temp_file]
    )
    os.replace(temp_file, video_file)
    print("Existing 'Clean' audio track removed.")

def add_audio_to_video(video_file, clean_audio_file, output_file=None):
    """Add the cleaned audio track back to the original video."""
    output_file = output_file or video_file
    temp_file = output_file + ".temp" + os.path.splitext(output_file)[1]

    if output_file == video_file and check_clean_audio(video_file):
        remove_clean_audio(video_file)

    print("Adding clean audio back to the video...")
    cmd = [
        "ffmpeg", "-y", 
        "-i", video_file, 
        "-i", clean_audio_file,
        "-map", "0",  # Include all original streams
        "-map", "1:a",  # Add clean audio as a new track
        "-c:v", "copy", 
        "-c:a", "aac", 
        "-strict", "-2",
        "-metadata:s:a:1", "title=Clean",
        "-metadata:s:a:1", "language=eng",
        "-metadata:s:a:1", "handler_name=CleanAudio",  # Add handler name
        "-metadata:s:a:1", "comment=Clean audio track",  # Add comment
        "-shortest", 
        temp_file
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.replace(temp_file, output_file)
    print(f"Clean audio track added to '{output_file}'.")

# Main Functionality
def main():
    parser = argparse.ArgumentParser(description="Process a video file to mute specific words.")
    parser.add_argument("video_file", help="Path to the input video file")
    parser.add_argument("--force", action="store_true", help="Force replace the 'Clean' audio track.")
    args = parser.parse_args()

    video_file = args.video_file
    if not os.path.exists(video_file):
        print(f"Error: File '{video_file}' not found.")
        return

    if check_clean_audio(video_file):
        if not args.force:
            print("'Clean' audio track already exists. Use --force to replace it.")
            return

    base_name = os.path.splitext(os.path.basename(video_file))[0]
    output_dir = os.path.dirname(video_file)
    transcription_file = os.path.join(output_dir, f"{base_name}_transcription.json")

    # Step 1: Extract audio
    extracted_audio = extract_audio(video_file)

    # Step 2: Transcribe audio
    transcribe_audio(extracted_audio, transcription_file)

    # Step 3: Generate mute sections
    filter_string = generate_filter(transcription_file)
    if not filter_string:
        print("No sections to mute. Exiting.")
        os.unlink(extracted_audio)
        return

    # Step 4: Mute the audio
    muted_audio = mute_audio(extracted_audio, filter_string)
    os.unlink(extracted_audio)  # Clean up extracted audio

    # Step 5: Add muted audio back to the video
    add_audio_to_video(video_file, muted_audio)
    os.unlink(muted_audio)  # Delete muted audio

if __name__ == "__main__":
    main()