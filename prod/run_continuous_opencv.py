import cv2

import logging
import numpy as np
import os
import sys
import threading
import time

from functools import partial

from continuous import (
    continuous_record_driver,
    ffmpeg_template_processing_function,
    ok_dir,
)
from processing import is_over_mean_bright_threshold

sys.path.append(r"/home/brend/Documents")
import timestamping

# -- basic camera config
USB_CAMERA_DEVICE_NUMBER = 0
OPENCV_WIDTH = 640
OPENCV_HEIGHT = 480
# note picamera2 can adjust this automatically, opencv fps is just a joke
# because it's really up to the hardware, and unless you just dynamically
# monitor it in the code it's going to be a bit shit when you hardcode it
# into the video header via cv2.VideoWriter
OPENCV_FPS = 19.93
CAMERA_LABEL = "USB_CAMERA"


# -- opencv image processing
EVENT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
EVENT_LOGS_DIR_PATH = "/home/brend/Documents/prod/event_logs"
EVENT_LOG_FILE_LOG_LEVEL = logging.DEBUG
MEAN_BRIGHTNESS_THRESHOLD = 10
FRAMES_IN_A_ROW_FOR_BRIGHTNESS_EVENT = OPENCV_FPS * 2


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
    over_brightness_threshold_frame_count = 0
    mean_brightness_event_flag = False
    # the key design idea below: we always want to try and store, and later
    # convert whatever we record regardless of if we encounter an exception midway
    try:
        while True:
            ret, frame = cap.read()
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

            # best to put all processing into separate try-except block
            try:
                if is_over_mean_bright_threshold(frame, MEAN_BRIGHTNESS_THRESHOLD):
                    if over_brightness_threshold_frame_count == 0:
                        events_logger.debug(
                            f"{avi_fname}: Mean brightness threshold exceeded on frame {frame_count}"
                        )
                    over_brightness_threshold_frame_count += 1
                else:
                    over_brightness_threshold_frame_count = 0
                    mean_brightness_event_flag = False

                if (
                    over_brightness_threshold_frame_count
                    >= FRAMES_IN_A_ROW_FOR_BRIGHTNESS_EVENT
                    and not mean_brightness_event_flag
                ):
                    events_logger.info(
                        f"{avi_fname}: Mean brightness event on frame {frame_count}"
                    )
                    mean_brightness_event_flag = True
            except:
                logging.error(
                    f"`record_to_temp_avi()` {avi_fname}: processing for frame {frame_count} FAILED"
                )

            time_elapsed = time.monotonic() - start_time
            if time_elapsed >= secs:
                logging.info(
                    f"`record_to_temp_avi()` {avi_fname}: {time_elapsed:.1f}s video written to temp file"
                )
                break
    except:
        logging.error(
            f"`record_to_temp_avi()` {avi_fname}: exception raise in recording loop",
            exc_info=True,
        )
    finally:
        logging.debug(
            f"`record_to_temp_avi()` {avi_fname}: effective framerate was {frame_count/(time.monotonic()-start_time)}fps"
        )
        writer.release()
        logging.debug(
            f"`record_to_temp_avi()` {avi_fname}: writer for {avi_fname} released."
        )
        # todo: when main driver improved, raise error here if frame_count==0
        return avi_fname  # still return the name to try and convert and save as mp4


def cleanup_opencv(hardware: dict):
    try:
        cap = hardware["cap"]
    except:
        logging.critical("`cleanup_opencv`: Error in USB hardware objects passed")
        raise RuntimeError("Error in USB hardware objects passed")
    cap.release()


if __name__ == "__main__":
    # configure events logger
    assert ok_dir(EVENT_LOGS_DIR_PATH)
    timestamped_event_log_fname = timestamping.generate_filename(
        # API was designed for camera recording in mind, but oh well...
        camera_name=CAMERA_LABEL,
        extension=".log",
    )
    events_handler = logging.FileHandler(
        os.path.join(EVENT_LOGS_DIR_PATH, timestamped_event_log_fname), mode="w"
    )
    events_handler.setLevel(EVENT_LOG_FILE_LOG_LEVEL)
    events_handler.setFormatter(logging.Formatter(EVENT_LOG_FORMAT))

    events_logger = logging.getLogger("events_logger")
    events_logger.addHandler(events_handler)
    events_logger.setLevel(EVENT_LOG_FILE_LOG_LEVEL)
    events_logger.propagate = False

    # partial out template ffmpeg wrapper to suit hardware in this file
    avi_convert_to_mp4 = partial(
        ffmpeg_template_processing_function,
        base_cmd=[
            "ffmpeg",  # command-line tool ffmpeg for multimedia processing
            "-y",  # output overwrites any files with same name
            "-i",
            None,  # input placeholder
            "-c:v",
            "libx264",  # use the H.264 encoder (libx264)
            "-preset",
            "fast",  # encoding speed/quality trade-off preset
            "-crf",
            "23",  # constant rate factor — lower = better quality & bigger file; 23 is default
            "-pix_fmt",
            "yuv420p",  # output pixel format: yuv420p generally compatible with most browsers
            None,  # output placeholder
        ],
        in_extension=".avi",
        camera_name=CAMERA_LABEL,
        function_logging_label="avi_convert_to_mp4",
    )

    continuous_record_driver(
        camera_name=CAMERA_LABEL,
        initialise_hardware_function=initialise_opencv,
        record_function=record_to_temp_avi,
        processing_function=avi_convert_to_mp4,
        cleanup_function=cleanup_opencv,
    )
