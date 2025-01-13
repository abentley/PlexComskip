#!/bin/sh
ffprobe '/var/lib/jellyfin/data/livetv/recordings/Saturday Night Live/Saturday Night Live 2024_12_20_20_00_00 - A Saturday Night Live Christmas.ts' -of json -show_streams 2> foo|jq .streams[].duration
