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
    "jesus", "christ",
    "cunt"
]

# Words that must match as exact whole words only (no prefix matching).
# e.g. "christ" matches "Christ" but NOT "Christine", "Christian", "Christopher".
EXACT_MATCH_WORDS = {"jesus", "christ"}


def build_regex_patterns(target_words=None):
    """Build compiled regex patterns for target words.

    Words in EXACT_MATCH_WORDS use \\bword\\b (exact match only).
    All other words use \\bword\\w*\\b (prefix matching, e.g. fuck -> fucking).
    """
    words = target_words if target_words is not None else DEFAULT_TARGET_WORDS
    patterns = []
    for word in words:
        if word.lower() in EXACT_MATCH_WORDS:
            patterns.append(re.compile(rf"\b{word}\b", re.IGNORECASE))
        else:
            patterns.append(re.compile(rf"\b{word}\w*\b", re.IGNORECASE))
    return patterns

# Functions
def find_english_audio_stream(video_file):
    """Find the best English audio stream index in a video file.

    Returns the relative audio stream index (e.g., 0 for first audio, 1 for second)
    for use with ffmpeg's -map 0:a:N selector. Defaults to 0 if no English track found.
    """
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "a",
        video_file
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)

    try:
        streams = json.loads(probe_result.stdout).get("streams", [])
    except (json.JSONDecodeError, KeyError):
        return 0

    # Look for English audio tracks
    for i, stream in enumerate(streams):
        lang = stream.get("tags", {}).get("language", "").lower()
        if lang == "eng":
            print(f"Found English audio track at audio stream index {i} (absolute index {stream['index']})")
            return i

    # No English track found, default to first audio stream
    print("No English audio track found, using first audio stream")
    return 0


def extract_audio(video_file):
    """Extract audio from the video file and return the temporary audio file path."""
    # Find the English audio stream
    audio_stream_idx = find_english_audio_stream(video_file)

    # Probe the selected audio stream for channel information
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", f"a:{audio_stream_idx}",
        video_file
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    audio_info = json.loads(probe_result.stdout)

    # Get number of channels from selected audio stream, default to 2 if not found
    channels = 2
    if audio_info.get("streams") and len(audio_info["streams"]) > 0:
        channels = int(audio_info["streams"][0].get("channels", 2))

    temp_audio = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    temp_audio.close()
    print(f"Extracting {channels}-channel audio from video (audio stream {audio_stream_idx})...")

    subprocess.run([
        "ffmpeg", "-y", "-i", video_file,
        "-map", f"0:a:{audio_stream_idx}",  # Select the English audio stream
        "-vn",  # No video
        "-c:a", "aac",  # Use AAC codec
        "-b:a", "256k",  # High quality bitrate
        "-ar", "44100",  # Standard sample rate
        "-ac", str(channels),  # Preserve original channel count
        temp_audio.name
    ])
    return temp_audio.name

def transcribe_audio(audio_file, transcription_file):
    """Transcribe the full audio and save the transcription (legacy pipeline)."""
    print("Loading Whisper model...")
    model = whisper.load_model("base.en")
    print("Transcribing full audio...")
    result = model.transcribe(audio_file, word_timestamps=True, verbose=True)
    with open(transcription_file, "w") as f:
        json.dump(result, f, indent=4)
    print(f"Transcription saved to '{transcription_file}'")


def generate_filter(transcription_file, buffer=0.1, target_words=None):
    """Generate FFmpeg filter string from a full Whisper transcription file."""
    print("Generating mute sections from transcription...")
    with open(transcription_file, "r") as f:
        transcription = json.load(f)

    regex_patterns = build_regex_patterns(target_words)
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

