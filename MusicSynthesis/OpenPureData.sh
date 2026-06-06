#!/bin/bash
sudo pkill puredata
systemctl --user stop pipewire wireplumber pipewire.socket

fuser /dev/snd/*
puredata &
