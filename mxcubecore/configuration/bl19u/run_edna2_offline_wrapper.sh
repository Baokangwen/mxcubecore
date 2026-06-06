#!/bin/bash
# 运行在 MXCuBE 服务器上的离线处理智能路由脚本

WORKFLOW_TYPE="$1"   # 接收 "Mesh", "OSC", 或 "Helical"
SHARED_JSON="$2"     # 接收来自 Python 传入的共享路径 (例如 /ramdisk/opid3/.../offline_input.json)
REMOTE_HOST="demo@10.30.61.207"

# 记录日志 (这里你原本就写对了，用的是 >>)
echo "--- Offline Processing Triggered: $(date) ---" >> /tmp/edna_offline.log
echo "Workflow: $WORKFLOW_TYPE | JSON: $SHARED_JSON" >> /tmp/edna_offline.log

# 🚨 移除了 SCP，因为 SHARED_JSON 已经在共享盘 /ramdisk 上了，EDNA2 直接就能读！

if [ "$WORKFLOW_TYPE" == "Mesh" ]; then
    echo "--> Routing to DozorM" >> /tmp/edna_offline.log
    
    ssh "$REMOTE_HOST" << EOF >> /tmp/edna_offline.log 2>&1
        source /home/demo/anaconda3/etc/profile.d/conda.sh
        conda activate edna2
        export EDNA2_SITE=bl19u1lab

        # 🌟 修改 1：DozorM 改为追加 >>
        nohup python /opt/edna2/edna2_run_script/run_dozorm_pipeline.py "$SHARED_JSON" >> /tmp/dozorm_remote.log 2>&1 &
EOF

elif [ "$WORKFLOW_TYPE" == "OSC" ] || [ "$WORKFLOW_TYPE" == "Helical" ]; then
    echo "--> Routing to XDS" >> /tmp/edna_offline.log
    
    ssh "$REMOTE_HOST" << EOF >> /tmp/edna_offline.log 2>&1
        source /home/demo/anaconda3/etc/profile.d/conda.sh
        conda activate edna2
        export EDNA2_SITE=bl19u1lab
        export PATH=/home/demo/XDS:\$PATH

        # 🌟 修改 2：XDS 改为追加 >>
        nohup python /opt/edna2/edna2_run_script/run_xds_pipeline.py "$SHARED_JSON" >> /tmp/xds_remote.log 2>&1 &

        # 🌟 修改 3：DIALS 改为追加 >>
        nohup python /opt/edna2/edna2_run_script/run_dials_pipeline.py "$SHARED_JSON" >> /tmp/xia2_remote.log 2>&1 &

        # 🌟 修改 4：autoPROC 改为追加 >>
        nohup python /opt/edna2/edna2_run_script/run_autoproc_pipeline.py "$SHARED_JSON" >> /tmp/autoproc_remote.log 2>&1 &
EOF

else
    echo "--> Unknown Workflow Type: $WORKFLOW_TYPE. Aborting." >> /tmp/edna_offline.log
fi