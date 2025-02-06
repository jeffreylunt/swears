# Audio Profanity Filter

This script processes video files to create a clean audio track by muting specified words. It uses Whisper for speech recognition and FFmpeg for audio processing.

## Prerequisites

- Python 3.9+
- FFmpeg
- Required Python packages:
  ```bash
  pip install whisper argparse pytest
  ```

## Installation

1. Clone this repository
2. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Basic Usage

```bash
python3.9 swears.py <input_video_file>
```

This will:
1. Extract audio from the video
2. Transcribe the audio using Whisper
3. Identify target words
4. Create a new audio track with those words muted
5. Save the clean audio as a separate WAV file (named `<input_video>.Clean.wav`)

### Options

- `--embed-audio`: Embed clean audio track in video instead of saving as separate file
  ```bash
  python3.9 swears.py video_file.mp4 --embed-audio
  ```

- `--force`: Replace existing clean audio track if one exists (only applies with --embed-audio)
  ```bash
  python3.9 swears.py video_file.mp4 --embed-audio --force
  ```

- `--add-clean-subtitles`: Generate clean subtitles and save them as a separate file
  ```bash
  python3.9 swears.py video_file.mp4 --add-clean-subtitles
  ```

### Output Files

By default, the script creates:
- `<input_video>.Clean.wav`: Clean audio file with profanity muted
- `<input_video>.Clean.en.srt`: Clean subtitles file (if --add-clean-subtitles is used)

When using --embed-audio, the script modifies the input video file by adding a new audio track labeled "Clean". The original audio track is preserved.

### Supported Formats

- Input/Output: MP4, MKV
- The script preserves the original container format

## Development

### Running Tests

1. Prepare test files:
   ```bash
   # Convert sample video to both formats for testing
   ffmpeg -i sample_video.mp4 sample_video.mkv
   ```

2. Run all tests:
   ```bash
   pytest test_swears.py -v
   ```

3. Run a specific test:
   ```bash
   pytest test_swears.py -v -k "test_clean_audio_track"
   ```

4. Run tests with debug output:
   ```bash
   pytest test_swears.py -v -s
   ```

### Test Files

The tests expect:
- `sample_video.mp4`: Sample video file with speech
- `sample_video.mkv`: Same content in MKV format

### Customizing Target Words

The default list of target words can be found in `swears.py`. You can modify the `DEFAULT_TARGET_WORDS` list to customize which words are muted.

## Troubleshooting

### Common Issues

1. **"Clean audio track already exists"**
   - Use the `--force` flag to replace the existing clean track
   - Or remove the clean track manually using a video editor

2. **No words were muted**
   - Check if the target words exist in the video
   - Verify the transcription file for accuracy
   - Consider adjusting the target word list

### Debug Output

To see detailed information about the audio tracks:

ffmpeg -i video_file.mp4 -hide_banner

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run the tests
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.