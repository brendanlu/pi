import os
import sys
sys.path.append(r"/home/brend/Documents")
import timestamping

LOGS_DIR_PATHS_LIST = [
    # "/home/brend/Documents/diskmanage/logs",
    # "/home/brend/Documents/opencv/logs"
]

def clean_logs_dir(dir_path):
    assert os.path.exists(dir_path) and os.path.isdir(dir_path)
    to_clean = list(os.listdir(dir_path))
    for f in to_clean:
        assert f.endswith(".log"), f"NON LOG FILE FOUND: {f}"
        assert timestamping.parse_filename(f, ".log"), f"MALFORMED LOG FILE FOUND: {f}"
        fpath = os.path.join(dir_path, f)
        assert os.path.isfile(fpath)
        try:
            os.remove(fpath)
        except:
            RuntimeError(f"COULD NOT DELETE {f}")
    print(f"SUCCESSFULLY CLEANED {len(to_clean)} LOG FILES")

if __name__ == "__main__":
    for path in LOGS_DIR_PATHS_LIST: 
        clean_logs_dir(path)
