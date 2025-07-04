"""Running this file directly will test the functions within it
Despite some of the naming in this file, we actually use this module for
generating log file names as well as camera names!
"""

from datetime import datetime
import re
from typing import Callable, Literal, Tuple
import unittest

TIMESTAMP_FMT = r"%Y%m%d_%H%M%S"
TIMESTAMP_REGEX_FMT = r"(\d{8}_\d{6})" # ensure this matches above
DISPLAY_STR_FMT = r"%Y-%m-%d %H:%M:%S" # formatted string for display, e.g. "2025-06-11 15:30:15"

def _add_dot_to_extension(extension: str):
    if not extension.startswith("."):
        return "." + extension
    else: 
        return extension

def generate_filename(
        *,
        for_time: datetime|Literal["now"]|None="now",
        camera_name="camera1",
        extension=".mp4",
    ) -> str:
    """We need to be quite careful when generating files, because if we do it
    wrong it's a massive headache, so all parameters are keyword ONLY by
    deliberate design.
    """
    generate_now_timestamp: Callable[[], str] = lambda: datetime.now().strftime(TIMESTAMP_FMT)
    extension = _add_dot_to_extension(extension)
    if for_time == "now":
        timestamp = generate_now_timestamp()
    elif isinstance(for_time, datetime):
        timestamp = for_time.strftime(TIMESTAMP_FMT)
    else: # ERROR: `generate_filename` recieved non-datetime obj input
        timestamp = generate_now_timestamp()
    return f"{timestamp}_{camera_name}{extension}"

def parse_filename(fname: str, extension=".mp4") -> Tuple[datetime, str] | Tuple[None, None]:
    """Returns tuple containing:
         - timestamp as datetime object
         - camera name as string
    Otherwise returns None if cannot parse
    """
    try:
        extension = _add_dot_to_extension(extension)
    except:
        extension = extension
    try:
        assert fname.endswith(extension)
        regex_obj = re.fullmatch(TIMESTAMP_REGEX_FMT + rf"_(.+){re.escape(extension)}", fname)
        assert regex_obj, f"ERROR: {fname} is unable to be timestamp parsed!"
        timestamp_str, camera_name = regex_obj.groups()
        dt = datetime.strptime(timestamp_str, TIMESTAMP_FMT)
        return dt, camera_name
    except:
        return None, None

def dt_strfmt(dt: datetime):
    return dt.strftime(DISPLAY_STR_FMT)

class TestUtils(unittest.TestCase):
    def test_filename_generate_and_parse(self):
        for extension in [".mp4", ".log", "mp4", "log", "h264", "h.264", ".h.264"]:
            # generate dummy file name
            input_dt = datetime.now()
            input_camera_name = "aaa_bbb"
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

    # -- big brain prompt engineer tests below....

    def test_parse_bad_filenames(self):
        self.assertEqual(parse_filename("badname.mp4"), (None, None))
        self.assertEqual(parse_filename("20210615_123045.mp4"), (None, None))  # missing camera name
        self.assertEqual(parse_filename("20210615_123045_camera1.txt"), (None, None))  # wrong extension
        self.assertEqual(parse_filename("not_even_close"), (None, None))  # completely wrong format
    

    def test_generate_filename_invalid_for_time(self):
        """If for_time is invalid (e.g. int, list), fallback to now without error."""
        invalid_inputs = [42, [], {}, 3.14, object()]
        for inval in invalid_inputs:
            fname = generate_filename(for_time=inval, camera_name="cam", extension=".mp4")
            self.assertIsInstance(fname, str)
            self.assertTrue(re.match(r"\d{8}_\d{6}_cam\.mp4", fname))

    def test_generate_filename_camera_name_special_chars(self):
        """Filename generation should handle special characters in camera_name."""
        specials = ["cam name", "cam-name", "cam.name", "cam@name!", "123_cam"]
        for name in specials:
            fname = generate_filename(for_time=datetime(2025, 6, 16, 10, 30, 45), camera_name=name)
            self.assertIn(name, fname)
            self.assertTrue(fname.endswith(".mp4"))

    def test_parse_filename_wrong_extension_case(self):
        """Parsing should fail if extension case does not exactly match."""
        fname = "20250616_103045_camera1.MP4"
        self.assertEqual(parse_filename(fname, extension=".mp4"), (None, None))

    def test_parse_filename_extra_underscores_in_camera_name(self):
        """Parsing should correctly extract camera name even if it contains underscores."""
        fname = "20250616_103045_my_camera_name.mp4"
        parsed = parse_filename(fname, extension=".mp4")
        self.assertIsNotNone(parsed)
        dt, cam_name = parsed
        self.assertEqual(cam_name, "my_camera_name")
        self.assertEqual(dt, datetime.strptime("20250616_103045", TIMESTAMP_FMT))

    def test_parse_filename_missing_timestamp(self):
        """Parsing should fail if timestamp is missing or malformed."""
        bad_fnames = [
            "_camera1.mp4",
            "20250616_camera1.mp4",
            "20250616103045_camera1.mp4",
            "2025_06_16_103045_camera1.mp4"
        ]
        for fname in bad_fnames:
            self.assertEqual(parse_filename(fname, extension=".mp4"), (None, None))

    def test_generate_and_parse_for_time_now_string(self):
        """generate_filename with for_time='now' string should generate a valid filename parseable back."""
        fname = generate_filename(for_time="now", camera_name="camX", extension=".log")
        parsed = parse_filename(fname, extension=".log")
        self.assertIsNotNone(parsed)
        dt, cam_name = parsed
        self.assertEqual(cam_name, "camX")
        self.assertIsInstance(dt, datetime)

    def test_generate_filename_with_none_for_time(self):
        """generate_filename with for_time=None should behave like 'now'."""
        fname = generate_filename(for_time=None, camera_name="camY")
        parsed = parse_filename(fname)
        self.assertIsNotNone(parsed)
        _, cam_name = parsed
        self.assertEqual(cam_name, "camY")

    def test_parse_filename_empty_string(self):
        """Parsing an empty string should safely return (None, None)."""
        self.assertEqual(parse_filename("", extension=".mp4"), (None, None))

    def test_parse_filename_long_camera_name(self):
        """Parsing should handle very long camera names without crashing."""
        long_name = "a" * 1000
        fname = f"20250616_103045_{long_name}.mp4"
        parsed = parse_filename(fname, extension=".mp4")
        self.assertIsNotNone(parsed)
        dt, cam_name = parsed
        self.assertEqual(cam_name, long_name)


if __name__ == "__main__":
    unittest.main()
