import os
import pytest
from pathlib import Path
from process_videos import find_video_files

# Constants
SAMPLE_VIDEO_MP4 = "sample_video.mp4"
SAMPLE_VIDEO_MKV = "sample_video.mkv"
BASE_DIR = Path(__file__).parent

def test_find_video_files():
    """Test that the script finds both sample videos in the repo."""
    video_files = find_video_files(BASE_DIR)
    
    # Check if sample videos exist and are found
    expected_videos = set()
    if os.path.exists(SAMPLE_VIDEO_MP4):
        expected_videos.add(str(BASE_DIR / SAMPLE_VIDEO_MP4))
    if os.path.exists(SAMPLE_VIDEO_MKV):
        expected_videos.add(str(BASE_DIR / SAMPLE_VIDEO_MKV))
    
    assert set(video_files) == expected_videos, "Did not find expected sample videos"