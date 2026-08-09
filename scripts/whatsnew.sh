#!/bin/sh

find /mnt/edvault/storage/media/ -maxdepth 3 -type f -mtime -7 -print0 | xargs -0 ls -1 | cut -d '/' -f7 | sort | uniq