def generate_filter_from_mute_windows(mute_windows, buffer=0.1):
    """Generate FFmpeg filter string from a list of mute windows.

    Each mute window is a dict with 'start' and 'end' keys (seconds).
    """
    if not mute_windows:
        print("No mute windows to apply.")
        return None

    filter_parts = []
    for window in mute_windows:
        start = max(0, window["start"] - buffer)
        end = window["end"] + buffer
        filter_parts.append(f"volume=enable='between(t,{start},{end})':volume=0")

    filter_string = ",".join(filter_parts)
    print(f"Generated FFmpeg filter with {len(filter_parts)} mute windows")
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

    temp_muted_audio = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    temp_muted_audio.close()
    print(f"Applying mute sections to {channels}-channel audio...")

    subprocess.run([
        "ffmpeg", "-y", "-i", audio_file,
        "-af", filter_string,
        "-c:a", "aac",
        "-b:a", "256k",
        "-ar", "44100",
        "-ac", str(channels),
        temp_muted_audio.name
    ])
    print(f"Muted audio temporarily saved to '{temp_muted_audio.name}'")
    return temp_muted_audio.name

def check_clean_audio(video_file):
    """Check if the video file has an audio track with title 'Clean' or a separate clean audio file."""
    # Check for separate clean audio file
    base_name = os.path.splitext(video_file)[0]
    clean_audio_file = f"{base_name}.Clean.m4a"
    if os.path.exists(clean_audio_file):
        return True

    # Check for embedded clean audio track
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
        "-c:a", "aac",  # Use AAC codec
        "-b:a", "256k",  # High quality bitrate
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
    regex_patterns = build_regex_patterns(target_words)

    cleaned_text = text
    for pattern in regex_patterns:
        cleaned_text = pattern.sub(lambda m: '_' * len(m.group(0)), cleaned_text)
    return cleaned_text

def extract_subtitles(video_file):
    """Extract subtitles from video file if they exist.

    Uses ffprobe to find the best English subtitle track, preferring
    non-forced, non-SDH tracks. Falls back to first subtitle track
    if no English tracks are found.
    """
    temp_subs = tempfile.NamedTemporaryFile(suffix=".srt", delete=False)
    temp_subs.close()

    # Use ffprobe to find the best English subtitle track
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "s",
        video_file
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)

    best_track = None
    try:
        streams = json.loads(probe_result.stdout).get("streams", [])
        eng_tracks = [s for s in streams if s.get("tags", {}).get("language") == "eng"]

        if eng_tracks:
            # Prefer non-forced, non-SDH English track (the full dialogue track)
            for track in eng_tracks:
                title = (track.get("tags", {}).get("title") or "").lower()
                is_forced = track.get("disposition", {}).get("forced", 0) == 1 or "forced" in title
                is_sdh = "sdh" in title
                if not is_forced and not is_sdh:
                    best_track = track["index"]
                    break
            # Fall back to any non-forced English track (including SDH)
            if best_track is None:
                for track in eng_tracks:
                    title = (track.get("tags", {}).get("title") or "").lower()
                    is_forced = track.get("disposition", {}).get("forced", 0) == 1 or "forced" in title
                    if not is_forced:
                        best_track = track["index"]
                        break
            # Last resort among English tracks: first one
            if best_track is None:
                best_track = eng_tracks[0]["index"]
    except (json.JSONDecodeError, KeyError):
        pass

    if best_track is not None:
        # Extract the specific track by absolute stream index
        print(f"Extracting subtitle track index {best_track}")
        subprocess.run([
            "ffmpeg", "-y", "-i", video_file,
            "-map", f"0:{best_track}",
            temp_subs.name
        ], capture_output=True)
    else:
        # No English tracks found via probe, try first subtitle track
        subprocess.run([
            "ffmpeg", "-y", "-i", video_file,
            "-map", "0:s:0",
            temp_subs.name
        ], capture_output=True)

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
    """Save the cleaned audio as a separate AAC file next to the video."""
    base_name = os.path.splitext(video_file)[0]
    output_aac = f"{base_name}.Clean.m4a"

    # Copy the clean audio to the output location
    with open(clean_audio_file, 'rb') as src, open(output_aac, 'wb') as dst:
        dst.write(src.read())

    print(f"Clean audio saved to '{output_aac}'")

