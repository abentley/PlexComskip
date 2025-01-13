#!/usr/bin/env python3

import configparser
import contextlib
from collections import namedtuple
from enum import Enum
from functools import partial
from itertools import pairwise
import logging
import os
from pathlib import Path
import math
from multiprocessing import Pool
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid


class Action(Enum):

    SKIP = b'0'

    MUTE = b'1'


def sizeof_fmt(num, suffix='B'):
    """
    Converts a number of bytes to a human-readable format.

    Args:
        num: The number of bytes to convert.
        suffix: The suffix to use for the unit (default: 'B').

    Returns:
        A string representing the number of bytes in a human-readable format.
    """
    units = ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y']
    unit_index = min(int(math.log(max(num, 1), 1024)), 8)
    unit = units[unit_index]
    num /= float(1024 ** unit_index)
    return "%3.1f%s%s" % (num, unit, suffix)


# Clean up after ourselves and exit.
def cleanup_and_exit(temp_dir, keep_temp=False):
    """
    Cleans up the temporary directory and exits the program.

    Args:
        temp_dir: The path to the temporary directory.
        keep_temp: If True, the temporary directory will be preserved.
                   Defaults to False.
    """
    if keep_temp:
        logging.info('Leaving temp files in: %s' % temp_dir)
    else:
        try:
            # Get out of the temp dir before we nuke it (causes issues on NTFS)
            os.chdir(os.path.expanduser('~'))
            shutil.rmtree(temp_dir)
        except Exception as e:
            logging.error('Problem whacking temp dir: %s' % temp_dir)
            logging.error(str(e))

    # Exit cleanly.
    logging.info('Done processing!')
    # sys.exit(0)


@contextlib.contextmanager
def work_dir(temp_root, session_uuid, save_always, save_forensics):
    """Provide a work directory.

    The supplied temp root and session uuid are used to create the directory.

    If save_always is True, the results will be kept.  If save_forensics is
    True and there is an exception, the results will be kept.  Otherwise, they
    will be deleted.
    """
    temp_dir = Path(temp_root) / session_uuid
    os.makedirs(temp_dir)
    keep = save_always
    try:
        yield temp_dir
    except BaseException:
        keep = keep or save_forensics
        raise
    finally:
        cleanup_and_exit(temp_dir, keep_temp=keep)


def main():
    global COPY_ORIGINAL, SAVE_ALWAYS, NICE_ARGS, COMSKIP_PATH
    global COMSKIP_INI_PATH, FFMPEG_PATH
    # Config stuff.
    script_dir = Path(__file__).resolve().parent
    config_file_path = script_dir / 'PlexComskip.conf'
    if not config_file_path.exists():
        print('Config file not found: %s' % config_file_path)
        print('Make a copy of PlexConfig.conf.example named PlexConfig.conf,'
              ' modify as necessary, and place in the same directory as this'
              ' script.')
        sys.exit(1)

    config = configparser.ConfigParser({
        'comskip-ini-path': str(script_dir / 'comskip.ini'),
        'temp-root': tempfile.gettempdir(), 'nice-level': '0'
    })
    config.read(config_file_path)

    COMSKIP_PATH = os.path.expandvars(os.path.expanduser(
        config.get('Helper Apps', 'comskip-path')))
    COMSKIP_INI_PATH = os.path.expandvars(os.path.expanduser(
        config.get('Helper Apps', 'comskip-ini-path')))
    FFMPEG_PATH = os.path.expandvars(os.path.expanduser(
        config.get('Helper Apps', 'ffmpeg-path')))
    LOG_FILE_PATH = os.path.expandvars(
        os.path.expanduser(config.get('Logging', 'logfile-path')))
    CONSOLE_LOGGING = config.getboolean('Logging', 'console-logging')
    TEMP_ROOT = os.path.expandvars(os.path.expanduser(
        config.get('File Manipulation', 'temp-root')))
    COPY_ORIGINAL = config.getboolean('File Manipulation', 'copy-original')
    SAVE_ALWAYS = config.getboolean('File Manipulation', 'save-always')
    SAVE_FORENSICS = config.getboolean('File Manipulation', 'save-forensics')
    NICE_LEVEL = config.get('Helper Apps', 'nice-level')

    # Logging.
    session_uuid = str(uuid.uuid4())
    fmt = '%%(asctime)-15s [%s] %%(message)s' % session_uuid[:6]
    Path(LOG_FILE_PATH).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format=fmt, filename=LOG_FILE_PATH)
    if CONSOLE_LOGGING:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        console.setFormatter(formatter)
        logging.getLogger('').addHandler(console)

    # Human-readable bytes.
    if len(sys.argv) < 2:
        print('Usage: PlexComskip.py input-file.mkv')
        sys.exit(1)

    logging.info('PlexComskip got invoked from %s' % Path(__file__).resolve())
    # If we're in a git repo, let's see if we can report our sha.
    try:
        git_sha = subprocess.check_output(
            'git rev-parse --short HEAD', shell=True)
        if git_sha:
            logging.info('Using version: %s' % git_sha.strip())
    except BaseException:
        pass

    # Set our own nice level and tee up some args for subprocesses (unix-like
    # OSes only).
    NICE_ARGS = []
    if sys.platform != 'win32':
        try:
            nice_int = max(min(int(NICE_LEVEL), 20), 0)
            if nice_int > 0:
                os.nice(nice_int)
                NICE_ARGS = ['nice', '-n', str(nice_int)]
        except Exception as e:
            logging.error('Couldn\'t set nice level to %s: %s' %
                          (NICE_LEVEL, e))

    # On to the actual work.
    with work_dir(TEMP_ROOT, session_uuid, SAVE_ALWAYS,
                  SAVE_FORENSICS) as temp_dir:
        do_work(session_uuid, temp_dir)


