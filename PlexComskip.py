#!/usr/bin/python

import ConfigParser
import contextlib
import logging
import os
import math
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


def sizeof_fmt(num, suffix='B'):
  units = ['','K','M','G','T','P','E','Z', 'Y']
  unit_index = min(int(math.log(max(num, 1), 1024)), 8)
  unit = units[unit_index]
  num /= float(1024 ** unit_index)
  return "%3.1f%s%s" % (num, unit, suffix)


# Clean up after ourselves and exit.
def cleanup_and_exit(temp_dir, keep_temp=False):
  if keep_temp:
    logging.info('Leaving temp files in: %s' % temp_dir)
  else:
    try:
      os.chdir(os.path.expanduser('~'))  # Get out of the temp dir before we nuke it (causes issues on NTFS)
      shutil.rmtree(temp_dir)
    except Exception, e:
      logging.error('Problem whacking temp dir: %s' % temp_dir)
      logging.error(str(e))

  # Exit cleanly.
  logging.info('Done processing!')
  sys.exit(0)


@contextlib.contextmanager
def work_dir(temp_root, session_uuid, save_always, save_forensics):
    """Provide a work directory.

    The supplied temp root and session uuid are used to create the directory.

    If save_always is True, the results will be kept.  If save_forensics is
    True and there is an exception, the results will be kept.  Otherwise, they
    will be deleted.
    """
    temp_dir = os.path.join(temp_root, session_uuid)
    os.makedirs(temp_dir)
    keep = save_always
    try:
        yield temp_dir
    except:
        keep = keep or save_forensics
        raise
    finally:
        cleanup_and_exit(temp_dir, keep_temp=keep)
        

def main():
    global COPY_ORIGINAL, SAVE_ALWAYS, NICE_ARGS, COMSKIP_PATH
    global COMSKIP_INI_PATH, FFMPEG_PATH
    # Config stuff.
    config_file_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'PlexComskip.conf')
    if not os.path.exists(config_file_path):
      print 'Config file not found: %s' % config_file_path
      print 'Make a copy of PlexConfig.conf.example named PlexConfig.conf, modify as necessary, and place in the same directory as this script.'
      sys.exit(1)

    config = ConfigParser.SafeConfigParser({'comskip-ini-path' : os.path.join(os.path.dirname(os.path.realpath(__file__)), 'comskip.ini'), 'temp-root' : tempfile.gettempdir(), 'nice-level' : '0'})
    config.read(config_file_path)

    COMSKIP_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'comskip-path')))
    COMSKIP_INI_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'comskip-ini-path')))
    FFMPEG_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'ffmpeg-path')))
    LOG_FILE_PATH = os.path.expandvars(os.path.expanduser(config.get('Logging', 'logfile-path')))
    CONSOLE_LOGGING = config.getboolean('Logging', 'console-logging')
    TEMP_ROOT = os.path.expandvars(os.path.expanduser(config.get('File Manipulation', 'temp-root')))
    COPY_ORIGINAL = config.getboolean('File Manipulation', 'copy-original')
    SAVE_ALWAYS = config.getboolean('File Manipulation', 'save-always')
    SAVE_FORENSICS = config.getboolean('File Manipulation', 'save-forensics')
    NICE_LEVEL = config.get('Helper Apps', 'nice-level')

    # Logging.
    session_uuid = str(uuid.uuid4())
    fmt = '%%(asctime)-15s [%s] %%(message)s' % session_uuid[:6]
    if not os.path.exists(os.path.dirname(LOG_FILE_PATH)):
      os.makedirs(os.path.dirname(LOG_FILE_PATH))
    logging.basicConfig(level=logging.INFO, format=fmt, filename=LOG_FILE_PATH)
    if CONSOLE_LOGGING:
      console = logging.StreamHandler()
      console.setLevel(logging.INFO)
      formatter = logging.Formatter('%(message)s')
      console.setFormatter(formatter)
      logging.getLogger('').addHandler(console)

    # Human-readable bytes.
    if len(sys.argv) < 2:
      print 'Usage: PlexComskip.py input-file.mkv'
      sys.exit(1)


    # If we're in a git repo, let's see if we can report our sha.
    logging.info('PlexComskip got invoked from %s' % os.path.realpath(__file__))
    try:
      git_sha = subprocess.check_output('git rev-parse --short HEAD', shell=True)
      if git_sha:
        logging.info('Using version: %s' % git_sha.strip())
    except: pass

    # Set our own nice level and tee up some args for subprocesses (unix-like OSes only).
    NICE_ARGS = []
    if sys.platform != 'win32':
      try:
        nice_int = max(min(int(NICE_LEVEL), 20), 0)
        if nice_int > 0:
          os.nice(nice_int)
          NICE_ARGS = ['nice', '-n', str(nice_int)]
      except Exception, e:
        logging.error('Couldn\'t set nice level to %s: %s' % (NICE_LEVEL, e))

    # On to the actual work.
    with work_dir(TEMP_ROOT, session_uuid, SAVE_ALWAYS,
                  SAVE_FORENSICS) as temp_dir:
      do_work(session_uuid, temp_dir)


def make_segment_file(temp_video_path, start, end, num):
    """Make a segment file and return its filename."""
    video_ext = os.path.splitext(temp_video_path)[1]
    segment_name = 'segment-%s' % num
    segment_file_name = '%s%s' % (segment_name, video_ext)
    if end == -1:
        duration_args = []
    else:
        duration_args = ['-t', str(end - start)]
    cmd = NICE_ARGS + [FFMPEG_PATH, '-i', temp_video_path, '-ss', str(start)]
    cmd.extend(duration_args)
    cmd.extend(['-c', 'copy', segment_file_name])
    logging.info('[ffmpeg] Command: %s' % cmd)
    try:
        subprocess.call(cmd)
    except Exception, e:
        logging.error('Exception running ffmpeg: %s' % e)
        raise
    return segment_file_name


