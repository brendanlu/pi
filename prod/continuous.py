"""This is a script that implements production-capable continuous camera
recording code. It has been abstracted such that it works with both rasp Pi cam
(picamera2 (libcamera)) and USB cam (opencv).

The key bits:
 -> record video chunks continuously
 -> parallel processing via command line calls to ffmpeg
 -> graceful handling of interruptions, saves as much possible data to .mp4
 -> critical errors notify phone via pushcut app
 -> disk storage management via simple diskmanage module
 -> TODO: real-time image processing which does not limit framerate
"""

import cv2
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from libcamera import Transform

import atexit
import logging
import os
import requests
import signal
import subprocess
import sys
import time
import threading

from concurrent.futures import ProcessPoolExecutor
from dotenv import load_dotenv

sys.path.append(r"/home/brend/Documents")
import timestamping
import diskmanage

###############################################################################
# magic variables
###############################################################################

# -- pushcut
load_dotenv()
PUSHCUT_WEBHOOK_URL = os.getenv("PUSHCUT_WEBHOOK_URL")
assert PUSHCUT_WEBHOOK_URL

# -- camera hardware
USB_CAMERA_DEVICE_NUMBER = 0  # for opencv

# -- recording configuration
VID_LENGTH_SECONDS = 15
OPENCV_FPS = 20  # note picamera2 can adjust this automatically
OPENCV_WIDTH = 640
OPENCV_HEIGHT = 480
PICAM_WIDTH = 1920
PICAM_HEIGHT = 1080

# -- logging
CRITICAL_PHONE_ALERT = True
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOGS_DIR_PATH = "/home/brend/Documents/prod/logs"
LOG_FILE_LOG_LEVEL = logging.DEBUG

# -- memory disk
USB_DEVICE_NAME = "E657-3701"
USB_PATH = os.path.join("/media/brend", USB_DEVICE_NAME)
USB_VID_PATH = os.path.join(USB_PATH, "vidfiles")

# -- parallelism
WORKERS_LIMIT = 2
JOB_ERRORS_UNTIL_SYS_EXIT = 2
JOB_QUEUE_SIZE_UNTIL_SYS_EXIT = WORKERS_LIMIT * 5
# on average we expect process subprocesses to take strictly less than
# VID_LENGTH_SECONDS, but set a multiplier to allow for some variability
# around the mean
SUBPROCESS_TIMEOUT_SECONDS = VID_LENGTH_SECONDS * 2


###############################################################################
# definitions
###############################################################################
def cleanup():
    """Invoked at the end of every script"""
    logging.debug("FINAL SYSTEM CLEANUP: Running `cleanup()`...")
    logging.info("FINAL SYSTEM CLEANUP: `cleanup()` COMPLETE!")


def signal_handler(sig, frame):
    """Signal handler for any program interruptions, this gets registered for
    all processes
    """
    logging.info(
        f"`signal_handler()`: signal {sig} recieved in PID {os.getpid()}, \
            setting shutdown flag..."
    )
    shutdown_flag.set()


def ok_dir(dir_path) -> bool:
    return os.path.exists(dir_path) and os.path.isdir(dir_path)


def send_pushcut_notification(message):
    try:
        requests.post(PUSHCUT_WEBHOOK_URL, json={"text": message})
    except:
        # well too bad, sleep well...
        logging.critical("`send_pushcut_notification` FAILED")


