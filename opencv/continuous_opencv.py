import cv2

import atexit
import logging
import os
import signal
import subprocess
import sys 
import time
import threading
import concurrent.futures

sys.path.append(r"/home/brend/Documents")
import timestamping

# TODO: diskmanage, pushcut

###############################################################################
# script config
###############################################################################
# `ps aux | awk '$8 == "Z"'`
# `ps -eo pid,ppid,cmd | awk '$2 == 1 && $1 != 1'`
# `pkill -f continuous_opencv.py` to kill if you can't gracefully
# `ps aux | grep python` to check after

# run `v4l2-ctl --list-devices` in terminal
# if multiple found, run `v4l2-ctl -d /dev/video0 --all` to query which one is raw footage
USB_CAMERA_DEVICE_NUMBER = 0 

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
    logging.debug("FINAL SYSTEM CLEANUP: Running `cleanup()`...")
    logging.info("FINAL SYSTEM CLEANUP: `cleanup()` COMPLETE!")

atexit.register(cleanup)

shutdown_flag = threading.Event()
def signal_handler(sig, frame):
    logging.info(f"`signal_handler()`: signal {sig} recieved in PID {os.getpid()}, setting shutdown flag...")
    shutdown_flag.set()

signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
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

    proc = None
    try:
        timestamp, _ = timestamping.parse_filename(avi_fname, extension=".avi")
        mp4_fname = timestamping.generate_filename(for_time=timestamp, camera_name="TESTUSBCam", extension=".mp4")
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
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )
        _, stderr = proc.communicate(timeout=SUBPROCESS_TIMEOUT_SECONDS)
        os.remove(avi_fname)
        if proc.returncode != 0:
            logging.error(f"`avi_convert_to_mp4()` PID {os.getpid()}: subprocess error -> {stderr.decode()}")
            raise RuntimeError(f"Subprocess returned nonzero result")
        logging.info(f"`avi_convert_to_mp4()` PID {os.getpid()}: Processing job for {avi_fname} successfully complete, output to {mp4_fpath}")
    except:
        logging.critical(f"`avi_convert_to_mp4()` PID {os.getpid()}: Processing job for {avi_fname} FAILED.", exc_info=True)
        if proc:
            os.killpg(proc.pid, signal.SIGTERM)
        raise RuntimeError(f"Error thrown in converting {avi_fname}")

def record_to_temp_avi(cap: cv2.VideoCapture) -> str:
    logging.debug("`record_to_temp_avi()` called...")
    if not cap.isOpened():
        logging.critical("`record_to_temp_avi()`: not ready or not found capture device.")
        raise RuntimeError("Not ready or not found capture device.")
    
    codec = cv2.VideoWriter_fourcc(*"MJPG") # type: ignore
    avi_fname = timestamping.generate_filename(for_time="now", camera_name="TEMP", extension=".avi")
    writer = cv2.VideoWriter(avi_fname, codec, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        logging.critical(f"`record_to_temp_avi()` {avi_fname}: VideoWriter failed to initialize")
        raise RuntimeError("VideoWriter failed to initialize")

    logging.info(f"`record_to_temp_avi()` {avi_fname}: recording {VID_LENGTH_SECONDS}s video now...")
    start_time = time.monotonic()
    frame_count = 0
    # the key design idea below: we always want to try and store, and later
    # convert whatever we record regardless of if we encounter an exception midway
    try:
        while True:
            ret, frame = cap.read() # captures EVERY frame even if camera write to a buffer
            if not ret:
                if shutdown_flag.is_set():
                    logging.warning(f"`record_to_temp_avi()` {avi_fname}: interrupted after {frame_count} frames")
                    break
                else:
                    logging.error(f"`record_to_temp_avi()` {avi_fname}: failed frame after {frame_count} frames")
                    raise RuntimeError(f"Failed frame after {frame_count} frames")
            writer.write(frame)
            frame_count += 1
            if time.monotonic() - start_time >= VID_LENGTH_SECONDS:
                logging.info(f"`record_to_temp_avi()` {avi_fname}: {VID_LENGTH_SECONDS}s video written to temp file")
                break
    except:
        logging.error(
            f"`record_to_temp_avi()` {avi_fname}: exception raise in recording loop",
            exc_info=True
        )
    finally:
        writer.release()
        logging.debug(f"`record_to_temp_avi()` {avi_fname}: writer for {avi_fname} released.")
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
    cap = cv2.VideoCapture(USB_CAMERA_DEVICE_NUMBER)
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
    n_videos_recorded = 0
    n_videos_complete = 0
    job_errors = 0
    temp_avi_fname = None
    try:
        while not shutdown_flag.is_set():
            # --query jobs
            for f in futures:
                if f.done():
                    try:
                        f.result()
                        n_videos_complete += 1
                        logging.debug(f"{n_videos_complete} jobs complete!")
                    except:
                        job_errors += 1
                        logging.error(f"Exception caught in job, {job_errors} total job errors now", exc_info=True)
                        if job_errors > JOB_ERRORS_UNTIL_SYS_EXIT:
                            raise RuntimeError(f"{job_errors} job exceptions caught, aborting recording loop...")
            
            # --monitor jobload
            futures = [f for f in futures if not f.done()]
            n_pending_jobs = len(futures)
            logging.debug(f"{n_pending_jobs} jobs pending")
            if n_pending_jobs > WORKERS_LIMIT:
                logging.warning(f"{n_pending_jobs} jobs pending >limit of {WORKERS_LIMIT}")
            if n_pending_jobs > JOB_QUEUE_SIZE_UNTIL_SYS_EXIT:
                logging.critical(f"{n_pending_jobs} jobs in queue! Aborting script now...")
                raise RuntimeError(f"Job queue is dangerously bloated, with {n_pending_jobs} pending.")
                        
            # --continue recording and submitting processing jobs
            temp_avi_fname = record_to_temp_avi(cap)
            n_videos_recorded += 1
            logging.info(f"Video #{n_videos_recorded}, {temp_avi_fname}, submitted for conversion...")
            future = executor.submit(avi_convert_to_mp4, temp_avi_fname) # always try to convert
            futures.append(future)
            
    except:
        logging.critical(f"Continuous recording loop: caught exception!", exc_info=True)
    finally:
        logging.debug("Freeing camera resources...")
        cap.release()
    
    logging.debug("Querying any remaining workers now...")
    for f in futures:
        try:
            f.result()
            n_videos_complete += 1
            logging.debug(f"{n_videos_complete} jobs complete!")
        except:
            logging.error("Exception caught in job", exc_info=True)
    executor.shutdown(wait=True, cancel_futures=True)

    # try to convert the final .avi file in case it was interrupted mid-way but
    # conversion job was not submitted
    if temp_avi_fname and os.path.exists(temp_avi_fname) and n_videos_recorded < n_videos_complete:
        logging.warning(f"{temp_avi_fname} temp file still found, will attempt to process now...")
        try:
            avi_convert_to_mp4(temp_avi_fname)
            n_videos_complete += 1
            logging.debug(f"{n_videos_complete} jobs complete!")
        except:
            logging.error(f"Processing for {temp_avi_fname} FAILED.", exc_info=True)

    logging.info(f"Continuous recording loop: {n_videos_complete} videos saved to .mp4")
    logging.info("Main script shutdown complete")
