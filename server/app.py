from flask import Flask, render_template, send_file, abort, jsonify
from werkzeug.utils import safe_join
app = Flask(__name__)

import os
import signal
import sys
import atexit
from typing import List

sys.path.append(r"/home/brend/Documents")
import timestamping

USB_DEVICE_NAME = "E657-3701"
# todo: it should be able to handle files of differing length somehow
# ideas: maybe blacken out the screen to show user during video seeking that
# that whole chunk of time has no data
VIDS_DURATION_SECONDS_ASSUMED = 15.0 # currently just hardcording this 15 seconds assumption
videos_path = f"/media/brend/{USB_DEVICE_NAME}/vidfiles"

def fetch_mp4_files(videos_path: str) -> List[str]:
    return sorted([f for f in os.listdir(videos_path) if f.endswith(".mp4")])

def cleanup():
    print("\nRunning app.py `cleanup()`...")

atexit.register(cleanup)

def signal_handler(sig, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)   # ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill or system shutdown
signal.signal(signal.SIGQUIT, signal_handler)  # quit signal

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/playlist")
def playlist():
    try:
        mp4_files = fetch_mp4_files(videos_path)
    except:
        abort(404, description="Error fetching + sorting .mp4 files for playback")
    try:
        video_data = []
        for mp4_file in mp4_files:
            dt, camera_name = timestamping.parse_filename(mp4_file) # TODO: pass in camera_name to JS
            if dt:
                video_data.append({
                    "filename": mp4_file,
                    "start": timestamping.dt_strfmt(dt),
                    "duration_seconds": VIDS_DURATION_SECONDS_ASSUMED
                })
        assert video_data
    except:
        abort(404, description="Error parsing filenames")

    return jsonify(video_data)

@app.route("/browse")
def browse(): 
    try:
        mp4_files = fetch_mp4_files(videos_path)
    except:
        abort(404, descripton="Error fetching + sorting .mp4 files in browse")

    return render_template("browse.html", files=mp4_files)

@app.route("/video/<filename>")
def serve_video(filename):
    safe_path = safe_join(videos_path, filename)
    if not safe_path or not os.path.isfile(safe_path):
        abort(404, description="Error fetching files from specified drive in Flask app.py")
    return send_file(safe_path, mimetype="video/mp4")

if __name__ == "__main__": 
    app.run(host='0.0.0.0', port=5000, debug=False)
