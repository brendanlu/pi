import subprocess
import os 
import signal
import sys

VIDEO_DEVICE = "/dev/video1"

# the follow just points to the clone of the repo
mjpg_streamer_path = r"/home/brend/Downloads/mjpg-streamer/mjpg-streamer-experimental"

# run commands don't exactly know what these do
mjpg_streamer_cmd = [
    "./mjpg_streamer",
    "-i", f"./input_uvc.so -d {VIDEO_DEVICE}",
    "-o", "./output_http.so -w ./www"
]

def make_process_shutdown_handler(process):
    """Create a function that we can pass into signal.signal() to gracefully
    terminate the input process on shutdown of the script
    """
    def shutdown(signum, frame):
        """This must adhere to the signal.signal() interface
        """
        print("\nStopping mjpg-streamer")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Process didn't shutdown in time, killing manually...")
            process.kill()
        
        os.system(f"sudo fuser -k {VIDEO_DEVICE}")
        print("Cleanup complete")
        sys.exit(0)
    
    return shutdown

if __name__ == "__main__":
    mjpg_streamer_process = subprocess.Popen(mjpg_streamer_cmd, cwd=mjpg_streamer_path)
    signal.signal(signal.SIGINT, make_process_shutdown_handler(mjpg_streamer_process))
    print("mjpg-streamer running. Press Ctrl+C to stop")
    signal.pause()