def has_target_words_in_subtitles(subtitle_file, target_words=None):
    """Check if any target words exist in the subtitle file."""
    if not subtitle_file:
        return False

    regex_patterns = build_regex_patterns(target_words)

    with open(subtitle_file, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    return any(pattern.search(content) for pattern in regex_patterns)


# --- Targeted Whisper Pipeline ---

def srt_time_to_seconds(time_str):
    """Convert SRT timestamp (HH:MM:SS,mmm) to seconds."""
    match = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", time_str)
    if not match:
        return 0.0
    h, m, s, ms = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
    return h * 3600 + m * 60 + s + ms / 1000.0

def parse_srt(subtitle_file):
    """Parse an SRT file into a list of segments.

    Returns list of dicts with keys: index, start, end, text
    where start/end are in seconds.
    """
    with open(subtitle_file, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    segments = []
    blocks = content.strip().split("\n\n")
    timestamp_re = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})")

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # Find timestamp line
        ts_match = None
        ts_line_idx = None
        for i, line in enumerate(lines):
            ts_match = timestamp_re.search(line)
            if ts_match:
                ts_line_idx = i
                break

        if not ts_match or ts_line_idx is None:
            continue

        start = srt_time_to_seconds(ts_match.group(1))
        end = srt_time_to_seconds(ts_match.group(2))
        # Text is everything after the timestamp line
        text = "\n".join(lines[ts_line_idx + 1:])
        # Strip HTML/font tags for matching purposes
        clean_text = re.sub(r"<[^>]+>", "", text)

        try:
            idx = int(lines[0].strip())
        except ValueError:
            idx = 0

        segments.append({
            "index": idx,
            "start": start,
            "end": end,
            "text": clean_text,
            "raw_text": text,
        })

    return segments

def find_flagged_srt_segments(srt_segments, target_words=None):
    """Find SRT segments that contain target swear words.

    Returns list of dicts with keys: start, end, text, matched_words
    """
    words_to_target = target_words if target_words is not None else DEFAULT_TARGET_WORDS
    all_patterns = build_regex_patterns(target_words)
    regex_patterns = list(zip(words_to_target, all_patterns))

    flagged = []
    for seg in srt_segments:
        matched = []
        for word, pattern in regex_patterns:
            if pattern.search(seg["text"]):
                matched.extend(m.group(0) for m in pattern.finditer(seg["text"]))
        if matched:
            flagged.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "matched_words": matched,
            })

    return flagged

def extract_clip_audio(full_audio_file, start_time, end_time):
    """Extract a short audio clip from the full audio file.

    Returns path to temporary clip file.
    """
    clip_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    clip_file.close()

    duration = end_time - start_time
    subprocess.run([
        "ffmpeg", "-y",
        "-i", full_audio_file,
        "-ss", str(start_time),
        "-t", str(duration),
        "-ar", "16000",  # Whisper expects 16kHz
        "-ac", "1",      # Mono for Whisper
        clip_file.name
    ], capture_output=True)

    return clip_file.name

def transcribe_clip(model, clip_file, clip_offset):
    """Run Whisper on a short audio clip and return word-level timestamps.

    clip_offset is the start time of the clip relative to the full audio,
    so we can convert clip-relative timestamps back to absolute timestamps.

    Returns list of dicts with keys: word, start, end (absolute timestamps).
    """
    result = model.transcribe(clip_file, word_timestamps=True, verbose=False)

    words = []
    for segment in result.get("segments", []):
        for word_info in segment.get("words", []):
            words.append({
                "word": word_info["word"],
                "start": word_info["start"] + clip_offset,
                "end": word_info["end"] + clip_offset,
            })

    return words

