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

WORKERS_LIMIT = 2
JOB_ERRORS_UNTIL_SYS_EXIT = 3

# VID_LENGTH_SECONDS = 60 * 60
VID_LENGTH_SECONDS = 15
USB_DEVICE_NAME = "E657-3701"
USB_PATH = os.path.join("/media/brend", USB_DEVICE_NAME)
USB_VID_PATH = os.path.join(USB_PATH, "vidfiles")
LOGS_DIR_PATH = "/home/brend/Documents/opencv/logs"

FPS = 20; WIDTH = 640; HEIGHT = 480

def cleanup():
    logging.info("Running `cleanup()`...")

atexit.register(cleanup)

def signal_handler(sig, frame):
    sys.exit(0) # this just triggers atexit ^^^

signal.signal(signal.SIGINT, signal_handler)   # ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill or system shutdown
signal.signal(signal.SIGQUIT, signal_handler)  # quit signal

def ok_dir(dir_path) -> bool: 
    assert os.path.exists(dir_path) and os.path.isdir(dir_path)

def avi_convert_to_mp4(avi_fname) -> None:
    logging.debug(f"`avi_convert_to_mp4()`: Processing job for {avi_fname} recieved and starting now...")
    if not ok_dir(USB_VID_PATH): 
        logging.critical("`avi_convert_to_mp4()`: issue with USB_VID_PATH")

    try:
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
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL)
        os.remove(avi_fname)
        assert result.returncode == 0
        logging.info(f"`avi_convert_to_mp4()`: Processing job for {avi_fname} successfully complete, output to {mp4_fpath}")
    except:
        logging.critical(f"`avi_convert_to_mp4()`: Processing job for {avi_fname} FAILED.", exc_info=True)
        raise RuntimeError(f"Error thrown in converting {avi_fname}")


def record_to_temp_avi(cap: cv2.VideoCapture) -> str:
    logging.debug("`record_to_temp_avi()` called...")
    if not cap.isOpened():
        logging.critical("`record_to_temp_avi()`: not ready or not found capture device.")
        raise RuntimeError("Not ready or not found capture device.")
    
    codec = cv2.VideoWriter_fourcc(*"MJPG")
    avi_fname = timestamping.generate_filename(for_time="now", camera_name="TEMP", extension=".avi")
    writer = cv2.VideoWriter(avi_fname, codec, FPS, (WIDTH, HEIGHT))
    # deliberately avoiding writer.isOpened() check for now

    logging.debug(f"`record_to_temp_avi()`: recording {VID_LENGTH_SECONDS}s video now...")
    start_time = time.monotonic()
    frame_count = 0
    # the key design idea below: we always want to try and store, and later
    # convert whatever we record regardless of if we encounter an exception midway
    try:
        while True:
            ret, frame = cap.read()
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
        level=logging.DEBUG,  # Decreasing verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(LOGS_DIR_PATH, timestamped_log_fname), mode="w"),
            logging.StreamHandler()  # also prints to console
        ]
    )

    logging.debug("Configuring cv2 camera...")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        logging.critical("Cannot initialize video capture device")
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    logging.debug("Initializing ThreadPoolExecutor...")
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS_LIMIT)
    futures = []

    logging.debug("Starting continuous recording loop...")
    videos_complete = 0
    last_pending_jobs = 0
    job_errors = 0
    try:
        while True:
            # --job management
            for f in futures:
                if f.done():
                    try:
                        f.result()
                        job_errors = 0
                    except:
                        job_errors += 1
                        logging.error(f"Exception caught in future, {job_errors} in a row now", exc_info=True)
                        if job_errors > JOB_ERRORS_UNTIL_SYS_EXIT:
                            raise RuntimeError(f"{job_errors} job errors in a row now, aborting recording loop...")
                        
            # --continue recording and submitting processing jobs
            temp_avi_fname = record_to_temp_avi(cap)
            logging.info(f"Video #{videos_complete+1}, {temp_avi_fname}, submitted for conversion...")
            future = executor.submit(avi_convert_to_mp4, temp_avi_fname) # always try to convert
            futures.append(future)

            # -- monitor jobload
            futures = [f for f in futures if not f.done()]
            pending_jobs = len(futures)
            if pending_jobs > WORKERS_LIMIT:
                logging.warning(f"{pending_jobs} jobs submitted, >limit of {WORKERS_LIMIT}")
            if pending_jobs < last_pending_jobs:
                videos_complete += last_pending_jobs - pending_jobs
            last_pending_jobs = pending_jobs
    except KeyboardInterrupt:
        logging.info(f"Continuous recording loop keyboard interrupted after {videos_complete} .mp4 successfully saved")
    except:
        logging.critical(f"Exception caught in continuous recording loop", exc_info=True)
    finally:
        logging.debug("Freeing camera resources...")
        cap.release()
    
    logging.debug("Querying any remaining workers now...")
    for f in futures:
        try:
            f.result()
        except:
            logging.error("Exception caught in future", exc_info=True)
    executor.shutdown()
