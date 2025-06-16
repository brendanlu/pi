import os
import sys
sys.path.append(r"/home/brend/Documents")
import timestamping

LOGS_DIR_PATH = "/home/brend/Documents/diskmanage/logs"
# LOGS_DIR_PATH = "/home/brend/Documents/opencv/logs"

if __name__ == "__main__":
    assert os.path.exists(LOGS_DIR_PATH) and os.path.isdir(LOGS_DIR_PATH)
    to_clean = list(os.listdir(LOGS_DIR_PATH))
    for f in to_clean:
        assert f.endswith(".log"), f"NON LOG FILE FOUND: {f}"
        assert timestamping.parse_filename(f, ".log"), f"MALFORMED LOG FILE FOUND: {f}"
        fpath = os.path.join(LOGS_DIR_PATH, f)
        assert os.path.isfile(fpath)
        try:
            os.remove(fpath)
        except:
            RuntimeError(f"COULD NOT DELETE {f}")
    print(f"SUCCESSFULLY CLEANED {len(to_clean)} LOG FILES")
