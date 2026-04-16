import os
import json
import logging
import subprocess
from mxcubecore.BaseHardwareObjects import HardwareObject

__credits__ = ["SSRF BL19U1"]
__category__ = "General"

class OfflineProcessing(HardwareObject):
    """
    SSRF 离线数据处理硬件对象
    拦截数据收集结束事件，生成 EDNA2 所需的 JSON，并调用远程脚本
    """

    def __init__(self, name):
        HardwareObject.__init__(self, name)
        self.wrapper_script = None
        self.edna_plugin = "Characterisation"

    def init(self):
        """初始化：从 XML 配置文件加载路径和插件设置"""
        self.wrapper_script = self.get_property("processing_command")
        self.edna_plugin = self.get_property("edna_plugin", "Characterisation")
        
        if not self.wrapper_script or not os.path.exists(self.wrapper_script):
            logging.error(f"OfflineProcessing: 脚本路径无效: {self.wrapper_script}")

    def execute_autoprocessing(self, process_event, params_dict, frame_number=None):
        """
        MXCuBE3 标准入口函数
        :param process_event: 事件类型 (before, image, after)
        :param params_dict: 包含波长、距离、路径等所有元数据的字典
        """
        # 我们只在收集任务彻底结束后 (after) 触发离线处理
        if process_event == "after":
            logging.info("SSRF OfflineProcessing: 检测到收集结束，准备启动 EDNA2...")
            self.run_edna2_offline(params_dict)

    def run_edna2_offline(self, params):
        try:
            import time
            import os
            import json
            import subprocess
            import logging
            
            # 1. 安全获取 ID 和基本信息
            dc_id = params.get("collection_id") or time.strftime("%H%M%S")
            file_info = params.get("fileinfo", {})
            
            osc_seq_list = params.get("oscillation_sequence", [])
            osc_seq = osc_seq_list[0] if len(osc_seq_list) > 0 else {}
            sample_ref = params.get("sample_reference", {})

            # 2. 安全获取物理参数
            exp_time = osc_seq.get("exposure_time")
            exp_time = float(exp_time) if exp_time is not None else 1.0

            wavelength = params.get("wavelength")
            wavelength = float(wavelength) if wavelength is not None else 0.9785

            # 3. 智能推算图片的绝对路径 (imagePath)
            original_dir = file_info.get("directory", "")
            if "RAW_DATA" in original_dir:
                raw_dir = "/ramdisk" + original_dir.split("RAW_DATA")[1]
            else:
                raw_dir = original_dir.replace("/home/bl19u1/inhouse/idtest0", "/ramdisk")
            raw_dir = raw_dir.replace("//", "/")

            prefix = file_info.get("prefix", "unknown")
            run_number = int(file_info.get("run_number", 1))
            num_images = int(osc_seq.get("number_of_images", 10))
            
            start_img = int(osc_seq.get("start_image_number", 1))
            real_start = 10000 + start_img if start_img < 10000 else start_img

            image_paths = []
            for i in range(real_start, real_start + num_images):
                img_name = f"{prefix}_{run_number}_{i}.cbf"
                image_paths.append(os.path.join(raw_dir, img_name))

            # 4. 组装符合 EDNA2 要求的 JSON 结构 (已加入 diffractionPlan)
            edna_input = {
                "ispybDataCollectionId": dc_id,
                "imagePath": image_paths,
                "dataCollection": {
                    "imageDirectory": file_info.get("directory"),
                    "imagePrefix": prefix,
                    "imageNumber": 1,
                    "imageSuffix": "cbf",
                    "startAngle": float(osc_seq.get("start", 0.0)),
                    "oscillationWidth": float(osc_seq.get("range", 1.0)),
                    "numberImages": num_images
                },
                "diffractionPlan": {
                    "aimedCompleteness": 0.99,
                    "aimedResolution": 2.0,
                    "complexity": "none"
                },
                "experimentalCondition": {
                    "beam": {
                        "wavelength": wavelength,
                        "exposureTime": exp_time,
                        "transmission": float(params.get("transmission", 1.0))
                    },
                    "detector": {
                        "distance": float(params.get("detectorDistance", 509.0)),
                        "beamPositionX": float(params.get("xBeam", 127.0)),
                        "beamPositionY": float(params.get("yBeam", 144.0))
                    },
                    "goniostat": {
                        "maxOscillationSpeed": 10.0,
                        "minOscillationWidth": 0.05,
                        "minExposureTime": 0.04
                    }
                },
                "sample": {
                    "priorInfo": {
                        "spacegroup": sample_ref.get("spacegroup"),
                        "cell": sample_ref.get("cell")
                    }
                }
            }

            # 5. 写入文件并调用 wrapper 脚本 (将目标目录 raw_dir 传过去)
            local_json_path = f"/tmp/edna_offline_input_{dc_id}.json"
            with open(local_json_path, 'w') as f:
                json.dump(edna_input, f, indent=4)
            
            logging.info(f"SSRF OfflineProcessing: JSON 已生成: {local_json_path}")

            if hasattr(self, 'wrapper_script') and self.wrapper_script:
                subprocess.Popen(
                    [self.wrapper_script, local_json_path, getattr(self, 'edna_plugin', 'Characterisation'), raw_dir],
                    shell=False,
                    stdout=None,
                    stderr=None,
                    close_fds=True
                )
                logging.info(f"SSRF OfflineProcessing: 远程脚本已启动，结果将生成至 {raw_dir}")

        except Exception as e:
            import logging
            logging.error(f"SSRF OfflineProcessing: 启动失败! 错误原因: {str(e)}")