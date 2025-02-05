import os
import json
import pytest
import shutil
from pathlib import Path
from swears import (
    transcribe_audio,
    check_clean_audio,
    extract_audio,
    mute_audio,
    generate_filter,
    add_audio_to_video
)

# Constants for test files
SAMPLE_VIDEO_MP4 = "sample_video.mp4"
SAMPLE_VIDEO_MKV = "sample_video.mkv"
TEST_OUTPUT_VIDEO_MP4 = "test_output_video.mp4"
TEST_OUTPUT_VIDEO_MKV = "test_output_video.mkv"
EXPECTED_TRANSCRIPTION = "sample_video_transcription.json"
BASE_DIR = Path(__file__).parent

# Add test words
TEST_TARGET_WORDS = ["irish", "pension", "detective"]

@pytest.fixture(params=[
    (SAMPLE_VIDEO_MP4, TEST_OUTPUT_VIDEO_MP4),
    (SAMPLE_VIDEO_MKV, TEST_OUTPUT_VIDEO_MKV)
])
def video_files(request):
    """Fixture to test both MP4 and MKV formats"""
    return request.param

def test_sample_videos_exist(video_files):
    """Verify that the sample video files exist"""
    input_video, _ = video_files
    assert os.path.exists(input_video), f"Sample video file {input_video} not found"

def test_transcription_creation(video_files):
    """Test that transcription is created and contains expected structure"""
    input_video, _ = video_files
    # Extract and transcribe audio
    extracted_audio = extract_audio(input_video)
    transcribe_audio(extracted_audio, EXPECTED_TRANSCRIPTION)
    
    # Check transcription file exists
    transcription_file = BASE_DIR / EXPECTED_TRANSCRIPTION
    assert transcription_file.exists(), "Transcription file was not created"
    
    # Verify transcription content structure
    with open(transcription_file) as f:
        transcription = json.load(f)
    
    # Check required fields in transcription
    assert "text" in transcription, "Transcription missing 'text' field"
    assert "segments" in transcription, "Transcription missing 'segments' field"
    assert "words" in transcription["segments"][0], "Transcription segments missing 'words' field"

def test_clean_audio_track(video_files):
    """Test that the clean audio track is added to the video"""
    input_video, output_video = video_files
    # First run - should create clean track
    extracted_audio = extract_audio(input_video)
    transcribe_audio(extracted_audio, EXPECTED_TRANSCRIPTION)
    filter_string = generate_filter(EXPECTED_TRANSCRIPTION, target_words=TEST_TARGET_WORDS)
    muted_audio = mute_audio(extracted_audio, filter_string)
    
    # Create test output file
    add_audio_to_video(input_video, muted_audio, output_file=output_video)
    
    # Check if clean track exists in the output file
    assert check_clean_audio(output_video), "Clean audio track was not added"

def test_muted_sections(video_files):
    """Test that muted sections are created correctly"""
    input_video, _ = video_files
    # Extract and transcribe
    extracted_audio = extract_audio(input_video)
    transcribe_audio(extracted_audio, EXPECTED_TRANSCRIPTION)
    
    # Load transcription to check muted words
    transcription_file = BASE_DIR / EXPECTED_TRANSCRIPTION
    with open(transcription_file) as f:
        transcription = json.load(f)
    
    # Generate filter string and verify it contains mute sections
    filter_string = generate_filter(EXPECTED_TRANSCRIPTION, target_words=TEST_TARGET_WORDS)
    assert filter_string is not None, "No mute sections were generated"
    assert "volume=0" in filter_string, "No volume muting found in filter string"

def test_save_filter_string(video_files):
    """Test that filter string is correctly saved to a file"""
    input_video, _ = video_files
    base_name = os.path.splitext(os.path.basename(input_video))[0]
    filter_file = f"{base_name}_filter-string.txt"
    
    # Extract and transcribe
    extracted_audio = extract_audio(input_video)
    transcribe_audio(extracted_audio, EXPECTED_TRANSCRIPTION)
    
    # Generate filter string
    filter_string = generate_filter(EXPECTED_TRANSCRIPTION, target_words=TEST_TARGET_WORDS)
    
    # Save filter string to file
    with open(filter_file, 'w') as f:
        f.write(filter_string)
    
    # Verify file exists and contains the filter string
    assert os.path.exists(filter_file), f"Filter string file {filter_file} was not created"
    with open(filter_file, 'r') as f:
        saved_filter = f.read()
    assert saved_filter == filter_string, "Saved filter string doesn't match generated filter string"
    
    # Clean up
    os.remove(filter_file)

@pytest.fixture(autouse=True)
def cleanup():
    """Clean up generated files after tests"""
    yield
    files_to_clean = [
        EXPECTED_TRANSCRIPTION,
        TEST_OUTPUT_VIDEO_MP4,
        TEST_OUTPUT_VIDEO_MKV,
        *[f for f in os.listdir() if f.endswith(".m4a")],  # Clean up temp audio files
        *[f for f in os.listdir() if f.endswith("_filter-string.txt")]  # Clean up filter string files
    ]
    for file in files_to_clean:
        try:
            os.remove(file)
        except FileNotFoundError:
            pass 