class CriticalAlertHandler(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.CRITICAL:
            send_pushcut_notification(self.format(record))


def record_to_temp_avi(cap: cv2.VideoCapture) -> str | None:
    """Using opencv, records USB camera footage to .avi file"""
    logging.debug("`record_to_temp_avi` called...")
    if not cap.isOpened():
        logging.critical("`record_to_temp_avi`: USB capture device error!")
        return None


def record_to_temp_h264(picam2: Picamera2, h264_encoder: H264Encoder) -> str | None:
    pass


###############################################################################
# script config
###############################################################################
shutdown_flag = threading.Event()

atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill or system shutdown
signal.signal(signal.SIGQUIT, signal_handler)  # quit signal


###############################################################################
# main
###############################################################################
if __name__ == "__main__":
    # -- initialise logging
    assert ok_dir(LOGS_DIR_PATH)
    timestamped_log_fname = timestamping.generate_filename(
        # API was designed for camera recording in mind, but oh well...
        camera_name="OPENCV_CONTINUOUS",
        extension=".log",
    )
    logging.basicConfig(
        # decreasing verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL
        level=LOG_FILE_LOG_LEVEL,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(
                os.path.join(LOGS_DIR_PATH, timestamped_log_fname), mode="w"
            ),
            # logging.StreamHandler()  # also prints to console
        ],
    )
    if CRITICAL_PHONE_ALERT:
        pushcut_notifier = CriticalAlertHandler()
        pushcut_notifier.setLevel(logging.CRITICAL)
        pushcut_notifier.setFormatter(logging.Formatter(LOG_FORMAT))
        logging.getLogger().addHandler(pushcut_notifier)

    # -- initialise camera hardware
    # ---- picamera
    logging.debug("Configuring picamera2 and h264 encoder objects...")
    picam2 = Picamera2()
    video_config = picam2.create_video_configuration(
        main={"size": (PICAM_WIDTH, PICAM_HEIGHT)},
        transform=Transform(hflip=True, vflip=True),
    )
    picam2.configure(video_config)
    h264_encoder = H264Encoder()
    try:
        picam2.start()
    except:
        logging.critical("Cannot start picamera")
        shutdown_flag.set()
    # ---- opencv USB camera
    logging.debug("Configuring cv2 camera...")
    cap = cv2.VideoCapture(USB_CAMERA_DEVICE_NUMBER)
    if not cap.isOpened():
        logging.critical("Cannot initialize USB video capture device")
        shutdown_flag.set()

    # -- parallelism
    logging.info(f"Initializing ProcessPoolExecutor, main PID {os.getpid()}...")
    executor = ProcessPoolExecutor(max_workers=WORKERS_LIMIT)
    futures = []

    # -- main recording loop
    logging.info("Starting continuous recording and processing loop...")
    n_videos_recorded = 0
    n_videos_complete = 0
    processing_job_errors = 0
    last_temp_avi_fname = None
    last_temp_h264_fname = None
    try:
        cap.set(cv2.CAP_PROP_FPS, OPENCV_FPS)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, OPENCV_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, OPENCV_HEIGHT)
        while not shutdown_flag.is_set():

            # ---- query existing jobs
            for f in futures:
                if f.done():
                    try:
                        f.result()
                        n_videos_complete += 1
                    except:
                        processing_job_errors += 1
                        logging.error(
                            f"Exception caught in job, {processing_job_errors} \
                                total job errors counted",
                            exc_info=True,
                        )
                        if processing_job_errors > JOB_ERRORS_UNTIL_SYS_EXIT:
                            logging.critical(
                                f"{processing_job_errors} job exceptions caught, \
                                    aborting recording loop"
                            )
                            shutdown_flag.set()

            # ---- monitor jobload
            futures = [f for f in futures if not f.done()]
            n_pending_jobs = len(futures)
            logging.debug(f"{n_pending_jobs} jobs pending")
            if n_pending_jobs > WORKERS_LIMIT:
                logging.warning(f"Pending jobs >max workers of {WORKERS_LIMIT}")
            if n_pending_jobs > JOB_QUEUE_SIZE_UNTIL_SYS_EXIT:
                logging.critical(
                    f"Job queue is dangerously large with {n_pending_jobs} jobs \
                        in queue!"
                )
                shutdown_flag.set()

            # ---- recording and submitting processing jobs
            last_temp_avi_fname = record_to_temp_avi(cap)
            last_temp_h264_fname = record_to_temp_h264(picam2, h264_encoder)

    except:
        pass
