"""Run with care this will screw with a dir if wrong
"""
import logging

from pathlib import Path
import os
import sys
import shutil
sys.path.append(r"/home/brend/Documents")
import timestamping

KB = 1024
MB = 1024 * KB
GB = 1024 * MB
byte_dict = {"kb": KB, "mb": MB, "gb": GB}

# TODO: NEED TO TUNE / CALCULATE THIS DEPENDING ON HOW OFTEN THIS WILL BE RUN
# AND THE SIZE OF THE STORAGE DISK
THRESHOLD = 0.8

USB_DEVICE_NAME = "E657-3701"
USB_PATH = os.path.join("/media/brend", USB_DEVICE_NAME)
USB_VID_PATH = os.path.join(USB_PATH, "vidfiles")
LOGS_DIR_PATH = "/home/brend/Documents/diskmanage/logs"

def get_usb_usage(path: str, units_input: str = None):
    """Wrapper around shutil.disk_usage that returns:
        - total 
        - used
        - free
    """
    units_divisor = 1
    if units_input:
        units_input = units_input.lower()
        assert units_input in byte_dict, "invalid units passed into `get_usb_usage"
        units_divisor = byte_dict[units_input]
    
    total_used_free = shutil.disk_usage(path) # 3-tuple, don't unpack so we can map over
    return tuple(map(lambda bytes: bytes/units_divisor, total_used_free))

def assert_subpath(child_path: str, parent_path: str):
    child = Path(child_path).resolve()
    parent = Path(parent_path).resolve()
    if not child.is_relative_to(parent):
        raise ValueError(f"{child} is not a subpath of {parent}")

def auto_cleanup(
    *,
    monitor_path: str,
    clean_path: str,
    threshold_ratio: float
):
    """Detect disk usage at `monitor_path`
    """
    assert os.path.exists(monitor_path) and os.path.isdir(monitor_path)
    assert os.path.exists(clean_path) and os.path.isdir(clean_path)
    assert isinstance(threshold_ratio, float) and 0.5 < threshold_ratio < 1
    assert_subpath(child_path=clean_path, parent_path=monitor_path)
    logging.info(f"`auto_cleanup()`: valid function call, monitor_path-> {monitor_path}, clean_path-> {clean_path}, threshold-> {threshold_ratio}")

    total_bytes, used_bytes, _ = get_usb_usage(path=monitor_path)
    logging.info(f"`auto_cleanup()`: initial scan, currently using {used_bytes/GB}GB of total {total_bytes/GB}GB")

    to_clean_files = []
    if used_bytes / total_bytes > threshold_ratio:
        to_clean_files = [
            f for f in os.listdir(clean_path) 
            if f.endswith(".mp4") and timestamping.parse_filename(f)
        ]
        to_clean_files.sort()
        logging.info(f"`auto_cleanup()`: initialized cleaning list with {len(to_clean_files)} cleanable video files")
    else:
        logging.info(f"`auto_cleanup()`: disk usage is {used_bytes*100/total_bytes}% for now, no cleaning to happen")
        return 0

    cleaned_bytes = 0
    for file in to_clean_files:
        try:
            full_fpath = os.path.join(clean_path, file)
            file_size = os.path.getsize(full_fpath)
            os.remove(full_fpath)
            cleaned_bytes += file_size
            logging.info(f"`auto_cleanup()`: {file} of {file_size} was removed, total cleaned bytes: {cleaned_bytes}")
        except:
            logging.error(f"`auto_cleanup()`: {file} was unable to be removed")

        if (used_bytes - cleaned_bytes) / total_bytes < threshold_ratio:
            break
    
    if (used_bytes - cleaned_bytes) / total_bytes > threshold_ratio:
        logging.error(f"`auto_cleanup()`: after cleaning all cleanable video files, disk usage still exceeds threshold input: {threshold_ratio}")

    return cleaned_bytes

if __name__ == "__main__":
    # configure logger and generate timestamped log file name
    timestamped_log_fname = timestamping.generate_filename(
        camera_name=USB_DEVICE_NAME+"_CLEANLOG", # bit misleading naming but oh well...
        extension=".log"
    )
    assert os.path.exists(LOGS_DIR_PATH) and os.path.isdir(LOGS_DIR_PATH)
    logging.basicConfig(
        level=logging.INFO,  # Decreasing verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(LOGS_DIR_PATH, timestamped_log_fname)),
            logging.StreamHandler()  # also prints to console
        ]
    )

    try:
        # run some sort of loop here
        auto_cleanup(monitor_path=USB_PATH, clean_path=USB_VID_PATH, threshold_ratio=THRESHOLD)
    except:
        logging.critical("main: `auto_cleanup()` call caused exception")
