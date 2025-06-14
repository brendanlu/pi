from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from libcamera import Transform

import sys
import subprocess
import time
import os
import logging
from concurrent.futures import ThreadPoolExecutor

sys.path.append(r"/home/brend/Documents")
import timestamping

HOW_MANY_VIDS = 1
VID_LENGTH_SECONDS = 15

USB_DEVICE_NAME = "E657-3701"
USB_PATH = os.path.join("/media/brend", USB_DEVICE_NAME)
USB_VID_PATH = os.path.join(USB_PATH, "vidfiles")

WORKERS_LIMIT = 2


def ffmpeg_convert_h264_to_mp4(h264_fname):
    logging.debug(f"Processing job for {h264_fname} recieved and starting now...")
    try:
        timestamp, _ = timestamping.parse_filename(h264_fname, extension=".h264")
        mp4_fname = timestamping.generate_filename(for_time=timestamp, camera_name="TESTPiCam", extension=".mp4")
        mp4_fpath = os.path.join(USB_VID_PATH, mp4_fname)
        cmd = [
            "ffmpeg", # command-line tool ffmpeg for multimedia processing
            "-y", # output overwrites any files with same name
            "-framerate", "30", # picamera2 records at 30fps, ensures output matches
            "-i", h264_fname, # input .h264 file
            "-c:v", "copy", # copy input codec without re-encoding; speeds up conversion and avoids quality loss
            mp4_fpath # final argument output fpath
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL)
        os.remove(h264_fname)
        assert result.returncode == 0
        logging.info(f"Processing job for {h264_fname} successfully complete, output to {mp4_fpath}!")
    except:
        logging.critical(f"Processing job for {h264_fname} FAILED.")
        RuntimeError(f"Error thrown in converting {h264_fname}")


if __name__ == "__main__":
    assert os.path.exists(USB_VID_PATH) and os.path.isdir(USB_VID_PATH)

    # initialize logger
    logging.basicConfig(
        level=logging.DEBUG,  # Decreasing verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler("test_picamera2_latest.log", mode="w"),
            logging.StreamHandler()  # also prints to console
        ]
    )

    # -
    logging.debug("Initializing picamera and h264 encoder objects...")
    picam2 = Picamera2()
    video_config = picam2.create_video_configuration(
        main={"size": (1920, 1080)},
        transform=Transform(hflip=True, vflip=True)
    )
    picam2.configure(video_config)
    h264_encoder = H264Encoder()
    picam2.start()

    # -
    logging.debug("Initializing ThreadPoolExecutor...")
    executor = ThreadPoolExecutor(max_workers=WORKERS_LIMIT) 
    futures = []

    logging.debug(f"Starting loop: script set to record {HOW_MANY_VIDS} videos of length {VID_LENGTH_SECONDS}s")
    try:
        for i in range(HOW_MANY_VIDS):
            # this file name will be temporary, and it's timestamp will be parsed and
            # copied into the final filename
            h264_fname = timestamping.generate_filename(for_time="now", camera_name="TEMP", extension=".h264")
            logging.info(f"Video #{i+1}, fname: {h264_fname}, being recorded...")
            picam2.start_recording(h264_encoder, FileOutput(h264_fname))
            time.sleep(VID_LENGTH_SECONDS)
            picam2.stop_recording()

            # submit job for ffmpeg processing
            logging.debug(f"Video #{i+1}, fname: {h264_fname}, recorded, submitting conversion job...")
            future = executor.submit(ffmpeg_convert_h264_to_mp4, h264_fname)
            futures.append(future)
    except:
        logging.critical("Error in the recording loop.", exc_info=True)
    finally:
        logging.debug("Closing picam2...")
        picam2.close()

    for f in futures:
        try:
            f.result()
        except:
            logging.error("Exception caught in future:", exc_info=True)
    executor.shutdown()
