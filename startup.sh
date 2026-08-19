#!/usr/bin/env sh

gunicorn -c conf/gunicorn.conf.py main:app
