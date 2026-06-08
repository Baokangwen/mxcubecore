#!/bin/bash
# 运行在 MXCuBE 服务器上的离线处理智能路由脚本

WORKFLOW_TYPE="$1"   # 接收 "Mesh", "OSC", 或 "Helical"
SHARED_JSON="$2"     # 接收来自 Python 传入的共享路径

# 🌟 核心修改：智能提取任务专属名称
# 用 basename 命令去掉路径前缀，去掉 .json 后缀
# 结果类似：offline_input_OSC_Sample-8-05_1_20260606_020848
JOB_NAME=$(basename "$SHARED_JSON" .json)

REMOTE_HOST="demo@10.30.61.207"

# 总控日志（记录谁在什么时候被触发了）保留在一个公共文件里，方便查看流量
echo "--- Offline Processing Triggered: $(date) ---" >> /tmp/edna_offline.log
echo "Workflow: $WORKFLOW_TYPE | Job: $JOB_NAME" >> /tmp/edna_offline.log

if [ "$WORKFLOW_TYPE" == "Mesh" ]; then
    echo "--> Routing to DozorM" >> /tmp/edna_offline.log
    
    ssh "$REMOTE_HOST" << EOF >> /tmp/edna_offline.log 2>&1
        source /home/demo/anaconda3/etc/profile.d/conda.sh
        conda activate edna2
        export EDNA2_SITE=bl19u1lab

        # 🎯 每个任务拥有专属日志文件
        nohup python /opt/edna2/edna2_run_script/run_dozorm_pipeline.py "$SHARED_JSON" >> /tmp/dozorm_${JOB_NAME}.log 2>&1 &
EOF

elif [ "$WORKFLOW_TYPE" == "OSC" ] || [ "$WORKFLOW_TYPE" == "Helical" ]; then
    echo "--> Routing to XDS" >> /tmp/edna_offline.log
    
    ssh "$REMOTE_HOST" << EOF >> /tmp/edna_offline.log 2>&1
        source /home/demo/anaconda3/etc/profile.d/conda.sh
        conda activate edna2
        export EDNA2_SITE=bl19u1lab
        export PATH=/home/demo/XDS:\$PATH

        # 🎯 为每个流程生成带样品名和时间戳的专属日志
        nohup python /opt/edna2/edna2_run_script/run_xds_pipeline.py "$SHARED_JSON" >> /tmp/xds_${JOB_NAME}.log 2>&1 &

        nohup python /opt/edna2/edna2_run_script/run_dials_pipeline.py "$SHARED_JSON" >> /tmp/xia2_${JOB_NAME}.log 2>&1 &

        nohup python /opt/edna2/edna2_run_script/run_autoproc_pipeline.py "$SHARED_JSON" >> /tmp/autoproc_${JOB_NAME}.log 2>&1 &
EOF

else
    echo "--> Unknown Workflow Type: $WORKFLOW_TYPE. Aborting." >> /tmp/edna_offline.log
fi