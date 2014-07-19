#!/bin/bash

SRC_DIR=proto
DEST_DIR=python/mc/proto

mkdir -p $DEST_DIR;
touch $DEST_DIR/__init__.py

protoc -I=$SRC_DIR --python_out=$DEST_DIR $SRC_DIR/*.proto
