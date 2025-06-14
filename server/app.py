from flask import Flask, render_template, send_file, abort, jsonify, Response
from werkzeug.utils import safe_join

from picamera2 import Picamera2
from libcamera import Transform
import cv2

import atexit
import logging
import os
import signal
import sys
import time
from typing import List

sys.path.append(r"/home/brend/Documents")
import timestamping

# todo: it should be able to handle files of differing length somehow
# ideas: maybe blacken out the screen to show user during video seeking that
# that whole chunk of time has no data
VIDS_DURATION_SECONDS_ASSUMED = 15.0 # currently just hardcording this 15 seconds assumption

USB_DEVICE_NAME = "E657-3701"
USB_DEVICE_NAME = "E657-3701"
USB_PATH = os.path.join("/media/brend", USB_DEVICE_NAME)
USB_VID_PATH = os.path.join(USB_PATH, "vidfiles")

app = Flask(__name__)

def cleanup():
    logging.info("Running `cleanup()`...")
    try:
        picam2.close()
        logging.info("`cleanup`: picam2 closed")
    except:
        logging.critical("Error during picamera cleanup")

atexit.register(cleanup)

def signal_handler(sig, frame):
    sys.exit(0) # this just triggers atexit ^^^

signal.signal(signal.SIGINT, signal_handler)   # ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill or system shutdown
signal.signal(signal.SIGQUIT, signal_handler)  # quit signal

@app.route("/")
def home():
    return render_template("home.html")

###############################################################################

def fetch_mp4_files(videos_path: str) -> List[str]:
    return sorted([f for f in os.listdir(videos_path) if f.endswith(".mp4")])

def generate_stream():
    logging.info("Stream initialized.")
    error_last_frame_flag = False
    try:
        while True:
            try:
                frame = picam2.capture_array()
                error_last_frame_flag = False
            except:
                logging.warning("Issue capturing one frame in stream.")
                if error_last_frame_flag:
                    raise RuntimeError("Two corrupt stream frames in a row, aborting stream")
                error_last_frame_flag = True
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                logging.warning("Issue streaming frame in `generate_stream()`")
                continue
            yield (b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.06)  # about ~15fps ish
    except GeneratorExit:
        logging.info("Client disconnected from stream.")
    except Exception as e:
        logging.critical(f"Exception caught in stream: {e}")

@app.route("/playlist")
def playlist():
    try:
        mp4_files = fetch_mp4_files(USB_VID_PATH)
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
        mp4_files = fetch_mp4_files(USB_VID_PATH)
    except:
        abort(404, description="Error fetching + sorting .mp4 files in browse")

    return render_template("browse.html", files=mp4_files)

@app.route('/stream')
def stream():
    return render_template('stream.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/video/<filename>")
def serve_video(filename):
    safe_path = safe_join(USB_VID_PATH, filename)
    if not safe_path or not os.path.isfile(safe_path):
        abort(404, description="Error fetching files from specified drive in Flask app.py")
    return send_file(safe_path, mimetype="video/mp4")

if __name__ == "__main__": 
    # initialize logger
    logging.basicConfig(
        level=logging.INFO,  # Decreasing verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler("app_last.log", mode="w"),
            logging.StreamHandler()  # also prints to console
        ]
    )

    # initialize picam for stream
    picam2 = Picamera2()
    picam2.configure(picam2.create_preview_configuration(
        main={"size": (640, 480)},
        transform=Transform(hflip=True, vflip=True)
    ))
    picam2.start()

    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