def make_segment_file(temp_video_path, start, end, num):
    """Make a segment file and return its filename."""
    video_ext = temp_video_path.suffix
    segment_name = 'segment-%s' % num
    segment_file_name = '%s%s' % (segment_name, video_ext)
    cmd = NICE_ARGS + [FFMPEG_PATH, '-i', temp_video_path, '-ss', str(start)]
    if end != -1:
        cmd.extend(['-t', str(end - start)])
    cmd.extend(['-c', 'copy', segment_file_name])
    logging.info('[ffmpeg] Command: %s' % cmd)
    try:
        subprocess.check_call(cmd)
    except Exception as e:
        logging.error('Exception running ffmpeg: %s' % e)
        raise
    return Path(segment_file_name)


def parse_edl(edl_lines):
    """
    Parses an mplayer-style EDL (Edit Decision List) file and yields the start
    time, end time, and action for each segment.

    Args:
        edl_lines: An iterable of lines from the EDL file.
                   Each line is expected to be in the format:
                   "start_time end_time action"
                   where `start_time` and `end_time` are floats
                   and `action` is an instance of the `Action` enum.

    Yields:
        A tuple containing the start time, end time, and action
        for each segment in the EDL file.
    """
    for line in edl_lines:
        data = line.split()
        start = float(data[0])
        end = float(data[1])
        action = Action(data[2])
        yield (start, end, action)


def edl_to_segments(edl_segments):
    """
    Yields segments to keep based on the provided EDL segments.

    Args:
        edl_segments: A list of tuples representing EDL segments
                      (start_time, end_time, action).

    Yields:
        A tuple representing a segment to keep (start_time, end_time).
    """
    def maybe_yield(segment):
        if segment.start < segment.end:
            yield segment

    next_end = 0.0  # Handle empty input
    for num, ((start, end, _), (next_start, next_end, _)) in enumerate(
        pairwise(edl_segments)
    ):
        if num == 0:
            yield from maybe_yield(Segment(0.0, start))
        yield from maybe_yield(Segment(end, next_start))
    # Yield the last segment to the end of the file
    yield Segment(next_end, -1)


def list_segments(edl_file):
    """Use the supplied EDL file to produce a segment list.

    The segments returned are the segments to keep; this is the opposite of the
    EDL, which lists segments to remove.

    Because we don't know how long the file is from the EDL, the last segment
    may be 0-length.
    """
    with edl_file.open('rb') as edl:
        # EDL contains segments we need to drop, so chain those together
        # into segments to keep.
        edl_segments = list(parse_edl(edl))
    return list(edl_to_segments(edl_segments))


