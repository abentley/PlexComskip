#!/usr/bin/env python3

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil

import PlexComskip
from PlexComskip import remove_commercials


def main():
    nice_int = 20
    PlexComskip.NICE_ARGS = ['nice', '-n', str(nice_int)]
    PlexComskip.FFMPEG_PATH = '/usr/bin/ffmpeg'
    parser = argparse.ArgumentParser()
    parser.add_argument('video', type=Path)
    parser.add_argument('edl', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    video = args.video.resolve()
    edl = args.edl.resolve()
    with TemporaryDirectory() as temp_dir:
        os.chdir(temp_dir)
        output_video = remove_commercials(temp_dir, video, edl, video.name)
        shutil.move(output_video, output)


if __name__ == '__main__':
    main()
