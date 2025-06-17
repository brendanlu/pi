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
# script config and setup
###############################################################################

# -- pushcut
load_dotenv()
PUSHCUT_WEBHOOK_URL = os.getenv("PUSHCUT_WEBHOOK_URL")
assert PUSHCUT_WEBHOOK_URL

# -- camera hardware
USB_CAMERA_DEVICE_NUMBER = 0

# -- recording configuration
VID_LENGTH_SECONDS = 15
FPS = 20; WIDTH = 640; HEIGHT = 480

# -- logging
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







def send_pushcut_notification(message):
    try:
        requests.post(PUSHCUT_WEBHOOK_URL, json={"text": message})
    except:
        logging.critical("`send_pushcut_notification` FAILED")

class CriticalAlertHandler(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.CRITICAL:
            send_pushcut_notification(self.format(record))

if __name__ == "__main__":
    assert ok_dir(LOGS_DIR_PATH)
    timestamped_log_fname = timestamping.generate_filename(
        camera_name="OPENCV_CONTINUOUS", # bit misleading parameter naming but oh well...
        extension=".log"
    )
    logging.basicConfig(
        level=LOG_FILE_LOG_LEVEL,  # Decreasing verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(LOGS_DIR_PATH, timestamped_log_fname), mode="w"),
            # logging.StreamHandler()  # also prints to console
        ]
    )
    pushcut_notifier = CriticalAlertHandler()
    pushcut_notifier.setLevel(logging.CRITICAL)
    pushcut_notifier.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logging.getLogger().addHandler(pushcut_notifier)