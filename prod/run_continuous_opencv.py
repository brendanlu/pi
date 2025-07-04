import cv2
import logging
import os
import signal
import subprocess
import sys
import threading
import time

from continuous import continuous_record_driver, ok_dir

sys.path.append(r"/home/brend/Documents")
import timestamping

USB_CAMERA_DEVICE_NUMBER = 0
OPENCV_WIDTH = 640
OPENCV_HEIGHT = 480
OPENCV_FPS = 20  # note picamera2 can adjust this automatically


def initialise_opencv(shutdown_flag: threading.Event) -> dict:
    logging.debug("Configuring cv2 camera...")
    cap = cv2.VideoCapture(USB_CAMERA_DEVICE_NUMBER)
    if not cap.isOpened():
        logging.critical("Cannot initialize USB video capture device")
        shutdown_flag.set()
    try:
        cap.set(cv2.CAP_PROP_FPS, OPENCV_FPS)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, OPENCV_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, OPENCV_HEIGHT)
    except:
        logging.critical("Could not configure opencv capture settings")
        shutdown_flag.set()
    return dict(cap=cap)


def record_to_temp_avi(
    shutdown_flag: threading.Event, secs: int, hardware: dict
) -> str:
    """Using opencv, records USB camera footage to .avi file"""
    try:
        cap = hardware["cap"]
    except:
        logging.critical("`record_to_temp_avi`: Error in USB hardware objects passed")
        raise RuntimeError("Error in USB hardware objects passed")
    logging.debug("`record_to_temp_avi` called...")
    if not cap.isOpened():
        logging.critical("`record_to_temp_avi`: USB capture device error")
        raise RuntimeError("USB capture device error")
    codec = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore
    avi_fname = timestamping.generate_filename(
        for_time="now", camera_name="TEMP", extension=".avi"
    )
    writer = cv2.VideoWriter(
        avi_fname, codec, OPENCV_FPS, (OPENCV_WIDTH, OPENCV_HEIGHT)
    )
    if not writer.isOpened():
        logging.critical(
            f"`record_to_temp_avi()` {avi_fname}: VideoWriter failed to initialize"
        )
        raise RuntimeError("VideoWriter failed to initialize")

    logging.info(f"`record_to_temp_avi()` {avi_fname}: recording {secs}s video now...")
    start_time = time.monotonic()
    frame_count = 0
    # the key design idea below: we always want to try and store, and later
    # convert whatever we record regardless of if we encounter an exception midway
    try:
        while True:
            ret, frame = (
                cap.read()
            )  # captures EVERY frame even if camera write to a buffer
            if not ret:
                if shutdown_flag.is_set():
                    logging.warning(
                        f"`record_to_temp_avi()` {avi_fname}: interrupted after {frame_count} frames"
                    )
                    break
                else:
                    logging.error(
                        f"`record_to_temp_avi()` {avi_fname}: failed frame after {frame_count} frames"
                    )
                    raise RuntimeError(f"Failed frame after {frame_count} frames")
            writer.write(frame)
            frame_count += 1
            if time.monotonic() - start_time >= secs:
                logging.info(
                    f"`record_to_temp_avi()` {avi_fname}: {secs}s video written to temp file"
                )
                break
    except:
        logging.error(
            f"`record_to_temp_avi()` {avi_fname}: exception raise in recording loop",
            exc_info=True,
        )
    finally:
        writer.release()
        logging.debug(
            f"`record_to_temp_avi()` {avi_fname}: writer for {avi_fname} released."
        )
        return avi_fname  # still return the name to try and convert and save as mp4


def avi_convert_to_mp4(avi_fname: str, out_dirpath: str, timeout_secs: int) -> None:
    logging.debug(
        f"`avi_convert_to_mp4()` PID {os.getpid()}: Processing job for {avi_fname} starting..."
    )
    if not ok_dir(out_dirpath):
        logging.critical(
            f"`avi_convert_to_mp4()` PID {os.getpid()}: issue with USB_VID_PATH"
        )
        raise RuntimeError("Issue with USB_VID_PATH")

    proc = None
    try:
        timestamp, _ = timestamping.parse_filename(avi_fname, extension=".avi")
        mp4_fname = timestamping.generate_filename(
            for_time=timestamp, camera_name="TESTUSBCam", extension=".mp4"
        )
        mp4_fpath = os.path.join(out_dirpath, mp4_fname)
        cmd = [
            "ffmpeg",  # command-line tool ffmpeg for multimedia processing
            "-y",  # output overwrites any files with same name
            "-i",
            avi_fname,  # input .avi file
            "-c:v",
            "libx264",  # use the H.264 encoder (libx264)
            "-preset",
            "fast",  # encoding speed/quality trade-off preset
            "-crf",
            "23",  # constant rate factor — lower = better quality & bigger file; 23 is default
            "-pix_fmt",
            "yuv420p",  # output pixel format: yuv420p generally compatible with most browsers
            mp4_fpath,
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, preexec_fn=os.setsid
        )
        _, stderr = proc.communicate(timeout=timeout_secs)
        os.remove(avi_fname)
        if proc.returncode != 0:
            logging.error(
                f"`avi_convert_to_mp4()` PID {os.getpid()}: subprocess error -> {stderr.decode()}"
            )
            raise RuntimeError(f"Subprocess returned nonzero result")
        logging.info(
            f"`avi_convert_to_mp4()` PID {os.getpid()}: Processing job for {avi_fname} successfully complete, output to {mp4_fpath}"
        )
    except:
        logging.critical(
            f"`avi_convert_to_mp4()` PID {os.getpid()}: Processing job for {avi_fname} FAILED.",
            exc_info=True,
        )
        if proc:
            os.killpg(proc.pid, signal.SIGTERM)
        raise RuntimeError(f"Error thrown in converting {avi_fname}")


def cleanup_opencv(hardware: dict):
    try:
        cap = hardware["cap"]
    except:
        logging.critical("`cleanup_opencv`: Error in USB hardware objects passed")
        raise RuntimeError("Error in USB hardware objects passed")
    cap.release()


if __name__ == "__main__":
    continuous_record_driver(
        camera_name="USB_CAMERA",
        initialise_hardware_function=initialise_opencv,
        record_function=record_to_temp_avi,
        processing_function=avi_convert_to_mp4,
        cleanup_function=cleanup_opencv,
    )
