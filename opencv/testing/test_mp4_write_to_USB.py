import cv2
import os
import subprocess

USB_DEVICE_NAME = "E657-3701"

def record_mp4_to_usb(
    *,
    out_fpath="test.mp4",
    duration_seconds=5,
    fps=20,
    width=640,
    height=480
):
    assert out_fpath.endswith(".mp4"), "Please ensure `out_fpath` is .mp4"

    cap = cv2.VideoCapture(0)
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
    temp_fname = "69temp.avi"
    out = cv2.VideoWriter(temp_fname, codec, fps, (width, height))

    target_frame_count = int(duration_seconds * fps)
    current_frame_count = 0
    print(f"Recording started. Saving to {out_fpath} for {duration_seconds} seconds.")

    try:
        while current_frame_count < target_frame_count:
            ret, frame = cap.read()
            if not ret: 
                print(f"Failed to grab frame after {current_frame_count/fps} seconds.")
                break
            
            out.write(frame)
            current_frame_count += 1
    except:
        print("Unexpected termination during video recording")
    finally:
        print(f"{current_frame_count} of {target_frame_count} frames written to {out_fpath}")

        # cleanup cv2 stuff
        cap.release()
        out.release()
        cv2.destroyAllWindows()

        # perform video conversion
        try:
            assert os.path.isfile(temp_fname), "ERROR: cannot find temp .avi file for conversion to .mp4"
            subprocess.run([
                "ffmpeg", # command-line tool ffmpeg for multimedia processing
                "-y", # output overwrites any files with same name
                "-i", temp_fname, # input .avi file
                "-c:v", "libx264", # use the H.264 encoder (libx264)
                "-preset", "fast", # encoding speed/quality trade-off preset
                "-crf", "23", # constant Rate Factor — controls quality (lower = better quality & bigger file); 23 is default
                "-pix_fmt", "yuv420p", # output pixel format: yuv420p generally compatible with most browsers
                out_fpath
            ])
            os.remove(temp_fname)
        except:
            print("ERROR: during .avi temp to .mp4 conversion")

if __name__ == "__main__":
    usb_path = f"/media/brend/{USB_DEVICE_NAME}"
    usb_output_fpath = os.path.join(usb_path, "test.mp4")
    record_mp4_to_usb(out_fpath=usb_output_fpath)
