#!/bin/bash
LOCAL_JSON=$1
PLUGIN_NAME=${2:-"Characterisation"}
OUT_DIR=$3

REMOTE_HOST="demo@10.30.61.207"
REMOTE_TMP="/tmp/$(basename $LOCAL_JSON)"

echo "--- Offline Processing Started: $(date) ---" >> /tmp/edna_offline.log
echo "Local JSON: $LOCAL_JSON" >> /tmp/edna_offline.log

# 1. 传输 JSON 文件
scp -q $LOCAL_JSON ${REMOTE_HOST}:${REMOTE_TMP}

# 提取数据收集的名字，比如 a4，用来建文件夹
COLLECTION_NAME=$(basename $OUT_DIR)

# 2. 远程执行
ssh $REMOTE_HOST << EOF >> /tmp/edna_offline.log 2>&1
    source /home/demo/anaconda3/etc/profile.d/conda.sh
    conda activate edna2
    export EDNA2_SITE=bl19u1lab
    
    # 强制注入 XDS 路径
    export PATH=/home/demo/XDS:\$PATH
    
    # ==========================================
    # 退而求其次：在 demo 账号有绝对权限的 /tmp 下，
    # 专门为这次收集 (比如 a4) 建一个专属工作目录
    # ==========================================
    SAFE_OUT_DIR="/tmp/edna_results_\${COLLECTION_NAME}_$(date +%H%M%S)"
    mkdir -p "\$SAFE_OUT_DIR"
    cd "\$SAFE_OUT_DIR"
    
    echo "Executing EDNA2 Plugin: $PLUGIN_NAME in \$SAFE_OUT_DIR"
    
    python /opt/edna2/bin/run_edna2.py --taskName $PLUGIN_NAME --inDataFile $REMOTE_TMP
EOF

echo "--- Offline Processing Finished ---" >> /tmp/edna_offline.log