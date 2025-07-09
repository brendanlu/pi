from flask import Flask, render_template, send_file, abort, jsonify, Response
from werkzeug.utils import safe_join

from picamera2 import Picamera2
from libcamera import Transform
import cv2

import atexit
import json
import logging
import os
import signal
import subprocess 
import sys
import time
from typing import List

sys.path.append(r"/home/brend/Documents")
import timestamping

VIDEO_DURATIONS_CACHE_PATH = "_video_durations.json"

# USB_DEVICE_NAME = "E657-3701"
USB_DEVICE_NAME = "DYNABOOK"
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
    # YOU MUST SYS.EXIT(0) here!!!!!!!!
    # otherwise ctrl+C will not work
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

def try_load_json(path) -> dict:
    if os.path.exists(path):
        with open(path, "r") as f:
            logging.debug("Durations cache successfully accessed")
            return json.load(f)
    else:
        logging.warning("Durations cache not found")
        return {}

def save_json(path, dict_: dict) -> None:
    with open(path, "w") as f:
        json.dump(dict_, f, indent=2)
        logging.info("Video durations cached")

def get_video_duration(fpath: str, cache: dict) -> float:
    fname = os.path.basename(fpath)
    if fname in cache:
        if cache[fname] == -1: # error code on second time around
            try:
                duration = get_video_duration_ffprobe(fpath)
                cache[fname] = duration
            except:
                cache[fname] == 0 # give up on this
                logging.warning(f"{fpath} ffprobe call for duration has errored twice, and permanently stored in cache as error'ed")
        return cache[fname]
    else: 
        try:
            cache[fname] = get_video_duration_ffprobe(fpath)
        except:
            cache[fname] = -1 # error code
        return cache[fname]

def get_video_duration_ffprobe(fpath: str) -> float:
    result = subprocess.run([
        "ffprobe", "-v",
        "error", "-select_streams",
        "v:0", "-show_entries",
        "format=duration", "-of",
        "json",
        fpath
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {fpath}: {result.stderr}")
    
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])
    
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
                continue
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                logging.warning("Issue streaming frame in `generate_stream()`")
                continue
            yield (b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.06)  # about ~15fps ish
    except GeneratorExit:
        logging.info("Client disconnected from stream.")
    except:
        logging.critical(f"Exception caught in stream!", exc_info=True)

@app.route("/playlist")
def playlist():
    logging.info("Fetching all .mp4 files into list...")
    try:
        mp4_files = fetch_mp4_files(USB_VID_PATH)
    except:
        msg = "Error fetching + sorting .mp4 files for playback!"
        logging.error(msg)
        abort(404, description=msg)

    durations_cache = try_load_json(VIDEO_DURATIONS_CACHE_PATH)
    durations_cache_initial_size = len(durations_cache)
    video_data = []

    for mp4_file in mp4_files:
        dt, camera_name = timestamping.parse_filename(mp4_file)
        if not dt or not camera_name: 
            logging.warning(f"Unable to parse file {mp4_file} for timestamp and camera name")
            continue

        logging.debug(f"Generating video metadata for {mp4_file}...")
        try:
            full_path = os.path.join(USB_VID_PATH, mp4_file)
            vid_duration = get_video_duration(full_path, durations_cache)
            if vid_duration > 0:
                video_data.append({
                    "filename": mp4_file,
                    "start": timestamping.dt_strfmt(dt),
                    "duration_seconds": vid_duration,
                    "camera_name": camera_name
                })
            else:
                logging.info(f"{mp4_file} has been processed as invalid length, and will be excluded from playback")
        except:
            logging.error(f"Problem calculating / fetching {mp4_file} video duration")

    logging.debug("Saving videos durations cache...")
    try:
        save_json(VIDEO_DURATIONS_CACHE_PATH, durations_cache)
        logging.info(f"Durations cache: {durations_cache_initial_size} cache size updated to {len(durations_cache)}")
    except:
        logging.critical(f"Issue saving videos durations cache to {VIDEO_DURATIONS_CACHE_PATH}")

    if not video_data:
        logging.critical("Unable to populate any videos")
        abort(404, description="Error parsing filenames or generating video metadata")
    else:
        if len(video_data) < len(mp4_files):
            logging.warning(f"{len(mp4_files) - len(video_data)} videos in drive unable to be processed and displayed")

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
        level=logging.DEBUG,  # Decreasing verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler("app_last.log", mode="w"),
            # logging.StreamHandler()  # also prints to console
        ]
    )

    # manage Flask/Werkzeug loggers
    flask_log_handler = logging.FileHandler("flask_last.log", mode="w")
    flask_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    for name in ('flask.app', 'werkzeug'):
        flask_logger = logging.getLogger(name)
        flask_logger.setLevel(logging.DEBUG)
        flask_logger.propagate = False  # prevent double logging
        flask_logger.handlers.clear()
        flask_logger.addHandler(flask_log_handler)

    try:
        # initialize picam for stream
        picam2 = Picamera2()
        picam2.configure(picam2.create_preview_configuration(
            main={"size": (640, 480)},
            transform=Transform(hflip=True, vflip=True)
        ))
        picam2.start()
    except:
        logging.error(f"Unable to initialize camera for stream")

    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
