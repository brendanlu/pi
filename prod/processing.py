import cv2

import logging
import os
import signal
import threading

# -- memory disk
USB_DEVICE_NAME = "E657-3701"
USB_PATH = os.path.join("/media/brend", USB_DEVICE_NAME)
USB_VID_PATH = os.path.join(USB_PATH, "vidfiles")


def is_over_mean_bright_threshold(frame, threshold: int) -> bool:
    # mean returns (B, G, R, alpha)
    mean_val = cv2.mean(frame)  # tuple of floats
    # convert to grayscale luminance without full cvtColor
    # In Rec. 601 (used for SD video and many image formats), the formula is:
    #   Y' = 0.299R' + 0.587G' + 0.114B'
    brightness = 0.114 * mean_val[0] + 0.587 * mean_val[1] + 0.299 * mean_val[2]
    return brightness > threshold


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

    shutdown_flag = threading.Event()

    def signal_handler(sig, frame):
        """Signal handler for any program interruptions, this gets registered
        for all processes
        """
        logging.info(
            f"`signal_handler()`: signal {sig} recieved in PID {os.getpid()}, setting shutdown flag..."
        )
        shutdown_flag.set()

    signal.signal(signal.SIGQUIT, signal_handler)  # quit signal

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FPS, 19)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    frame_count = 0
    while cap.isOpened() and not shutdown_flag.is_set():
        frame_count += 1
        ret, frame = cap.read()
        if not ret:
            logging.info(f"Failed to read frame {frame_count}")
            break

        # best to put all processing into separate try-except block
        try:

            def get_brightness(frame):
                mv = cv2.mean(frame)
                return 0.114 * mv[0] + 0.587 * mv[1] + 0.299 * mv[2]

            logging.debug(f"Frame {frame_count}: {get_brightness(frame)}")
        except:
            logging.error(f"processing error for frame {frame_count}")

    cap.release()
