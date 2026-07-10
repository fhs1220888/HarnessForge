#!/usr/bin/env bash
set -e
test -f logs/app.log
test -f logs/error.log
test -f data/metrics.csv
test -f readme.txt                 # must not be moved
test ! -f app.log && test ! -f error.log && test ! -f metrics.csv
echo OK