def list_segments(edl_file):
    """Use the supplied EDL file to produce a segment list.

    The segments returned are the segments to keep; this is the opposite of the
    EDL, which lists segments to remove.

    Because we don't know how long the file is from the EDL, the last segment
    may be 0-length.
    """
    segments = []
    prev_segment_end = 0.0
    if os.path.exists(edl_file):
	with open(edl_file, 'rb') as edl:
	    # EDL contains segments we need to drop, so chain those together
	    # into segments to keep.
	    for segment in edl:
		start, end, something = segment.split()
		if float(start) == 0.0:
		    logging.info('Start of file is junk, skipping this'
                                 ' segment...')
		else:
		    keep_segment = [float(prev_segment_end), float(start)]
		    logging.info('Keeping segment from %s to %s...'
                                 % (keep_segment[0], keep_segment[1]))
		    segments.append(keep_segment)
		prev_segment_end = end

    # Write the final keep segment from the end of the last commercial break to the end of the file.
    keep_segment = [float(prev_segment_end), -1]
    logging.info('Keeping segment from %s to the end of the file...' %
                 prev_segment_end)
    segments.append(keep_segment)
    return segments


def remove_commercials(temp_dir, input_video, edl_file, video_basename):
    logging.info('Using EDL: ' + edl_file)
    try:
      segments = list_segments(edl_file)
      segment_files = []
      segment_list_file_path = os.path.join(temp_dir, 'segments.txt')
      with open(segment_list_file_path, 'wb') as segment_list_file:
        for i, segment in enumerate(segments):
          segment_file_name = make_segment_file(input_video, segment[0],
                                                segment[1], i)
          # If the last drop segment ended at the end of the file, we will have
          # written a zero-duration file.
          if os.path.exists(segment_file_name):
            if os.path.getsize(segment_file_name) < 1000:
              logging.info('Last segment ran to the end of the file, not adding bogus segment %s for concatenation.' % (i + 1))
              continue

            segment_files.append(segment_file_name)
            segment_list_file.write('file %s\n' % segment_file_name)

    except Exception, e:
      logging.error('Something went wrong during splitting: %s' % e)
      raise

    logging.info('Going to concatenate %s files from the segment list.' % len(segment_files))
    try:
      target_path = os.path.join(temp_dir, video_basename)
      cmd = NICE_ARGS + [FFMPEG_PATH, '-y', '-f', 'concat', '-i',
                         segment_list_file_path, '-c', 'copy', target_path]
      logging.info('[ffmpeg] Command: %s' % cmd)
      subprocess.call(cmd)

    except Exception, e:
      logging.error('Something went wrong during concatenation: %s' % e)
      raise


def detect_commercials(temp_dir, temp_video_path, video_name):
    """Use comskip to detect commercials.  Return path to edl."""
    # Process with comskip.
    cmd = NICE_ARGS + [COMSKIP_PATH, '--output', temp_dir, '--ini',
                       COMSKIP_INI_PATH, temp_video_path]
    logging.info('[comskip] Command: %s' % cmd)
    subprocess.call(cmd)
    return os.path.join(temp_dir, video_name + '.edl')


def do_work(session_uuid, temp_dir):
    try:
      video_path = os.path.abspath(sys.argv[1])
      os.chdir(temp_dir)

      logging.info('Using session ID: %s' % session_uuid)
      logging.info('Using temp dir: %s' % temp_dir)
      logging.info('Using input file: %s' % video_path)


      original_video_dir = os.path.dirname(video_path)
      video_basename = os.path.basename(video_path)
      video_name, video_ext = os.path.splitext(video_basename)

    except Exception, e:
      logging.error('Something went wrong setting up temp paths and working files: %s' % e)
      raise

    try:
      if COPY_ORIGINAL or SAVE_ALWAYS: 
        temp_video_path = os.path.join(temp_dir, video_basename)
        logging.info('Copying file to work on it: %s' % temp_video_path)
        shutil.copy(video_path, temp_dir)
      else:
        temp_video_path = video_path

      edl_file = detect_commercials(temp_dir, temp_video_path, video_name)

    except Exception, e:
      logging.error('Something went wrong during comskip analysis: %s' % e)
      raise

    remove_commercials(temp_dir, temp_video_path, edl_file, video_basename)
    logging.info('Sanity checking our work...')
    try:
      input_size = os.path.getsize(video_path)
      output_size = os.path.getsize(os.path.join(temp_dir, video_basename))
      if input_size and 1.01 > float(output_size) / float(input_size) > 0.99:
        logging.info('Output file size was too similar (doesn\'t look like we did much); we won\'t replace the original: %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size)))
        return
      elif input_size and 1.1 > float(output_size) / float(input_size) > 0.5:
        logging.info('Output file size looked sane, we\'ll replace the original: %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size)))
        logging.info('Copying the output file into place: %s -> %s' % (video_basename, original_video_dir))
        shutil.copy(os.path.join(temp_dir, video_basename), original_video_dir)
        return
      else:
        logging.info('Output file size looked wonky (too big or too small); we won\'t replace the original: %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size)))
        raise Exception('Wonky size')
    except Exception, e:
      logging.error('Something went wrong during sanity check: %s' % e)
      raise

if __name__ == '__main__':
    main()
