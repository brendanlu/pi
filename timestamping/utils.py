"""Running this file directly will test the functions within it
Despite some of the naming in this file, we actually use this module for
generating log file names as well as camera names!
"""

from datetime import datetime
import re
from typing import Tuple, Union
import unittest

TIMESTAMP_FMT = r"%Y%m%d_%H%M%S"
TIMESTAMP_REGEX_FMT = r"(\d{8}_\d{6})" # ensure this matches above
DISPLAY_STR_FMT = r"%Y-%m-%d %H:%M:%S" # formatted string for display, e.g. "2025-06-11 15:30:15"

def generate_filename(
        *,
        for_time: datetime = "now",
        camera_name="camera1",
        extension=".mp4",
    ) -> str:
    """We need to be quite careful when generating files, because if we do it
    wrong it's a massive headache, so all parameters are keyword ONLY by
    deliberate design.
    """
    if for_time == "now":
        timestamp = datetime.now().strftime(TIMESTAMP_FMT)
    else:
        assert isinstance(for_time, datetime), "ERROR: `generate_filename` recieved non-datetime obj input"
        timestamp = for_time.strftime(TIMESTAMP_FMT)
    return f"{timestamp}_{camera_name}{extension}"

def parse_filename(fname: str, extension=".mp4") -> Tuple[datetime, str] | None:
    """Returns tuple containing:
         - timestamp as datetime object
         - camera name as string
    Otherwise returns None if cannot parse
    """
    try:
        assert fname.endswith(extension)
        regex_obj = re.match(TIMESTAMP_REGEX_FMT + f"_(.+)\{extension}", fname)
        assert regex_obj, f"ERROR: {fname} is unable to be timestamp parsed!"
        timestamp_str, camera_name = regex_obj.groups()
        dt = datetime.strptime(timestamp_str, TIMESTAMP_FMT)
        return dt, camera_name
    except:
        return None

def dt_strfmt(dt: datetime):
    return dt.strftime(DISPLAY_STR_FMT)

class TestUtils(unittest.TestCase):
    def test_filename_generate_and_parse(self):
        for extension in [".mp4", ".log"]:
            # generate dummy file name
            input_dt = datetime.now()
            input_camera_name = "aaa"
            fname = generate_filename(
                for_time=input_dt,
                camera_name=input_camera_name,
                extension=extension
            )

            # parse dummy file name
            parsed_dt, parsed_camera_name = parse_filename(
                fname,
                extension=extension
            )

            # check roundabout works
            # get rid of microsecond data in input_dt as we lose this info when 
            # timestamping files
            self.assertEqual(input_dt.replace(microsecond=0), parsed_dt)
            self.assertEqual(input_camera_name, parsed_camera_name)
    
    def test_generate_filename_for_NOW(self):
        self.assertIsInstance(generate_filename(), str)

if __name__ == "__main__":
    unittest.main()
