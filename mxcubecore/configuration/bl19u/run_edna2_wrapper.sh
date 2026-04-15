#!/bin/bash
# 接收 MXCuBE 传来的参数
TASK_NAME=$1
IN_JSON_FILE=$2
PROCESS_DIR=$3

echo "Starting EDNA2 Task: $TASK_NAME"
echo "Input File: $IN_JSON_FILE"
echo "Process Dir: $PROCESS_DIR"

# 1. 确保处理目录存在并进入
mkdir -p "$PROCESS_DIR"
cd "$PROCESS_DIR"

# 2. 直接使用 conda 环境内的 Python 绝对路径启动 EDNA2！
# 这样系统会自动带上 edna2 环境的所有依赖，无需 activate
/home/demo/anaconda3/envs/edna2/bin/python /opt/edna2/bin/run_edna2.py \
    --taskName "$TASK_NAME" \
    --inDataFile "$IN_JSON_FILE" \
    --outDataFile "$PROCESS_DIR/edna2_result.json" \
    --info