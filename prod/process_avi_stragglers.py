import glob
import os

from run_continuous_opencv import avi_convert_to_mp4

USB_DEVICE_NAME = "DYNABOOK"
USB_PATH = os.path.join("/media/brend", USB_DEVICE_NAME)
USB_VID_PATH = os.path.join(USB_PATH, "vidfiles")
SUBPROCESS_TIMEOUT_SECONDS = 600 # 5 minutes, roughly twice as long as 5min vid 

if __name__ == "__main__":
    avi_temp_files = glob.glob("*_TEMP.avi")
    for file in avi_temp_files:
        # avi_convert_to_mp4(file, USB_VID_PATH, SUBPROCESS_TIMEOUT_SECONDS, )
        pass

