"""
Requires a audio recording and playback device.
When run, it records from the audio device and when keyboard interrupted it
plays it back via the playback device.
"""

import subprocess 
import signal
import os

FILENAME = "test-mic.wav"

# Run command `arecord -l` to see what audio record devices there are
# This script is currently using USB2 audio input from a USB webcam (card 3)
AUDIO_INPUT_CARD_NUMBER = 3

# Run command `aplay -l` to see what audio playback devices there are
# This script is currently using 3.5mm headphone jack (card 2)
AUDIO_PLAYBACK_CARD_NUMBER = 2

# arecord
# Starts the ALSA sound recorder.
# 
# -D plughw:3,0
# Specifies the device to record from:
# 3 = ALSA card number (your USB webcam mic)
# 0 = ALSA device number (usually the first audio input on the card)
# plughw uses ALSA's plug plugin, which automatically converts formats if
# needed (e.g. sample rate or bit depth).
# 
# -f cd
# Sets the format to "CD quality":
# 16-bit
# Stereo (2 channels)
# 44.1 kHz sample rate
# 
# -t wav
# Sets the file format to .wav (rather than raw PCM data).
#
# -d 5
# Duration: record for 5 seconds.
# 
# test-mic.wav
# The filename to save the audio to.
record_cmd = [
    "arecord",
    "-D", f"plughw:{AUDIO_INPUT_CARD_NUMBER},0",
    "-f", "cd",
    "-t", "wav",
    FILENAME
]

playback_cmd = [
    "aplay",
    "-D", f"plughw:{AUDIO_PLAYBACK_CARD_NUMBER},0",
    FILENAME
]

if __name__ == "__main__":
    try:
        print("Recording... Press Ctrl+C to stop...")
        recording_process = subprocess.Popen(record_cmd)
        recording_process.wait()
    except KeyboardInterrupt:
        print("\nStopping recording")
        recording_process.send_signal(signal.SIGINT)
        recording_process.wait()
        print("Playing back recording now...")
        subprocess.run(playback_cmd)
        os.remove(FILENAME)
