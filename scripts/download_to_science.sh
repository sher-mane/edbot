#!/bin/sh

yt-dlp -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" -P /mnt/edvault/storage/media/topics/science $1

