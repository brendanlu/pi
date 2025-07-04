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

Import the main function defined in this file, with a few hardware specific
functions and configurations...and off you go...
"""

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
from typing import Callable, cast

sys.path.append(r"/home/brend/Documents")
import timestamping
import diskmanage

###############################################################################
# magic variables
###############################################################################

# -- pushcut
load_dotenv()
PUSHCUT_WEBHOOK_URL = cast(str, os.getenv("PUSHCUT_WEBHOOK_URL"))
assert PUSHCUT_WEBHOOK_URL

# -- recording configuration
VID_LENGTH_SECONDS = 15

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


def ok_dir(dir_path: str) -> bool:
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


###############################################################################
# abtract driver function
###############################################################################
def continuous_record_driver(
    *,
    camera_name: str,
    initialise_hardware_function: Callable[[threading.Event], dict],
    record_function: Callable[[threading.Event, int, dict], str],
    processing_function: Callable[[str, str, int], None],
    cleanup_function: Callable[[dict], None],
):
    """Details of functional abstraction (unless stated all functions receive
    the threading.Event() `shutdown_flag` as their first arg):
        - `initialise_hardware_function`
            - <NIL input>
            - <output> a dictionary of hardware objects
        - `record_function`
            - <input> recording length in seconds
            - <input> a dictionary of hardware objects
            - <output> text fname of temporary recording file
        - `processing_function` : called via a ProcessPoolExecutor
            - <DOES NOT RECIEVE THREADING.EVENT OBJ input>
            - <input> text fname of temporary recording file
            - <input> final output video directory path
            - <input> timeout seconds
            - <NIL output>
        - `cleanup_function` : called during cleanup
            - <input> a dictionary of hardware objects
            - <NIL output>
    """
    # -- configure shutdown behaviour
    shutdown_flag = threading.Event()

    def signal_handler(sig, frame):
        """Signal handler for any program interruptions, this gets registered
        for all processes
        """
        logging.info(
            f"`signal_handler()`: signal {sig} recieved in PID {os.getpid()}, setting shutdown flag..."
        )
        shutdown_flag.set()

    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # kill or system shutdown
    signal.signal(signal.SIGQUIT, signal_handler)  # quit signal

    # -- initialise logging
    assert ok_dir(LOGS_DIR_PATH)
    timestamped_log_fname = timestamping.generate_filename(
        # API was designed for camera recording in mind, but oh well...
        camera_name=camera_name,
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

    # -- initialise camera hardware into a dict of hardware objects
    hardware_dict = initialise_hardware_function(shutdown_flag)

    # -- parallelism
    logging.info(f"Initializing ProcessPoolExecutor, main PID {os.getpid()}...")
    executor = ProcessPoolExecutor(max_workers=WORKERS_LIMIT)
    futures = []

    # -- main recording loop
    logging.info("Starting continuous recording and processing loop...")
    n_videos_recorded = 0
    n_videos_complete = 0
    processing_job_errors = 0
    last_temp_fname = None
    try:
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
                            f"Exception caught in job, {processing_job_errors} total job errors counted",
                            exc_info=True,
                        )
                        if processing_job_errors > JOB_ERRORS_UNTIL_SYS_EXIT:
                            logging.critical(
                                f"{processing_job_errors} job exceptions caught, aborting recording loop"
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
                    f"Job queue is dangerously large with {n_pending_jobs} jobs in queue!"
                )
                shutdown_flag.set()

            # ---- recording and submitting processing jobs
            last_temp_fname = record_function(
                shutdown_flag, VID_LENGTH_SECONDS, hardware_dict
            )
            n_videos_recorded += 1
            logging.info(
                f"Video #{n_videos_recorded}, {last_temp_fname}, submitted for conversion..."
            )
            future = executor.submit(
                processing_function,
                last_temp_fname,
                USB_VID_PATH,
                SUBPROCESS_TIMEOUT_SECONDS,
            )
            futures.append(future)

    except:
        logging.critical(f"Continuous recording loop: caught exception!", exc_info=True)
    finally:
        logging.debug("Freeing hardware resources...")
        cleanup_function(hardware_dict)

    logging.debug("Querying any remaining processing workers now...")
    for f in futures:
        try:
            f.result()
            n_videos_complete += 1
            logging.debug(f"{n_videos_complete} jobs complete!")
        except:
            logging.error("Exception caught in job", exc_info=True)
    executor.shutdown(wait=True, cancel_futures=True)

    # try to convert any half recorded file in case it was interrupted mid-way
    # but conversion job was not submitted
    if (
        last_temp_fname
        and os.path.exists(last_temp_fname)
        and n_videos_recorded < n_videos_complete
    ):
        logging.warning(
            f"{last_temp_fname} temp file still found, will attempt to process now..."
        )
        try:
            processing_function(
                last_temp_fname, USB_VID_PATH, SUBPROCESS_TIMEOUT_SECONDS
            )
            n_videos_complete += 1
            logging.debug(f"{n_videos_complete} jobs complete!")
        except:
            logging.error(f"Processing for {last_temp_fname} FAILED.", exc_info=True)

    logging.info(f"Continuous recording loop: {n_videos_complete} videos saved to .mp4")
    logging.info("Driver script shutdown complete")