def targeted_transcription(video_file, subtitle_file, full_audio_file, transcription_file, target_words=None, clip_buffer=2.0):
    """Run targeted Whisper transcription on flagged subtitle segments only.

    Instead of transcribing the entire audio, this:
    1. Parses SRT subtitles to find segments with swear words
    2. Extracts short audio clips around those segments
    3. Runs Whisper only on those clips for precise word timestamps
    4. Falls back to SRT timestamp-based muting if Whisper misses the word

    Returns list of mute windows (dicts with 'start', 'end', 'source' keys).
    Also saves transcription data to transcription_file.
    """
    regex_patterns = build_regex_patterns(target_words)

    # Parse SRT and find flagged segments
    srt_segments = parse_srt(subtitle_file)
    flagged = find_flagged_srt_segments(srt_segments, target_words)

    if not flagged:
        print("No target words found in subtitles.")
        # Save empty transcription
        with open(transcription_file, "w") as f:
            json.dump({"pipeline": "targeted", "flagged_segments": 0, "mute_windows": []}, f, indent=4)
        return []

    print(f"Found {len(flagged)} subtitle segments with target words")
    for seg in flagged:
        text_preview = seg["text"][:60].replace("\n", " ")
        print(f"  [{seg['start']:.1f}s - {seg['end']:.1f}s] {text_preview}... => {seg['matched_words']}")

    # Load Whisper model once
    print("\nLoading Whisper model for targeted transcription...")
    model = whisper.load_model("base.en")

    mute_windows = []
    clip_results = []

    for seg in flagged:
        # Extract a clip with buffer around the subtitle segment
        clip_start = max(0, seg["start"] - clip_buffer)
        clip_end = seg["end"] + clip_buffer

        text_preview = seg["text"][:50].replace("\n", " ")
        print(f"\nProcessing segment [{seg['start']:.1f}s - {seg['end']:.1f}s]: {text_preview}...")
        clip_file = extract_clip_audio(full_audio_file, clip_start, clip_end)

        # Run Whisper on the clip
        words = transcribe_clip(model, clip_file, clip_start)
        os.unlink(clip_file)

        # Search for target words in Whisper results
        found_in_whisper = False
        whisper_words_for_segment = []

        for word_info in words:
            if any(p.search(word_info["word"]) for p in regex_patterns):
                mute_windows.append({
                    "start": word_info["start"],
                    "end": word_info["end"],
                    "word": word_info["word"].strip(),
                    "source": "whisper",
                })
                found_in_whisper = True
                whisper_words_for_segment.append(word_info)
                print(f"  Whisper found: '{word_info['word'].strip()}' at {word_info['start']:.2f}s - {word_info['end']:.2f}s")

        if not found_in_whisper:
            # Fallback: use SRT timestamp with conservative window
            # Mute the entire subtitle segment duration
            mute_windows.append({
                "start": seg["start"],
                "end": seg["end"],
                "word": ", ".join(seg["matched_words"]),
                "source": "srt_fallback",
            })
            print(f"  Whisper missed target words, falling back to SRT timing: {seg['start']:.2f}s - {seg['end']:.2f}s")

        clip_results.append({
            "srt_start": seg["start"],
            "srt_end": seg["end"],
            "srt_text": seg["text"],
            "matched_words": seg["matched_words"],
            "whisper_words": [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in words],
            "target_words_found": [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in whisper_words_for_segment],
            "used_fallback": not found_in_whisper,
        })

    # Save transcription data
    transcription_data = {
        "pipeline": "targeted",
        "flagged_segments": len(flagged),
        "total_mute_windows": len(mute_windows),
        "whisper_hits": sum(1 for w in mute_windows if w["source"] == "whisper"),
        "srt_fallbacks": sum(1 for w in mute_windows if w["source"] == "srt_fallback"),
        "mute_windows": mute_windows,
        "clip_results": clip_results,
    }
    with open(transcription_file, "w") as f:
        json.dump(transcription_data, f, indent=4)
    print(f"\nTranscription saved to '{transcription_file}'")
    print(f"  {transcription_data['whisper_hits']} words muted via Whisper (precise)")
    print(f"  {transcription_data['srt_fallbacks']} segments muted via SRT fallback (conservative)")

    return mute_windows


