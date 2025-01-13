import argparse
from pathlib import Path

import PlexComskip
from PlexComskip import ffmpeg_concat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('segment_list_file', type=Path)
    parser.add_argument('target_path', type=Path)
    args = parser.parse_args()
    nice_int = 20
    PlexComskip.NICE_ARGS = ['nice', '-n', str(nice_int)]
    PlexComskip.FFMPEG_PATH = '/usr/bin/ffmpeg'
    ffmpeg_concat(args.segment_list_file, args.target_path)


if __name__ == '__main__':
    main()
