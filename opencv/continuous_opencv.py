import cv2

import atexit
import logging
import os
import signal
import subprocess
import sys 
import time
import concurrent.futures

sys.path.append(r"/home/brend/Documents")
import timestamping

###############################################################################
# script config
###############################################################################
# `ps aux | awk '$8 == "Z"'`
# `ps -eo pid,ppid,cmd | awk '$2 == 1 && $1 != 1'`

# run `v4l2-ctl --list-devices` in terminal
# if multiple found, run `v4l2-ctl -d /dev/video0 --all` to query which one is raw footage
CAMERA_DEVICE_NUMBER = 0 

# VID_LENGTH_SECONDS = 60 * 60
VID_LENGTH_SECONDS = 15
USB_DEVICE_NAME = "E657-3701"
USB_PATH = os.path.join("/media/brend", USB_DEVICE_NAME)
USB_VID_PATH = os.path.join(USB_PATH, "vidfiles")
LOGS_DIR_PATH = "/home/brend/Documents/opencv/logs"

WORKERS_LIMIT = 2
JOB_ERRORS_UNTIL_SYS_EXIT = 2
JOB_QUEUE_SIZE_UNTIL_SYS_EXIT = WORKERS_LIMIT * 5
# idea here is that ffmpeg processing time should be on the same order as VID_LENGTH_SECONDS
# in fact, to run continuously without futures list bloat, we should expect it to be, on average, strictly less
# we set the multiplier >1 to allow for some degree of variance in processing time
SUBPROCESS_TIMEOUT_SECONDS = VID_LENGTH_SECONDS * 2

FPS = 20; WIDTH = 640; HEIGHT = 480

LOG_FILE_LOG_LEVEL = logging.DEBUG

def cleanup():
    logging.info("Running `cleanup()`...")

atexit.register(cleanup)

def signal_handler(sig, frame):
    logging.info("Running `signal_handler`...")

signal.signal(signal.SIGINT, signal_handler)   # ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill or system shutdown
signal.signal(signal.SIGQUIT, signal_handler)  # quit signal

###############################################################################
###############################################################################

def ok_dir(dir_path) -> bool: 
    return os.path.exists(dir_path) and os.path.isdir(dir_path)

def avi_convert_to_mp4(avi_fname) -> None:
    logging.debug(f"`avi_convert_to_mp4()` PID {os.getpid()}: Processing job for {avi_fname} starting...")
    if not ok_dir(USB_VID_PATH): 
        logging.critical(f"`avi_convert_to_mp4()` PID {os.getpid()}: issue with USB_VID_PATH")
        raise RuntimeError("Issue with USB_VID_PATH")

    try:
        result = None
        timestamp, _ = timestamping.parse_filename(avi_fname, extension=".avi")
        mp4_fname = timestamping.generate_filename(for_time=timestamp, camera_name="TESTPiCam", extension=".mp4")
        mp4_fpath = os.path.join(USB_VID_PATH, mp4_fname)
        cmd = [
            "ffmpeg", # command-line tool ffmpeg for multimedia processing
            "-y", # output overwrites any files with same name
            "-i", avi_fname, # input .avi file
            "-c:v", "libx264", # use the H.264 encoder (libx264)
            "-preset", "fast", # encoding speed/quality trade-off preset
            "-crf", "23", # constant Rate Factor — controls quality (lower = better quality & bigger file); 23 is default
            "-pix_fmt", "yuv420p", # output pixel format: yuv420p generally compatible with most browsers
            mp4_fpath
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            preexec_fn=os.setsid
        )
        os.remove(avi_fname)
        if result.returncode != 0:
            logging.error(f"`avi_convert_to_mp4()` PID {os.getpid()}: subprocess error -> {result.stderr.decode()}")
            raise RuntimeError(f"Subprocess returned nonzero result")
        logging.info(f"`avi_convert_to_mp4()` PID {os.getpid()}: Processing job for {avi_fname} successfully complete, output to {mp4_fpath}")
    except:
        logging.critical(f"`avi_convert_to_mp4()` PID {os.getpid()}: Processing job for {avi_fname} FAILED.", exc_info=True)
        if result:
            os.killpg(result.pid, signal.SIGTERM)
        raise RuntimeError(f"Error thrown in converting {avi_fname}")

