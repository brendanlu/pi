from flask import Flask, render_template, send_file, abort
from werkzeug.utils import safe_join
app = Flask(__name__)

import os
import signal
import sys
import atexit

USB_DEVICE_NAME = "E657-3701"
videos_path = f"/media/brend/{USB_DEVICE_NAME}"

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

@app.route("/browse")
def browse(): 
    try:
        mp4_files = [f for f in os.listdir(videos_path) if f.endswith(".mp4")]
        mp4_files.sort()
    except:
        abort(404, descripton="Error displaying sorted .mp4 files")

    return render_template("browse.html", files=mp4_files)

@app.route("/video/<filename>")
def serve_video(filename):
    safe_path = safe_join(videos_path, filename)
    if not safe_path or not os.path.isfile(safe_path):
        abort(404, description="Error fetching files from specified drive in Flask app.py")
    return send_file(safe_path, mimetype="video/mp4")

if __name__ == "__main__": 
    app.run(host='0.0.0.0', port=5000, debug=False)
