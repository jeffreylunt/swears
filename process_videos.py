import os
import argparse
import subprocess
from pathlib import Path

# Common video file extensions
VIDEO_EXTENSIONS = {
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', 
    '.webm', '.m4v', '.mpg', '.mpeg', '.m2v'
}

def find_video_files(directory):
    """Recursively find all video files in the given directory."""
    video_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if Path(file).suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(os.path.join(root, file))
    return video_files

def process_video(video_path, args):
    """Process a single video file using swears.py."""
    print(f"\nProcessing: {video_path}")
    
    # Build command for swears.py
    cmd = ["python3.9", "swears.py", video_path]
    
    # Add optional arguments if specified
    if args.force:
        cmd.append("--force")
    if args.save_filter:
        cmd.append("--save-filter")
    if not args.add_clean_subtitles:
        cmd.append("--no-clean-subtitles")
    if args.subtitles_only:
        cmd.append("--subtitles-only")
    if args.embed_audio:
        cmd.append("--embed-audio")
    if args.skip_subtitle_check:
        cmd.append("--skip-subtitle-check")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Successfully processed: {video_path}")
            if result.stdout:
                print("Output:", result.stdout)
        else:
            print(f"Error processing {video_path}:")
            print(result.stderr)
    except Exception as e:
        print(f"Failed to process {video_path}: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="Recursively process video files in a directory using swears.py")
    parser.add_argument("directory", help="Directory to search for video files")
    parser.add_argument("--force", action="store_true", help="Force replace existing 'Clean' audio tracks")
    parser.add_argument("--save-filter", action="store_true", help="Save the FFmpeg filter string to a file")
    parser.add_argument("--add-clean-subtitles", action="store_true", default=True, help="Add a clean subtitle track (default: true)")
    parser.add_argument("--subtitles-only", action="store_true", help="Only process subtitles, skip audio processing")
    parser.add_argument("--embed-audio", action="store_true", help="Embed clean audio in video instead of saving as separate file")
    parser.add_argument("--skip-subtitle-check", action="store_true", help="Skip checking subtitles for target words")
    parser.add_argument("--dry-run", action="store_true", help="Show which files would be processed without processing them")
    args = parser.parse_args()

    # Validate directory
    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a valid directory")
        return

    # Find all video files
    video_files = find_video_files(args.directory)
    
    if not video_files:
        print(f"No video files found in {args.directory}")
        return

    print(f"Found {len(video_files)} video files to process:")
    for video in video_files:
        print(f"- {video}")

    if args.dry_run:
        print("\nDry run completed. Use without --dry-run to process files.")
        return

    # Process each video file
    for i, video in enumerate(video_files, 1):
        print(f"\nProcessing file {i} of {len(video_files)}")
        process_video(video, args)

    print("\nAll videos processed!")

if __name__ == "__main__":
    main() 