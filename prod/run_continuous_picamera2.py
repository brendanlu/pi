from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from libcamera import Transform

import logging
import threading

PICAM_WIDTH = 1920
PICAM_HEIGHT = 1080


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


def record_to_temp_h264(picam2: Picamera2, h264_encoder: H264Encoder) -> str | None:
    pass
