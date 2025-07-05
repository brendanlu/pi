from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from libcamera import Transform  # type: ignore

import logging
import sys
import threading
import time

from functools import partial

from continuous import continuous_record_driver, ffmpeg_template_processing_function

sys.path.append(r"/home/brend/Documents")
import timestamping

PICAM_WIDTH = 1920
PICAM_HEIGHT = 1080
CAMERA_LABEL = "PI_CAMERA"


def initialise_picamera2(shutdown_flag: threading.Event):
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
    return dict(picam2=picam2, h264_encoder=h264_encoder)


def record_to_temp_h264(
    shutdown_flag: threading.Event, secs: int, hardware: dict
) -> str:
    """Using picamera2, records picamera footage to raw .h264 file"""
    try:
        picam2 = hardware["picam2"]
        h264_encoder = hardware["h264_encoder"]
    except:
        logging.critical(
            f"`record_to_temp_h264`: Error in picamera2 hardware objects passed"
        )
        raise RuntimeError("Error in picamera2 hardware objects passed")
    logging.debug("`record_to_temp_h264` called...")
    h264_fname = timestamping.generate_filename(
        for_time="now", camera_name="TEMP", extension=".h264"
    )
    logging.info(f"`record_to_temp_h264` {h264_fname}: recording {secs}s video now...")
    start_time = time.monotonic()
    try:
        picam2.start_recording(h264_encoder, FileOutput(h264_fname))
        while True:
            time_elapsed = time.monotonic() - start_time
            if time_elapsed >= secs:
                logging.info(
                    f"`record_to_temp_h264` {h264_fname}: {time_elapsed:.1f}s video written to temp file"
                )
                break
            elif shutdown_flag.is_set():
                logging.warning(
                    f"`record_to_temp_avi()` {h264_fname}: interrupted after {time_elapsed:.1f}s"
                )
                break
            time.sleep(1)
    except:
        logging.error(
            f"`record_to_temp_h264()` {h264_fname}: exception raise in recording call",
            exc_info=True,
        )
    finally:
        picam2.stop_recording()
        return h264_fname


def cleanup_picamera2(hardware: dict):
    try:
        picam2 = hardware["picam2"]
    except:
        logging.critical(
            "`cleanup_picamera2`: Error in picamera hardware objects passed"
        )
        raise RuntimeError("Error in picamera hardware objects passed")
    picam2.close()


if __name__ == "__main__":
    h264_convert_to_mp4 = partial(
        ffmpeg_template_processing_function,
        base_cmd=[
            "ffmpeg",  # command-line tool ffmpeg for multimedia processing
            "-y",  # output overwrites any files with same name
            "-framerate",
            "30",  # picamera2 records at 30fps, ensures output matches
            "-i",
            None,  # input placeholder
            "-c:v",
            "copy",  # copy input codec without re-encoding; speeds up conversion and avoids quality loss
            None,  # output placeholder
        ],
        in_extension=".h264",
        camera_name=CAMERA_LABEL,
        function_logging_label="h264_convert_to_mp4",
    )

    continuous_record_driver(
        camera_name=CAMERA_LABEL,
        initialise_hardware_function=initialise_picamera2,
        record_function=record_to_temp_h264,
        processing_function=h264_convert_to_mp4,
        cleanup_function=cleanup_picamera2,
    )
