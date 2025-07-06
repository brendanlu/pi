import cv2

import logging
import numpy as np
import os

# -- memory disk
USB_DEVICE_NAME = "E657-3701"
USB_PATH = os.path.join("/media/brend", USB_DEVICE_NAME)
USB_VID_PATH = os.path.join(USB_PATH, "vidfiles")


def is_over_mean_bright_threshold(frame: np.ndarray, threshold: int) -> bool:
    return bool(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)) > threshold)


# below is testing code
if __name__ == "__main__":
    logging.basicConfig(
        # decreasing verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("processing_test_last.log", mode="w"),
            # logging.StreamHandler()  # also prints to console
        ],
    )

    cap = cv2.VideoCapture(os.path.join(USB_VID_PATH, "20250706_210039_USB_CAMERA.mp4"))
    frame_count = 0
    over_brightness_threshold_frame_count = 0
    mean_brightness_event_flag = False

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            logging.info("done or failed to read frame")
            break
        frame_count += 1

        # best to put all processing into separate try-except block
        try:
            mb = np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            logging.debug(f"mean brightness: {mb}")
            if is_over_mean_bright_threshold(frame, 7):
                if over_brightness_threshold_frame_count == 0:
                    logging.debug(
                        f"Mean brightness threshold exceeded on frame {frame_count}"
                    )
                over_brightness_threshold_frame_count += 1
            else:
                over_brightness_threshold_frame_count = 0
                mean_brightness_event_flag = False

            if (
                over_brightness_threshold_frame_count >= 40
                and not mean_brightness_event_flag
            ):
                logging.info("Mean brightness event")
                mean_brightness_event_flag = True
        except:
            logging.error(f"processing error for frame {frame_count}")

    cap.release()
