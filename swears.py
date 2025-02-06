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
    # First, probe the input file to get audio channel information
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "a:0",
        video_file
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    audio_info = json.loads(probe_result.stdout)
    
    # Get number of channels from first audio stream, default to 2 if not found
    channels = 2
    if audio_info.get("streams") and len(audio_info["streams"]) > 0:
        channels = int(audio_info["streams"][0].get("channels", 2))
    
    temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_audio.close()
    print(f"Extracting {channels}-channel audio from video...")
    
    subprocess.run([
        "ffmpeg", "-y", "-i", video_file,
        "-vn",  # No video
        "-acodec", "pcm_s16le",  # Use PCM format (WAV)
        "-ar", "44100",  # Standard sample rate
        "-ac", str(channels),  # Preserve original channel count
        temp_audio.name
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
    # First, probe the input file to get audio channel information
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "a:0",
        audio_file
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    audio_info = json.loads(probe_result.stdout)
    
    # Get number of channels from first audio stream, default to 2 if not found
    channels = 2
    if audio_info.get("streams") and len(audio_info["streams"]) > 0:
        channels = int(audio_info["streams"][0].get("channels", 2))
    
    temp_muted_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_muted_audio.close()
    print(f"Applying mute sections to {channels}-channel audio...")
    
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_file,
        "-af", filter_string,
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", str(channels),
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

    # Get number of channels from original video
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "a:0",
        video_file
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    audio_info = json.loads(probe_result.stdout)
    
    # Get number of channels, default to 2 if not found
    channels = 2
    if audio_info.get("streams") and len(audio_info["streams"]) > 0:
        channels = int(audio_info["streams"][0].get("channels", 2))

    print("Adding clean audio back to the video...")
    cmd = [
        "ffmpeg", "-y", 
        "-i", video_file, 
        "-i", clean_audio_file,
        "-map", "0",  # Include all original streams
        "-map", "1:a",  # Add clean audio as a new track
        "-c:v", "copy", 
        "-c:a", "pcm_s16le",  # Use WAV format (PCM)
        "-ar", "44100",  # Standard sample rate
        "-ac", str(channels),  # Use original channel count
        "-metadata:s:a:1", "title=Clean",
        "-metadata:s:a:1", "language=eng",
        "-metadata:s:a:1", "handler_name=CleanAudio",
        "-metadata:s:a:1", "comment=Clean audio track",
        "-shortest", 
        temp_file
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.replace(temp_file, output_file)
    print(f"Clean audio track added to '{output_file}'.")

def clean_subtitle_text(text, target_words=None):
    """Replace target words in subtitle text with underscores."""
    words_to_target = target_words if target_words is not None else DEFAULT_TARGET_WORDS
    regex_patterns = [re.compile(rf"\b{word}\w*\b", re.IGNORECASE) for word in words_to_target]
    
    cleaned_text = text
    for pattern in regex_patterns:
        cleaned_text = pattern.sub(lambda m: '_' * len(m.group(0)), cleaned_text)
    return cleaned_text

def extract_subtitles(video_file):
    """Extract subtitles from video file if they exist."""
    temp_subs = tempfile.NamedTemporaryFile(suffix=".srt", delete=False)
    temp_subs.close()
    
    # Try to extract English subtitles
    result = subprocess.run([
        "ffmpeg", "-y", "-i", video_file,
        "-map", "0:s:m:language:eng",  # Try to get English subtitles
        temp_subs.name
    ], capture_output=True)
    
    if os.path.getsize(temp_subs.name) == 0:
        # If no English subtitles found, try first subtitle track
        subprocess.run([
            "ffmpeg", "-y", "-i", video_file,
            "-map", "0:s:0",  # Get first subtitle track
            temp_subs.name
        ])
    
    if os.path.getsize(temp_subs.name) == 0:
        os.unlink(temp_subs.name)
        return None
        
    return temp_subs.name

def clean_subtitles(subtitle_file):
    """Clean subtitle file and return path to cleaned version."""
    if not subtitle_file:
        return None
        
    temp_clean_subs = tempfile.NamedTemporaryFile(suffix=".srt", delete=False)
    temp_clean_subs.close()
    
    with open(subtitle_file, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # Clean the subtitle content
    cleaned_content = clean_subtitle_text(content)
    
    with open(temp_clean_subs.name, 'w', encoding='utf-8') as f:
        f.write(cleaned_content)
    
    return temp_clean_subs.name

def check_clean_subtitles(video_file):
    """Check if the video file has a subtitle track with title 'Clean'."""
    result = subprocess.run([
        "ffmpeg", "-i", video_file, "-hide_banner"
    ], capture_output=True, text=True)
    
    # Look for any of our identifying metadata in subtitle streams
    subtitle_streams = result.stderr.split("Stream #")
    
    for stream in subtitle_streams:
        if "Subtitle" in stream:
            identifiers = [
                r"handler_name\s*:\s*CleanSubtitles",
                r"comment\s*:\s*Clean subtitle track",
                r"title\s*:\s*Clean"
            ]
            for identifier in identifiers:
                if re.search(identifier, stream, re.IGNORECASE):
                    return True
    
    return False

def remove_clean_subtitles(video_file):
    """Remove the clean subtitle file if it exists."""
    base_name = os.path.splitext(video_file)[0]
    clean_srt = f"{base_name}.Clean.en.srt"
    
    if os.path.exists(clean_srt):
        os.unlink(clean_srt)
        print("Existing clean subtitle file removed.")

def add_clean_subtitles(video_file, clean_subtitle_file, output_file=None):
    """Add cleaned subtitles as a new track to the video."""
    if not clean_subtitle_file:
        return
        
    output_file = output_file or video_file
    temp_file = output_file + ".temp" + os.path.splitext(output_file)[1]
    
    if check_clean_subtitles(video_file):
        remove_clean_subtitles(video_file)
    
    # Get current subtitle track count
    subtitle_count = len(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s", 
         "-show_entries", "stream=index", "-of", "csv=p=0", video_file],
        capture_output=True, text=True
    ).stdout.strip().split('\n'))
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_file,
        "-i", clean_subtitle_file,
        "-map", "0",  # Include all streams from original
        "-map", "1:0",  # Add new subtitle track
        "-c", "copy",  # Copy all streams
        "-c:s", "mov_text",  # Convert subtitles to MOV format
        "-metadata:s:s:" + str(subtitle_count), "title=Clean",  # Add metadata to new subtitle track
        "-metadata:s:s:" + str(subtitle_count), "language=eng",
        "-metadata:s:s:" + str(subtitle_count), "handler_name=CleanSubtitles",
        "-metadata:s:s:" + str(subtitle_count), "comment=Clean subtitle track",
        temp_file
    ]
    
    subprocess.run(cmd)
    os.replace(temp_file, output_file)
    print("Clean subtitle track added.")

def save_clean_audio(video_file, clean_audio_file):
    """Save the cleaned audio as a separate WAV file next to the video."""
    base_name = os.path.splitext(video_file)[0]
    output_wav = f"{base_name}.Clean.wav"
    
    # Copy the clean audio to the output location
    with open(clean_audio_file, 'rb') as src, open(output_wav, 'wb') as dst:
        dst.write(src.read())
    
    print(f"Clean audio saved to '{output_wav}'")

# Main Functionality
def main():
    parser = argparse.ArgumentParser(description="Process a video file to mute specific words.")
    parser.add_argument("video_file", help="Path to the input video file")
    parser.add_argument("--force", action="store_true", help="Force replace the 'Clean' audio track.")
    parser.add_argument("--save-filter", action="store_true", help="Save the FFmpeg filter string to a file")
    parser.add_argument("--add-clean-subtitles", action="store_true", help="Add a clean subtitle track")
    parser.add_argument("--subtitles-only", action="store_true", help="Only process subtitles, skip audio processing")
    parser.add_argument("--embed-audio", action="store_true", help="Embed clean audio in video instead of saving as separate file")
    args = parser.parse_args()
    
    # Validate that --subtitles-only is only used with --add-clean-subtitles
    if args.subtitles_only and not args.add_clean_subtitles:
        parser.error("--subtitles-only can only be used with --add-clean-subtitles")

    video_file = args.video_file
    if not os.path.exists(video_file):
        print(f"Error: File '{video_file}' not found.")
        return

    # Process subtitles if flag is set
    if args.add_clean_subtitles:
        subtitle_file = extract_subtitles(video_file)
        if subtitle_file:
            print("Found subtitle track, creating clean version...")
            clean_subtitle_file = clean_subtitles(subtitle_file)
            
            # Save cleaned subtitles to a new file instead of embedding back into video
            base_name = os.path.splitext(video_file)[0]
            output_srt = f"{base_name}.Clean.en.srt"
            
            # Copy the file contents instead of trying to move across devices
            with open(clean_subtitle_file, 'rb') as src, open(output_srt, 'wb') as dst:
                dst.write(src.read())
            
            print(f"Clean subtitles saved to '{output_srt}'")
            
            os.unlink(subtitle_file)
            os.unlink(clean_subtitle_file)
        else:
            print("No subtitle track found to process.")

        if args.subtitles_only:
            return

    # Continue with audio processing
    if check_clean_audio(video_file):
        if not args.force:
            print("'Clean' audio track already exists. Use --force to replace it.")
            return

    base_name = os.path.splitext(os.path.basename(video_file))[0]
    output_dir = os.path.dirname(video_file)
    transcription_file = os.path.join(output_dir, f"{base_name}_transcription.json")

    # Rest of audio processing steps
    extracted_audio = extract_audio(video_file)
    transcribe_audio(extracted_audio, transcription_file)
    
    filter_string = generate_filter(transcription_file)
    if not filter_string:
        print("No sections to mute. Exiting.")
        os.unlink(extracted_audio)
        return
    
    if args.save_filter:
        filter_file = os.path.join(output_dir, f"{base_name}_filter-string.txt")
        with open(filter_file, 'w') as f:
            f.write(filter_string)
        print(f"FFmpeg filter string saved to '{filter_file}'")

    muted_audio = mute_audio(extracted_audio, filter_string)
    os.unlink(extracted_audio)

    if args.embed_audio:
        add_audio_to_video(video_file, muted_audio)
    else:
        save_clean_audio(video_file, muted_audio)
    os.unlink(muted_audio)

if __name__ == "__main__":
    main()