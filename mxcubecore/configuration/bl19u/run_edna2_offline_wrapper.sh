#!/bin/bash
# 运行在 MXCuBE 服务器上的离线处理智能路由脚本

WORKFLOW_TYPE="$1"   # 接收 "Mesh", "OSC", 或 "Helical"
LOCAL_JSON="$2"      # 接收 JSON 文件路径
REMOTE_HOST="demo@10.30.61.207"
REMOTE_JSON="/tmp/$(basename "$LOCAL_JSON")"

# 记录开始时间与任务类型
echo "--- Offline Processing Triggered: $(date) ---" >> /tmp/edna_offline.log
echo "Workflow Type: $WORKFLOW_TYPE" >> /tmp/edna_offline.log
echo "JSON File: $LOCAL_JSON" >> /tmp/edna_offline.log

# 1. 传输 JSON 参数到远程
scp -q "$LOCAL_JSON" "${REMOTE_HOST}:${REMOTE_JSON}"

# 2. 路由分发 (DozorM 或 XDS)
if [ "$WORKFLOW_TYPE" == "Mesh" ]; then
    echo "--> Routing to DozorM (Mesh Scan Pipeline)" >> /tmp/edna_offline.log
    
    # EOF 前不要加锁进，严格按照格式
    ssh "$REMOTE_HOST" << EOF >> /tmp/edna_offline.log 2>&1
        source /home/demo/anaconda3/etc/profile.d/conda.sh
        conda activate edna2
        export EDNA2_SITE=bl19u1lab

        echo "Running DozorM Pipeline for: $REMOTE_JSON"
        # 使用 nohup 后台执行，让 SSH 连接瞬间释放
        nohup python /opt/edna2/edna2_run_script/run_dozorm_pipeline.py "$REMOTE_JSON" > /tmp/dozorm_remote.log 2>&1 &
EOF

elif [ "$WORKFLOW_TYPE" == "OSC" ] || [ "$WORKFLOW_TYPE" == "Helical" ]; then
    echo "--> Routing to XDS ($WORKFLOW_TYPE Pipeline)" >> /tmp/edna_offline.log
    
    ssh "$REMOTE_HOST" << EOF >> /tmp/edna_offline.log 2>&1
        source /home/demo/anaconda3/etc/profile.d/conda.sh
        conda activate edna2
        export EDNA2_SITE=bl19u1lab
        export PATH=/home/demo/XDS:\$PATH

        echo "Running XDS Pipeline for: $REMOTE_JSON"
        # 使用 nohup 后台执行
        nohup python /opt/edna2/edna2_run_script/run_xds_pipeline.py "$REMOTE_JSON" > /tmp/xds_remote.log 2>&1 &
EOF

else
    echo "--> Unknown Workflow Type: $WORKFLOW_TYPE. Aborting." >> /tmp/edna_offline.log
fi

echo "--- Offline Processing Dispatched ---" >> /tmp/edna_offline.log