def write_segment_file(input_video, i, segment):
    """
    Creates a segment file from the input video.

    Args:
        input_video: The path to the input video file.
        i: The index of the segment.
        segment: A tuple containing the start and end time of the segment.

    Returns:
        The path to the created segment file,
        or None if the segment has a zero duration.
    """
    segment_file_name = make_segment_file(input_video, segment[0],
                                          segment[1], i)
    # If the last drop segment ended at the end of the file, we will have
    # written a zero-duration file.
    if os.path.getsize(segment_file_name) < 1000:
        logging.info(
            'Last segment ran to the end of the file, not adding bogus segment'
            '%s for concatenation.' % (i + 1)
        )
        return None
    return segment_file_name


def write_segments(input_video, temp_dir, segments):
    """
    Creates segment files for each segment in the list.

    Args:
        input_video: The path to the input video file.
        temp_dir: The path to the temporary directory.
        segments: A list of lists, where each list represents a segment
                  with [start_time, end_time].

    Yields:
        A list of paths to each created segment file.
    """
    with Pool() as p:
        segment_file_names = p.starmap(
            partial(write_segment_file, input_video), enumerate(segments))
    return (f for f in segment_file_names if f is not None)


def write_segments_file(temp_dir, segment_files):
    """
    Creates a text file containing a list of segment files.

    Args:
        temp_dir: The path to the temporary directory.
        segment_files: An iterable of paths to segment files.

    Returns:
        The path to the created segment list file.
    """
    segment_list_file_path = temp_dir / 'segments.txt'
    with open(segment_list_file_path, 'wb') as segment_list_file:
        for segment_file_name in segment_files:
            segment_list_file.write(b'file %s\n' % segment_file_name)
    return segment_list_file_path


def remove_commercials(temp_dir, input_video, edl_file):
    """
    Removes commercials from the input video using the provided EDL file.

    Args:
        temp_dir: The path to the temporary directory.
        input_video: The path to the input video file.
        edl_file: The path to the EDL file generated by Comskip.

    Returns:
        The path to the output video file without commercials.
    """
    logging.info('Using EDL: %s', edl_file)
    target_path = temp_dir / input_video.with_suffix('.spliced.ts').name
    try:
        segments = list_segments(edl_file)
        segments = extend_end(segments)
        segment_files = list(write_segments(input_video, temp_dir, segments))
        segment_list_file_path = write_segments_file(temp_dir, segment_files)

    except Exception as e:
        logging.error('Something went wrong during splitting: %s' % e)
        raise

    logging.info('Going to concatenate %s files from the segment list.' %
                 len(segment_files))
    try:
        ffmpeg_concat(segment_list_file_path, target_path)
    except Exception as e:
        logging.error('Something went wrong during concatenation: %s' % e)
        raise

    return target_path


def ffmpeg_concat(segment_list_file_path, target_path):
    cmd = NICE_ARGS + [FFMPEG_PATH, '-y', '-f', 'concat', '-i',
                       segment_list_file_path, '-c', 'copy', target_path]
    logging.info('[ffmpeg] Command: %s' % cmd)
    subprocess.check_call(cmd)


def call_and_retry(cmd, retries=2):
    """
    Executes a subprocess command and retries it if it segfaults.

    Args:
        cmd: The command to execute as a list.
        retries: The number of retries to attempt. Defaults to 2.

    Raises:
        subprocess.CalledProcessError: If the command fails after all retries.
    """
    for num in range(retries):
        if num != 0:
            logging.info("Retry {} of {}".format(num, cmd))
        try:
            return subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            if e.returncode != -signal.SIGSEGV:
                raise
            if num == retries - 1:
                logging.error("Giving up after {} attempts".format(retries))
                raise


