"""Hacky script to write some random .mp4 files from a USB camera device to
external USB storage device in a format that can be displayed on browser 
using flask

Makes a call in subprocess using ffmpeg to do the conversion
"""

import cv2
import os
import subprocess
import sys
import traceback

USB_DEVICE_NAME = "E657-3701"
TEMP_FNAME = "70temp.avi"

sys.path.append(r"/home/brend/Documents")
import timestamping

def record_mp4_to_usb(
    *,
    out_folder,
    duration_seconds,
    fps=20,
    width=640,
    height=480
):
    cap = cv2.VideoCapture(1) # run `v4l2-ctl --list-devices` in terminal
    if not cap.isOpened:
        print("Error: Could not open video device.")
        return
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    # write to .avi video file for conversion later
    # use ffmpeg H.264 encoder later, only way for now to get appropriate .mp4
    # format that will show in browser
    codec = cv2.VideoWriter_fourcc(*'MJPG')
    out = cv2.VideoWriter(TEMP_FNAME, codec, fps, (width, height))

    target_frame_count = int(duration_seconds * fps)
    current_frame_count = 0
    print(f"Recording started. Aiming to capture {duration_seconds}s of footage.")

    try:
        while current_frame_count < target_frame_count:
            ret, frame = cap.read()
            if not ret: 
                print(f"Failed to grab frame after {current_frame_count/fps} seconds.")
                break
            out.write(frame)
            if current_frame_count == 0:
                # get time stamped fname ASAP so it's accurate
                fname = timestamping.generate_filename(for_time="now", camera_name="testUSBcam")
            current_frame_count += 1
    except:
        print("Unexpected termination during video recording")
    finally:
        # cleanup cv2 stuff
        print("Initiating open-cv cleanup...")
        cap.release()
        out.release()
        # cv2.destroyAllWindows() # DO NOT NEED AS WE USED `pip install opencv-python-headless`
        print(f"{current_frame_count} of {target_frame_count} frames captured.")

        # perform video conversion
        try:
            assert os.path.exists(out_folder) and os.path.isdir(out_folder), "`out_folder` input is not valid"
            out_fpath = os.path.join(out_folder, fname)
            assert os.path.isfile(TEMP_FNAME), "ERROR: cannot find temp .avi file for conversion to .mp4"
            subprocess.run([
                "ffmpeg", # command-line tool ffmpeg for multimedia processing
                "-y", # output overwrites any files with same name
                "-i", TEMP_FNAME, # input .avi file
                "-c:v", "libx264", # use the H.264 encoder (libx264)
                "-preset", "fast", # encoding speed/quality trade-off preset
                "-crf", "23", # constant Rate Factor — controls quality (lower = better quality & bigger file); 23 is default
                "-pix_fmt", "yuv420p", # output pixel format: yuv420p generally compatible with most browsers
                out_fpath
            ])
        except:
            traceback.print_exc()
            sys.exit("ERROR: during .avi temp to .mp4 conversion and file writing")

        # remove temp file
        try: 
            os.remove(TEMP_FNAME)
        except:
            traceback.print_exc()
            sys.exit("ERROR: during deletion of .avi temp file, check if it was even created")

if __name__ == "__main__":
    usb_path = f"/media/brend/{USB_DEVICE_NAME}/vidfiles"
    # usb_output_fpath = os.path.join(usb_path, "test.mp4")
    for i in range(1):
        record_mp4_to_usb(out_folder=usb_path, duration_seconds=15)
