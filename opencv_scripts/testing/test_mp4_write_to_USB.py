import cv2
import os

USB_DEVICE_NAME = "E657-3701"

def record_mp4_to_usb(
    *,
    filename="test.mp4",
    duration_seconds=5,
    fps=20,
    width=640,
    height=480
):
    cap = cv2.VideoCapture(0)
    if not cap.isOpened:
        print("Error: Could not open video device.")
        return
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    codec = cv2.VideoWriter_fourcc(*'mp4v')  # 'mp4v' is common for mp4
    out = cv2.VideoWriter(filename, codec, fps, (width, height))

    target_frame_count = int(duration_seconds * fps)
    current_frame_count = 0
    print(f"Recording started. Saving to {filename} for {duration_seconds} seconds.")

    try:
        while current_frame_count < target_frame_count:
            ret, frame = cap.read()
            if not ret: 
                print(f"Failed to grab frame after {current_frame_count/fps} seconds.")
                break
            
            out.write(frame)
            current_frame_count += 1
    except:
        print("Unexpected termination")
    finally:
        print(f"{current_frame_count} of {target_frame_count} frames written to {filename}")
        cap.release()
        out.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    usb_path = f"/media/brend/{USB_DEVICE_NAME}"
    usb_output_path = os.path.join(usb_path, "test.mp4")
    record_mp4_to_usb(filename=usb_output_path)