def detect_commercials(temp_dir, temp_video_path):
    """Use comskip to detect commercials.  Return path to edl."""
    edl_file = temp_dir / temp_video_path.with_suffix('.edl').name
    # Process with comskip.
    cmd = NICE_ARGS + [COMSKIP_PATH, '--output', temp_dir, '--ini',
                       COMSKIP_INI_PATH, temp_video_path]
    logging.info('[comskip] Command: %s' % cmd)
    call_and_retry(cmd)
    return edl_file


def replace_original(input_video, output_video):
    """
    Determine whether to replace the output with the input.

    Checks whether the new files is meaningfully smaller than the original.
    Ensures that the new file is not less than half the size of the original.
    (Ideally these checks would test *duration*, not file size, but we're
    copying the bitstream, so it should be okay.).

    Args:
        input_video: The path to the original video file.
        output_video: The path to the processed output video file.

    Returns:
        True if the original video file was replaced, False otherwise.

    Raises:
        Exception: If the output file size is significantly different
                   from the input file size, indicating a potential issue.
    """
    logging.info('Sanity checking our work...')
    try:
        input_size = os.path.getsize(input_video)
        output_size = os.path.getsize(output_video)
        if input_size and 1.01 > float(output_size) / float(input_size) > 0.99:
            logging.info(
                'Output file size was too similar (doesn\'t look like we did'
                ' much); we won\'t replace the original: %s -> %s'
                % (sizeof_fmt(input_size), sizeof_fmt(output_size))
            )
            return False
        elif input_size and 1.1 > float(output_size) / float(input_size) > 0.5:
            logging.info(
                'Output file size looked sane, we\'ll replace the original:'
                ' %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size))
            )
            return True
        else:
            logging.info(
                'Output file size looked wonky (too big or too small); we'
                ' won\'t replace the original: %s -> %s'
                % (sizeof_fmt(input_size), sizeof_fmt(output_size))
            )
            raise Exception('Wonky size')
    except Exception as e:
        logging.error('Something went wrong during sanity check: %s' % e)
        raise


Segment = namedtuple('Segment', ['start', 'end'])


def extend_end(segments, amount=5.0):
    extended = [
        Segment(s.start, s.end + amount) if s.end > 0 else s for s in segments
    ]
    extended2 = []
    cur = None
    for segment in extended:
        if cur is None:
            cur = segment
            continue
        if cur.end < segment.start:
            extended2.append(cur)
            cur = segment
        else:
            cur = Segment(cur.start, segment.end)
    if cur is not None:
        extended2.append(cur)
    return extended2


def do_work(session_uuid, temp_dir):
    """
    Performs the main processing steps for removing commercials from the video.

    Args:
        session_uuid: A unique identifier for the current processing session.
        temp_dir: The path to the temporary directory.

    Raises:
        Exception: If any error occurs during the processing steps.

    Note:
        Changes directory to temp_dir while processing, then to ~.
    """
    try:
        video_path = Path(sys.argv[1]).resolve()
        os.chdir(temp_dir)

        logging.info('Using session ID: %s' % session_uuid)
        logging.info('Using temp dir: %s' % temp_dir)
        logging.info('Using input file: %s' % video_path)

        original_video_dir = video_path.parent

    except Exception as e:
        logging.error(
            'Something went wrong setting up temp paths and working files: %s'
            % e)
        raise

    try:
        if COPY_ORIGINAL or SAVE_ALWAYS:
            temp_video_path = temp_dir / video_path.name
            logging.info('Copying file to work on it: %s' % temp_video_path)
            shutil.copyfile(video_path, temp_video_path)
        else:
            temp_video_path = video_path

        edl_file = detect_commercials(temp_dir, temp_video_path)

    except Exception as e:
        logging.error('Something went wrong during comskip analysis: %s' % e)
        raise

    output_video = remove_commercials(temp_dir, temp_video_path, edl_file)
    if replace_original(video_path, output_video):
        try:
            target = video_path.with_suffix(output_video.suffixes[-1])
            logging.info('Copying the output file into place: %s -> %s' %
                         (output_video, target))
            shutil.copy(output_video, target)
            if not target.samefile(video_path):
                video_path.unlink()
        except Exception as e:
            print(e)
            raise


if __name__ == '__main__':
    main()