# Main Functionality
def main():
    parser = argparse.ArgumentParser(description="Process a video file to mute specific words.")
    parser.add_argument("video_file", help="Path to the input video file")
    parser.add_argument("--force", action="store_true", help="Force replace the 'Clean' audio track.")
    parser.add_argument("--save-filter", action="store_true", help="Save the FFmpeg filter string to a file")
    parser.add_argument("--add-clean-subtitles", action="store_true",
                       help="Add a clean subtitle track (default: true)", default=True)
    parser.add_argument("--subtitles-only", action="store_true", help="Only process subtitles, skip audio processing")
    parser.add_argument("--embed-audio", action="store_true", help="Embed clean audio in video instead of saving as separate file")
    parser.add_argument("--skip-subtitle-check", action="store_true", help="Skip checking subtitles for target words")
    parser.add_argument("--full-whisper", action="store_true", help="Force full-episode Whisper transcription instead of targeted")
    args = parser.parse_args()

    video_file = args.video_file
    if not os.path.exists(video_file):
        print(f"Error: File '{video_file}' not found.")
        return

    # Check for existing clean audio
    if check_clean_audio(video_file):
        if not args.force:
            print("'Clean' audio track already exists. Use --force to replace it.")
            return

    base_name = os.path.splitext(os.path.basename(video_file))[0]
    output_dir = os.path.dirname(video_file)
    transcription_file = os.path.join(output_dir, f"{base_name}_transcription.json")

    if os.path.exists(transcription_file) and not args.force:
        print("Transcription already exists. Skipping.")
        return

    # Extract subtitles
    subtitle_file = extract_subtitles(video_file)
    has_subtitles = subtitle_file is not None
    has_swears_in_subs = False

    if subtitle_file and not args.skip_subtitle_check:
        print("Checking subtitles for target words...")
        has_swears_in_subs = has_target_words_in_subtitles(subtitle_file)

        if has_swears_in_subs:
            print("Found target words in subtitles, creating clean version...")
            clean_subtitle_file = clean_subtitles(subtitle_file)

            # Save cleaned subtitles
            base_path = os.path.splitext(video_file)[0]
            output_srt = f"{base_path}.Clean.en.srt"
            with open(clean_subtitle_file, 'rb') as src, open(output_srt, 'wb') as dst:
                dst.write(src.read())
            print(f"Clean subtitles saved to '{output_srt}'")
            os.unlink(clean_subtitle_file)
        else:
            print("No target words found in subtitles, skipping audio processing.")
            os.unlink(subtitle_file)
            return
    elif subtitle_file:
        pass  # skip_subtitle_check mode
    else:
        print("No subtitle track found, will use full Whisper transcription.")

    if args.subtitles_only:
        if subtitle_file:
            os.unlink(subtitle_file)
        return

    # Extract full audio for processing
    extracted_audio = extract_audio(video_file)

    # Decide pipeline: targeted (subtitle-driven) vs full Whisper
    if has_subtitles and has_swears_in_subs and not args.full_whisper:
        # --- Targeted Pipeline ---
        print("\n=== Using targeted Whisper pipeline (subtitle-driven) ===")
        mute_windows = targeted_transcription(
            video_file, subtitle_file, extracted_audio, transcription_file
        )
        os.unlink(subtitle_file)

        if not mute_windows:
            print("No mute windows generated. Exiting.")
            os.unlink(extracted_audio)
            return

        filter_string = generate_filter_from_mute_windows(mute_windows)
    else:
        # --- Full Whisper Pipeline (fallback for no subtitles) ---
        if subtitle_file:
            os.unlink(subtitle_file)
        print("\n=== Using full Whisper transcription (no subtitles available) ===")
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
