import os
import subprocess
import gevent
import logging
from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractOnlineProcessing import AbstractOnlineProcessing

class SimpleDozor(AbstractOnlineProcessing):
    def __init__(self, name):
        AbstractOnlineProcessing.__init__(self, name)
        self.dozor_exec = None
        self.library_path = None
        self.detector_hwobj = None

    def init(self):
        AbstractOnlineProcessing.init(self)
        
        # 1. 获取 Dozor 可执行文件路径
        self.dozor_exec = self.getProperty("executable")
        if self.dozor_exec is None:
            self.dozor_exec = "/usr/local/bin/dozor"

        # 2. 获取读取图片的库文件路径 (必须配置)
        self.library_path = self.getProperty("library_path")
        if self.library_path is None:
            # 如果 XML 没配，这里给一个硬编码的默认值，防止报错
            # 请确保这个文件在服务器上真实存在
            self.library_path = "/home/dozor_test/dozor_example/xds-zcbf.so"

        self.detector_hwobj = self.getObjectByRole("detector")

    def create_processing_input_file(self, processing_input_filename):
        """
        生成 dozor.dat 配置文件
        逻辑：自动转换 MXCuBE 的路径模板为 Dozor 格式
        """
        # --- 获取探测器参数 ---
        try:
            dist = self.detector_hwobj.get_distance()
            pixel_x, pixel_y = self.detector_hwobj.get_pixel_size()
            beam_x, beam_y = self.detector_hwobj.get_beam_position()
            wave = HWR.beamline.energy.get_wavelength()
        except:
            # 如果获取失败，使用兜底默认值
            logging.getLogger("HWR").warning("SimpleDozor: Failed to get detector params, using defaults.")
            dist = 345.11
            pixel_x = pixel_y = 0.172
            beam_x = 1229
            beam_y = 1270
            wave = 0.97861

        # --- 核心逻辑：转换路径模板 ---
        # MXCuBE template: /data/user/sample_1_%04d.cbf
        # Dozor template:  /data/user/sample_1_????.cbf
        
        run_num = self.params_dict["run_number"]
        mxcube_template = self.params_dict["template"]
        
        # 1. 尝试填充 Run Number，把 Image Number 填为 0 占位
        try:
            # 假设模板有两个占位符 (RunNum, ImgNum)
            temp_path_str = mxcube_template % (run_num, 0)
        except TypeError:
            # 假设模板只有一个占位符 (ImgNum)
            temp_path_str = mxcube_template % (0)

        # 2. 计算精度 (即问号的数量)
        precision = 4 # 默认
        if "%05d" in mxcube_template: precision = 5
        elif "%06d" in mxcube_template: precision = 6
        elif "%03d" in mxcube_template: precision = 3
        
        wildcards = "?" * precision
        
        # 3. 替换末尾的 0000 为 ????
        # 分离目录+文件名 和 扩展名
        base_part, ext_part = os.path.splitext(temp_path_str)
        # 切掉末尾的 '0' (长度等于精度)
        base_part_trimmed = base_part[:-precision]
        
        # 拼接最终路径
        dozor_template = f"{base_part_trimmed}{wildcards}{ext_part}"
        
        logging.getLogger("HWR").info(f"SimpleDozor: Converted template to: {dozor_template}")

        # --- 写入文件 ---
        with open(processing_input_filename, 'w') as f:
            # 1. 库文件引用
            if self.library_path:
                f.write(f"library {self.library_path}\n")
            
            # 2. 探测器物理参数
            f.write("!\n! detector parameter\n! ==================\n")
            # 这里的 nx ny 使用光心*2 进行估算，或者你可以写死 2463/2527
            f.write(f"nx {int(beam_x * 2)}\n")
            f.write(f"ny {int(beam_y * 2)}\n") 
            f.write(f"pixel {pixel_x}\n")
            f.write("pixel_min 0\n")
            f.write("pixel_max 1273414\n")
            
            # 3. 光束中心
            f.write("!\n! beam position\n! ===============\n")
            f.write(f"orgx {beam_x}\n")
            f.write(f"orgy {beam_y}\n")
            
            # 4. 实验参数
            f.write("!\n! data collection parameters\n! ==========================\n")
            f.write(f"detector_distance {dist}\n")
            f.write(f"X-ray_wavelength {wave}\n")
            
            # 5. 图片定义 (引用刚才生成的绝对路径模板)
            f.write("!\n! images\n! =======\n")
            f.write(f"first_image_number {self.params_dict['first_image_num']}\n")
            f.write(f"number_images {self.params_dict['images_num']}\n")
            f.write(f"name_template_image {dozor_template}\n")
            
            # 6. 选项参数
            f.write("!\n! OPTIONS\n! =======\n")
            f.write("spot_size 3\n")
            f.write("spot_level 5\n")
            f.write(f"exposure {self.params_dict.get('exp_time', 1.0)}\n")
            f.write(f"oscillation_range {self.params_dict.get('osc_range', 0.1)}\n")
            f.write(f"starting_angle {self.params_dict.get('osc_start', 0.0)}\n")
            
            f.write("!\nend\n")

    def run_processing(self, data_collection):
        """
        启动 Dozor 进程
        """
        self.data_collection = data_collection
        # 准备参数字典和目录
        self.prepare_processing()

        # 定义 dat 文件路径
        dat_file = os.path.join(self.params_dict["process_directory"], "dozor_input.dat")
        # 生成 dat 文件
        self.create_processing_input_file(dat_file)

        # 构造命令: dozor dozor_input.dat
        cmd = [self.dozor_exec, dat_file]
        
        logging.getLogger("HWR").info(f"SimpleDozor: Running command: {' '.join(cmd)}")

        try:
            self.started = True
            # 启动子进程
            # bufsize=1 意味着行缓冲，确保能实时读到日志
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # 把错误也输出到 stdout，防止遗漏
                cwd=self.params_dict["process_directory"],
                universal_newlines=True,
                bufsize=1
            )
            
            # 使用 Gevent 协程异步监听输出，不阻塞主界面
            gevent.spawn(self._monitor_output, process)

        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Start failed: {e}")
            self.set_processing_status("Failed")

    def _monitor_output(self, process):
        """
        解析 Dozor 2.3.9 的表格形式日志
        Format: 10001 |   910     101.08     1.68
        """
        logging.getLogger("HWR").info("SimpleDozor: Monitoring output started...")
        
        for line in process.stdout:
            # 过滤包含 | 的行，且排除表头
            if "|" in line and "image" not in line and "SPOTS" not in line:
                try:
                    # 分割数据
                    parts = line.split("|")
                    
                    # 获取图片号 (Image Number)
                    img_num_str = parts[0].strip()
                    if not img_num_str.isdigit():
                        continue
                    img_num = int(img_num_str)
                    
                    # 获取右侧数据 (Spots, Score, Resolution)
                    data_parts = parts[1].split()
                    
                    spots = int(data_parts[0])
                    score = float(data_parts[1])
                    resolution = float(data_parts[2])

                    # 映射到结果数组索引
                    relative_index = img_num - self.params_dict["first_image_num"]

                    # 安全检查：防止数组越界
                    if 0 <= relative_index < self.params_dict["images_num"]:
                        # 更新数据
                        self.results_raw["score"][relative_index] = score
                        self.results_raw["spots_num"][relative_index] = spots
                        self.results_raw["spots_resolution"][relative_index] = resolution
                        
                        # 触发对齐 (更新 Heatmap 视图)
                        self.align_processing_results(relative_index, relative_index)
                        
                        # 通知前端刷新
                        self.emit("processingResultsUpdate", False)
                        
                except Exception:
                    # 解析单行失败直接跳过，不要崩溃
                    pass
        
        # 等待进程彻底结束
        process.wait()
        logging.getLogger("HWR").info("SimpleDozor: Process finished.")
        self.set_processing_status("Success")