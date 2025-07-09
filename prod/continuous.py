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
VID_LENGTH_SECONDS = 5 * 60

# -- logging
CRITICAL_PHONE_ALERT = True
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOGS_DIR_PATH = "/home/brend/Documents/prod/logs"
LOG_FILE_LOG_LEVEL = logging.DEBUG

# -- memory disk
# USB_DEVICE_NAME = "E657-3701"
USB_DEVICE_NAME = "DYNABOOK"
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


def ffmpeg_template_processing_function(
    in_fname: str,
    out_dirpath: str,
    timeout_secs: int,
    *,
    base_cmd: list[str | None],
    in_extension: str,
    camera_name: str,
    function_logging_label: str,
) -> None:
    """Templace for a function that matches the signature required by the
    driver below, once the keyword arguments have been frozen to a
    configuration

    Performs conversion of a video intermediate via ffmpeg to a mp4 file
    compatible with web app streaming

    It expects the base_cmd to leave exactly two None placeholders, the first
    will be replaced by the input fpath, and the second by the output fpath

    e.g.
    base_cmd = [
        "ffmpeg",  # command-line tool ffmpeg for multimedia processing
        "-y",  # output overwrites any files with same name
        "-i", None,  # input placeholder
        "-c:v", "libx264",  # use the H.264 encoder (libx264)
        "-preset", "fast",  # encoding speed/quality trade-off preset
        "-crf", "23",  # constant rate factor — lower = better quality & bigger file; 23 is default
        "-pix_fmt", "yuv420p",  # output pixel format: yuv420p generally compatible with most browsers
        None,  # output placeholder
    ]
    """

    assert (
        base_cmd.count(None) == 2
    ), "base_cmd must contain exactly two None placeholders"
    assert (
        base_cmd[base_cmd.index(None) - 1] == "-i"
    ), "base_cmd first None must follow '-i'"
    assert base_cmd[-1] is None, "base_cmd second None must be at the end"

    logging.debug(
        f"`{function_logging_label}()` PID {os.getpid()}: Processing job for {in_fname} starting..."
    )
    if not ok_dir(out_dirpath):
        logging.critical(
            f"`{function_logging_label}()` PID {os.getpid()}: issue with video output directory"
        )
        raise RuntimeError("Issue with video output directory")

    proc = None
    try:
        timestamp, _ = timestamping.parse_filename(in_fname, extension=in_extension)
        out_fname = timestamping.generate_filename(
            for_time=timestamp, camera_name=camera_name, extension=".mp4"
        )
        out_fpath = os.path.join(out_dirpath, out_fname)
        cmd = base_cmd.copy()
        cmd[cmd.index(None)] = in_fname
        cmd[cmd.index(None)] = out_fpath
        # appease pylance, due to assertions at the start and the processing
        # lines above we can be sure of this
        cmd = cast(list[str], cmd)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        _, stderr = proc.communicate(timeout=timeout_secs)
        if proc.returncode != 0:
            logging.error(
                f"`{function_logging_label}()` PID {os.getpid()}: subprocess error -> {stderr.decode()}"
            )
            raise RuntimeError(f"Subprocess error")
        else:
            os.remove(in_fname)
        logging.info(
            f"`{function_logging_label}()` PID {os.getpid()}: Process job for {in_fname} successfully complete, output to {out_fpath}"
        )
    except:
        logging.critical(
            f"`{function_logging_label}()` PID {os.getpid()}: Processing job for {in_fname} FAILED.",
            exc_info=True,
        )
        if proc:
            os.killpg(proc.pid, signal.SIGTERM)
        raise RuntimeError(f"Processing job for {in_fname} FAILED.")


###############################################################################
# abtract driver function
###############################################################################
def continuous_record_driver(
    *,
    camera_name: str,
    initialise_hardware_function: Callable[[threading.Event], dict],
    record_function: Callable[[threading.Event, int, dict], tuple[str, dict]],
    processing_function: Callable[[str, str, int, dict], None],
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
            - <output> a dictionary of dynamic processing configs for the video
        - `processing_function` : called via a ProcessPoolExecutor
            - <DOES NOT RECIEVE THREADING.EVENT OBJ input>
            - <input> text fname of temporary recording file
            - <input> final output video directory path
            - <input> timeout seconds
            - <input> a dictionary of dynamic processing configs for the video
            - <NIL output>
        - `cleanup_function` : called during cleanup
            - <DOES NOT RECIEVE THREADING.EVENT OBJ input>
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

    def cleanup():
        """Invoked at the end of every script"""
        logging.debug("FINAL SYSTEM CLEANUP: Running `cleanup()`...")
        logging.info("FINAL SYSTEM CLEANUP: `cleanup()` COMPLETE!")

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
    while not shutdown_flag.is_set():
        try:
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
            last_temp_fname, last_dynamic_processing_configs = record_function(
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
                last_dynamic_processing_configs,
            )
            futures.append(future)

        except:
            logging.critical(
                f"Continuous recording loop: caught exception!", exc_info=True
            )

    logging.info("Freeing hardware resources...")
    cleanup_function(hardware_dict)

    logging.info("Querying any remaining processing workers now...")
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
                last_temp_fname,
                USB_VID_PATH,
                SUBPROCESS_TIMEOUT_SECONDS,
                last_dynamic_processing_configs,
            )
            n_videos_complete += 1
            logging.debug(f"{n_videos_complete} jobs complete!")
        except:
            logging.error(f"Processing for {last_temp_fname} FAILED.", exc_info=True)

    logging.info(f"Continuous recording loop: {n_videos_complete} videos saved to .mp4")
    logging.info("Driver script shutdown complete")