def record_to_temp_avi(cap: cv2.VideoCapture) -> str:
    logging.debug("`record_to_temp_avi()` called...")
    if not cap.isOpened():
        logging.critical("`record_to_temp_avi()`: not ready or not found capture device.")
        raise RuntimeError("Not ready or not found capture device.")
    
    codec = cv2.VideoWriter_fourcc(*"MJPG")
    avi_fname = timestamping.generate_filename(for_time="now", camera_name="TEMP", extension=".avi")
    writer = cv2.VideoWriter(avi_fname, codec, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        logging.critical("`record_to_temp_avi()`: VideoWriter failed to initialize")
        raise RuntimeError("VideoWriter failed to initialize")

    logging.debug(f"`record_to_temp_avi()`: recording {VID_LENGTH_SECONDS}s video now...")
    start_time = time.monotonic()
    frame_count = 0
    # the key design idea below: we always want to try and store, and later
    # convert whatever we record regardless of if we encounter an exception midway
    try:
        while True:
            ret, frame = cap.read() # captures EVERY frame even if camera write to a buffer
            if not ret:
                logging.critical(f"`record_to_temp_avi()`: failed frame after {frame_count} frames")
                raise RuntimeError(f"Failed frame after {frame_count} frames")
            writer.write(frame)
            frame_count += 1
            if time.monotonic() - start_time >= VID_LENGTH_SECONDS:
                logging.info(f"`record_to_temp_avi()`: {VID_LENGTH_SECONDS}s video written to {avi_fname}")
                break
    except:
        logging.error(
            f"`record_to_temp_avi()`: exception raise in recording loop",
            exc_info=True
        )
    finally:
        writer.release()
        logging.debug(f"`record_to_temp_avi()`: writer for {avi_fname} released.")
        return avi_fname # still return the name to try and convert and save as mp4


if __name__ == "__main__":
    assert ok_dir(USB_VID_PATH)

    # initialize logger
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

    logging.debug("Configuring cv2 camera...")
    cap = cv2.VideoCapture(CAMERA_DEVICE_NUMBER)
    if not cap.isOpened():
        logging.critical("Cannot initialize video capture device")
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    logging.info(f"Initializing ProcessPoolExecutor, main PID {os.getpid()}...")
    executor = concurrent.futures.ProcessPoolExecutor(max_workers=WORKERS_LIMIT)
    futures = []

    logging.debug("Starting continuous recording loop...")
    n_videos_complete = 0
    job_errors = 0
    temp_avi_fname = None
    try:
        while True:
            # --job management
            for f in futures:
                if f.done():
                    try:
                        f.result()
                        n_videos_complete += 1
                        job_errors = 0
                    except:
                        job_errors += 1
                        logging.error(f"Exception caught in future, {job_errors} in a row now", exc_info=True)
                        if job_errors > JOB_ERRORS_UNTIL_SYS_EXIT:
                            raise RuntimeError(f"{job_errors} job exceptions caught in a row now, aborting recording loop...")
                        
            # --continue recording and submitting processing jobs
            temp_avi_fname = record_to_temp_avi(cap)
            logging.info(f"Video #{n_videos_complete+1}, {temp_avi_fname}, submitted for conversion...")
            future = executor.submit(avi_convert_to_mp4, temp_avi_fname) # always try to convert
            futures.append(future)

            # --monitor jobload
            futures = [f for f in futures if not f.done()]
            n_pending_jobs = len(futures)
            if n_pending_jobs > WORKERS_LIMIT:
                logging.warning(f"{n_pending_jobs} jobs submitted, >limit of {WORKERS_LIMIT}")
            if n_pending_jobs > JOB_QUEUE_SIZE_UNTIL_SYS_EXIT:
                logging.critical(f"{n_pending_jobs} jobs in queue! Aborting script now...")
                raise RuntimeError(f"Job queue is dangerously bloated, with {n_pending_jobs} pending.")
            
    except KeyboardInterrupt:
        logging.info(f"Continuous recording loop: keyboard interrupt, {n_videos_complete} full {VID_LENGTH_SECONDS} have been saved to .mp4")
    except:
        logging.critical(f"Continuous recording loop: caught exception!", exc_info=True)
    finally:
        logging.debug("Freeing camera resources...")
        cap.release()
        # try to convert the final .avi file in case it was interrupted mid-way
        if temp_avi_fname and os.path.exists(temp_avi_fname):
            logging.warning(f"{temp_avi_fname} temp file still found, will attempt to process now...")
            try:
                avi_convert_to_mp4(temp_avi_fname)
            except:
                logging.error(f"Processing for {temp_avi_fname} FAILED.", exc_info=True)
    
    logging.debug("Querying any remaining workers now...")
    for f in futures:
        try:
            f.result()
        except:
            logging.error("Exception caught in future", exc_info=True)
    executor.shutdown()
