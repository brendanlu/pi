import cv2

import logging
import numpy as np
import os
import sys
import threading
import time

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
# we will try to automatically enforce this by throttling our capture loop
# because opencv cap.set() does not really do anything
# cheap USB camera hardware appears to record ~20fps at night and ~30fps during
# the day; attempt to throttle to 19fps which also has the added benefit of
# less frames for live-time image processing
OPENCV_FPS = 19
CAMERA_LABEL = "USB_CAMERA"


# -- opencv image processing
EVENT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
EVENT_LOGS_DIR_PATH = "/home/brend/Documents/prod/event_logs"
EVENT_LOG_FILE_LOG_LEVEL = logging.INFO
MEAN_BRIGHTNESS_THRESHOLD = 15
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


# global vars to persist between each recording call
over_brightness_threshold_frame_count = 0
mean_brightness_event_flag = False


def record_to_temp_avi(
    shutdown_flag: threading.Event, secs: int, hardware: dict
) -> tuple[str, dict]:
    """Using opencv, records USB camera footage to .avi file"""
    global over_brightness_threshold_frame_count, mean_brightness_event_flag

    # copy globals into locals to avoid slow access during tight recording
    # loop below; due to Python implementation details
    over_brightness_threshold_frame_count_local_copy = (
        over_brightness_threshold_frame_count
    )
    mean_brightness_event_flag_local_copy = mean_brightness_event_flag

    frame_count = 0
    # -- initialise hardware and file writer
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

    # -- begin recording
    logging.info(f"`record_to_temp_avi()` {avi_fname}: recording {secs}s video now...")
    # the key design idea below: we always want to try and store, and later
    # convert whatever we record regardless of if we encounter an exception midway
    try:
        time_per_frame = 1.0 / OPENCV_FPS
        recording_start_time = time.monotonic()
        while True:
            frame_start_time = time.monotonic()

            # opencv boilerplate
            ret, frame = cap.read()
            if not ret or shutdown_flag.is_set():
                if shutdown_flag.is_set():
                    logging.warning(
                        f"`record_to_temp_avi()` {avi_fname}: interrupted after {frame_count} frames"
                    )
                    break
                else:
                    logging.error(
                        f"`record_to_temp_avi()` {avi_fname}: failed frame after {frame_count} frames"
                    )
                    break
            writer.write(frame)
            frame_count += 1

            # put all processing into try block to avoid crashing on processing
            # code
            try:
                if is_over_mean_bright_threshold(frame, MEAN_BRIGHTNESS_THRESHOLD):
                    if over_brightness_threshold_frame_count_local_copy == 0:
                        events_logger.debug(
                            f"{avi_fname}: Mean brightness threshold exceeded on frame {frame_count}"
                        )
                    over_brightness_threshold_frame_count_local_copy += 1
                else:
                    over_brightness_threshold_frame_count_local_copy = 0
                    mean_brightness_event_flag_local_copy = False

                if (
                    over_brightness_threshold_frame_count_local_copy
                    >= FRAMES_IN_A_ROW_FOR_BRIGHTNESS_EVENT
                    and not mean_brightness_event_flag_local_copy
                ):
                    events_logger.info(
                        f"{avi_fname}: Mean brightness event on frame {frame_count}"
                    )
                    mean_brightness_event_flag_local_copy = True
            except:
                logging.error(
                    f"`record_to_temp_avi()` {avi_fname}: processing for frame {frame_count} FAILED"
                )

            # check if video duration elapsed
            time_elapsed = time.monotonic() - recording_start_time
            if time_elapsed >= secs:
                logging.info(
                    f"`record_to_temp_avi()` {avi_fname}: full {time_elapsed:.1f}s video written to temp file"
                )
                break

            # sleep to throttle to fps
            frame_time_elapsed = time.monotonic() - frame_start_time
            # if frame_time_elapsed > time_per_frame:
            #     logging.warning(
            #         f"`record_to_temp_avi()` {avi_fname}: {frame_time_elapsed:.4f}s long frame time on frame {frame_count}"
            #     )
            time.sleep(max(0, time_per_frame - frame_time_elapsed))

    except:
        logging.error(
            f"`record_to_temp_avi()` {avi_fname}: exception raise in recording loop",
            exc_info=True,
        )
    finally:
        # most cheap USB camera's won't give a shit what fps you pass into it
        # so we get a mean here to pass into ffmpeg
        # nb. this will make the video patchy as the actual recording fps
        # was dynamic, but oh well...
        effective_mean_fps = frame_count / (time.monotonic() - recording_start_time)
        logging.debug(
            f"`record_to_temp_avi()` {avi_fname}: effective framerate was {effective_mean_fps}fps"
        )
        writer.release()
        logging.debug(
            f"`record_to_temp_avi()` {avi_fname}: writer for {avi_fname} released."
        )
        # TODO: when main driver improved, raise error here if frame_count==0
        # still return the name to try and convert and save as mp4

        # make sure to save local values back into globals to persist into
        # next function call
        over_brightness_threshold_frame_count = (
            over_brightness_threshold_frame_count_local_copy
        )
        mean_brightness_event_flag = mean_brightness_event_flag_local_copy

        return avi_fname, dict(mean_fps=effective_mean_fps)


def avi_convert_to_mp4(
    in_fname: str, out_dirpath: str, timeout_secs: int, dynamic_configs: dict
):
    base_cmd = [
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
    ]

    # put dynamic configs in try block
    try:
        if "mean_fps" in dynamic_configs:
            iflag_index = base_cmd.index("-i")
            mean_fps: float = dynamic_configs["mean_fps"]
            base_cmd.insert(iflag_index, str(mean_fps))
            base_cmd.insert(iflag_index, "-r")
            logging.debug(
                f"`avi_convert_to_mp4()` {in_fname}: attempt to process with {mean_fps}fps"
            )
        else:
            logging.warning(
                f"`avi_convert_to_mp4()` {in_fname}: no dynamic fps found for processing"
            )
    except:
        logging.error(
            f"`avi_convert_to_mp4()` {in_fname}: exception occured in applying dynamic config"
        )

    return ffmpeg_template_processing_function(
        in_fname,
        out_dirpath,
        timeout_secs,
        base_cmd=base_cmd,
        in_extension=".avi",
        camera_name=CAMERA_LABEL,
        function_logging_label="avi_convert_to_mp4",
    )


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

    continuous_record_driver(
        camera_name=CAMERA_LABEL,
        initialise_hardware_function=initialise_opencv,
        record_function=record_to_temp_avi,
        processing_function=avi_convert_to_mp4,
        cleanup_function=cleanup_opencv,
    )
