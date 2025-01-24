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

@pytest.fixture(autouse=True)
def cleanup():
    """Clean up generated files after tests"""
    yield
    files_to_clean = [
        EXPECTED_TRANSCRIPTION,
        TEST_OUTPUT_VIDEO_MP4,
        TEST_OUTPUT_VIDEO_MKV,
        *[f for f in os.listdir() if f.endswith(".m4a")]  # Clean up temp audio files
    ]
    for file in files_to_clean:
        try:
            os.remove(file)
        except FileNotFoundError:
            pass 