from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from libcamera import Transform  # type: ignore

import logging
import sys
import threading

from continuous import continuous_record_driver, ok_dir

sys.path.append(r"/home/brend/Documents")
import timestamping

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


def convert_h264_to_mp4(h264_fname):
    logging.debug(
        f"`convert_h264_to_mp4`Processing job for {h264_fname} recieved and starting now..."
    )
    try:
        timestamp, _ = timestamping.parse_filename(h264_fname, extension=".h264")
        mp4_fname = timestamping.generate_filename(
            for_time=timestamp, camera_name="TESTPiCam", extension=".mp4"
        )
        mp4_fpath = os.path.join(USB_VID_PATH, mp4_fname)
        cmd = [
            "ffmpeg",  # command-line tool ffmpeg for multimedia processing
            "-y",  # output overwrites any files with same name
            "-framerate",
            "30",  # picamera2 records at 30fps, ensures output matches
            "-i",
            h264_fname,  # input .h264 file
            "-c:v",
            "copy",  # copy input codec without re-encoding; speeds up conversion and avoids quality loss
            mp4_fpath,  # final argument output fpath
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL)
        os.remove(h264_fname)
        assert result.returncode == 0
        logging.info(
            f"Processing job for {h264_fname} successfully complete, output to {mp4_fpath}!"
        )
    except:
        logging.critical(f"Processing job for {h264_fname} FAILED.")
        raise RuntimeError(f"Error thrown in converting {h264_fname}")


def record_to_temp_h264(picam2: Picamera2, h264_encoder: H264Encoder) -> str | None:
    pass


if __name__ == "__main__":
    continuous_record_driver(
        camera_name="PI_CAMERA",
    )
