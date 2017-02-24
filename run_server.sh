#!/bin/bash

gunicorn -b 0.0.0.0:5000 -k flask_sockets.worker server:app
