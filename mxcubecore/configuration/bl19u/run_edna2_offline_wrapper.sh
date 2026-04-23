#!/bin/bash
# ==============================================================================
# BL19U1 - 极简自动化流水线 Wrapper
# ==============================================================================

LOCAL_JSON="$1"
REMOTE_HOST="demo@10.30.61.207"
REMOTE_JSON="/tmp/$(basename "$LOCAL_JSON")"

# 记录开始时间
echo "--- Offline Processing Triggered: $(date) ---" >> /tmp/edna_offline.log

# 1. 传输 JSON 参数到远程
scp -q "$LOCAL_JSON" "${REMOTE_HOST}:${REMOTE_JSON}"

# 2. 调用远程统一入口 (该脚本内嵌了 Characterisation + XDS + Upload 全流程)
ssh "$REMOTE_HOST" << EOF >> /tmp/edna_offline.log 2>&1
    source /home/demo/anaconda3/etc/profile.d/conda.sh
    conda activate edna2
    export EDNA2_SITE=bl19u1lab
    export PATH=/home/demo/XDS:\$PATH

    echo "Running Unified Pipeline for: $REMOTE_JSON"
    
    # 直接运行你刚才测试通的 run_xds_pipeline.py 脚本
    # 确保该脚本已经部署在远端的 /opt/edna2/ 目录下
    python /opt/edna2/run_xds_pipeline.py "$REMOTE_JSON"
EOF

echo "--- Offline Processing Finished ---" >> /tmp/edna_offline.log