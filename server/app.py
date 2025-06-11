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
    print("Running app.py `cleanup()`...")

atexit.register(cleanup)

def signal_handler(sig, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

@app.route("/")
def index(): 
    try:
        mp4_files = [f for f in os.listdir(videos_path) if f.endswith(".mp4")]
    except:
        sys.exit("ERROR: issue accessing videos directory")
    return render_template("index.html", files=mp4_files)

@app.route("/video/<filename>")
def serve_video(filename):
    safe_path = safe_join(videos_path, filename)
    if not safe_path or not os.path.isfile(safe_path):
        abort(404)
    return send_file(safe_path, mimetype="video/mp4")

if __name__ == "__main__": 
    app.run(host='0.0.0.0', port=5000, debug=False)
