#!/bin/bash
set -eux
GPU=$(nvidia-smi --list-gpus | wc -l)
mpirun -np $GPU python3 cifar10_1k.py $*