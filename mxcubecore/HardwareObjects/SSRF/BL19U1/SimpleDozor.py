import os
import subprocess
import gevent
import logging
import shlex
from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractOnlineProcessing import AbstractOnlineProcessing

class SimpleDozor(AbstractOnlineProcessing):
    def __init__(self, name):
        AbstractOnlineProcessing.__init__(self, name)
        self.dozor_exec = None
        self.lib_cbf = None  # CBF 库
        self.lib_hdf5 = None # HDF5 库
        self.detector_hwobj = None

    def init(self):
        AbstractOnlineProcessing.init(self)
        
        # 1. 获取可执行文件
        self.dozor_exec = self.getProperty("executable")
        if self.dozor_exec is None:
            self.dozor_exec = "/usr/local/bin/dozor"

        # 2. 获取库文件路径 (支持配置两种库)
        # 参考 EDNA 逻辑，根据文件后缀自动切换
        self.lib_cbf = self.getProperty("library_cbf")
        self.lib_hdf5 = self.getProperty("library_hdf5")
        
        # 兜底默认值 (为了兼容你之前的测试环境)
        if self.lib_cbf is None:
            self.lib_cbf = "/home/dozor_test/dozor_example/xds-zcbf.so"
            
        self.detector_hwobj = self.getObjectByRole("detector")

    def _get_dozor_library(self, template):
        """
        参考 EDNA 的 getLibrary 逻辑，根据文件类型返回对应的库
        """
        if template.endswith(".h5") and self.lib_hdf5:
            return self.lib_hdf5
        return self.lib_cbf

    def create_processing_input_file(self, processing_input_filename):
        """
        生成 Dozor 配置文件 (dozor_input.dat)
        针对 LNLSPilatusDet.py 进行了单位适配 (米 -> 毫米)
        """
        # 1. 获取探测器对象
        # 为了保险，直接从 HWR 全局获取，绕过 role 查找可能存在的空指针
        try:
            det = HWR.beamline.detector
        except:
            det = self.getObjectByRole("detector")

        # 2. 获取参数 (增加单位自动修正逻辑)
        try:
            # --- 距离 (Distance) ---
            # 优先尝试 get_detector_distance (你的脚本里是这个名字)
            if hasattr(det, "get_detector_distance"):
                dist = det.get_detector_distance()
            else:
                dist = det.get_distance()
            
            # --- 像素大小 (Pixel Size) ---
            # 你的脚本返回的是 0.000172 (米)，Dozor 需要 0.172 (毫米)
            pixel_x = det.get_pixel_size_x()
            pixel_y = det.get_pixel_size_y()
            
            # 【关键修正】如果小于 1，说明是米，乘以 1000 转成毫米
            if pixel_x < 1.0: pixel_x *= 1000.0
            if pixel_y < 1.0: pixel_y *= 1000.0

            # --- 光心 (Beam Center) ---
            # 你的脚本里 get_beam_position 返回的是像素坐标 (x, y)
            beam_x, beam_y = det.get_beam_position()
            
            # --- 波长 (Wavelength) ---
            wave = HWR.beamline.energy.get_wavelength()
            
        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Error reading detector params: {e}")
            # 兜底默认值 (万一硬件对象没连上)
            dist = 345.11
            pixel_x = pixel_y = 0.172
            beam_x = 1229
            beam_y = 1270
            wave = 0.979

        # 3. 获取扫描参数
        # 优先从 params_dict (BL19U1Collect 传过来的) 里拿，拿不到再用默认值
        first_image_num = self.params_dict.get('first_image_num', 1)
        images_num = self.params_dict.get('images_num', 1)
        template = self.params_dict.get('template', 'unknown_template')
        
        # 曝光时间 & 振荡角度
        exp_time = self.params_dict.get('exp_time', 1.0)
        osc_range = self.params_dict.get('osc_range', 0.0) # Raster Scan 通常是 0
        start_angle = self.params_dict.get('osc_start', 0.0)

        # 4. 获取库文件 (CBF vs HDF5)
        library = self._get_dozor_library(template)

        # 5. 写入文件
        with open(processing_input_filename, 'w') as f:
            f.write("!\n")
            if library:
                f.write(f"library {library}\n")
            
            # 探测器尺寸 (根据光心反推大概尺寸，或者写死)
            # Pilatus 6M 约为 2463 x 2527
            f.write(f"nx 2463\n") 
            f.write(f"ny 2527\n")
            
            f.write(f"pixel {pixel_x:.4f}\n") # 确保写入的是 0.172
            f.write(f"exposure {exp_time:.3f}\n")
            f.write(f"spot_size 3\n")
            f.write(f"spot_level 5\n")
            f.write(f"detector_distance {dist:.3f}\n")
            f.write(f"X-ray_wavelength {wave:.3f}\n")
            f.write("fraction_polarization 0.990\n")
            f.write("pixel_min 0\n")
            f.write("pixel_max 64000\n")
            
            f.write(f"orgx {beam_x:.1f}\n")
            f.write(f"orgy {beam_y:.1f}\n")
            f.write(f"oscillation_range {osc_range:.3f}\n")
            f.write(f"starting_angle {start_angle:.3f}\n")
            
            f.write(f"first_image_number {first_image_num}\n")
            f.write(f"number_images {images_num}\n")
            f.write(f"name_template_image {template}\n")
            f.write("end\n")
            
        logging.getLogger("HWR").info(f"SimpleDozor: Input file created. Pixel: {pixel_x:.4f}mm, Dist: {dist:.1f}mm")
        
    def run_processing(self, data_collection):
        """
        【万能版】run_processing
        既支持 MeshScan 传过来的 DataCollection 对象
        也支持 BL19U1Collect 传过来的 参数字典 (Dict)
        """
        logging.getLogger("HWR").info("SimpleDozor: run_processing called")

        # =================================================================
        # 1. 智能判断参数类型
        # =================================================================
        is_mesh = False
        
        if isinstance(data_collection, dict):
            # >>> 情况 A：你从 BL19U1Collect 传过来的是字典 <<<
            logging.getLogger("HWR").info("SimpleDozor: Input is DICTIONARY (Custom Scan)")
            self.params_dict = data_collection
            # 既然是 Raster Scan，肯定是 Mesh 模式
            is_mesh = True
            
            # 确保目录存在
            if not os.path.exists(self.params_dict["process_directory"]):
                try:
                    os.makedirs(self.params_dict["process_directory"])
                except:
                    pass
        else:
            # >>> 情况 B：标准的 MeshScan 传过来的是对象 <<<
            logging.getLogger("HWR").info("SimpleDozor: Input is OBJECT (Standard Scan)")
            self.data_collection = data_collection
            self.prepare_processing() # 基类方法，把对象转为 self.params_dict
            
            # 判断是否需要 mesh 模式 (通常都需要)
            is_mesh = True 

        # =================================================================
        # 2. 生成配置文件
        # =================================================================
        dat_file = os.path.join(self.params_dict["process_directory"], "dozor_input.dat")
        try:
            self.create_processing_input_file(dat_file)
        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Failed to create input file: {e}")
            self.set_processing_status("Failed")
            return

        # =================================================================
        # 3. 构造命令
        # =================================================================
        # 这里的 self.dozor_exec 是在 init() 里获取的 /usr/local/bin/dozor
        cmd = [self.dozor_exec]
        
        if is_mesh:
            cmd.append('-mesh') # Raster Scan 必须加这个
        else:
            cmd.append('-pall')

        cmd.append(dat_file)
        
        logging.getLogger("HWR").info(f"SimpleDozor: Executing CMD: {' '.join(cmd)}")

        # =================================================================
        # 4. 启动进程
        # =================================================================
        try:
            self.started = True
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.params_dict["process_directory"],
                universal_newlines=True,
                bufsize=1
            )
            # 启动监听线程
            gevent.spawn(self._monitor_output, process)
            
        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Process start failed: {e}")
            self.set_processing_status("Failed")

    def _monitor_output(self, process):
        """
        移植自 ExecDozor.parseOutput
        """
        logging.getLogger("HWR").info("SimpleDozor: Monitoring output...")
        
        for line in process.stdout:
            # EDNA 逻辑：先去掉 '|' 然后用 shlex 分割
            # 原始行：10001 | 910 101.08 ...
            if "|" in line and "image" not in line and "SPOTS" not in line:
                try:
                    # 使用 shlex.split 处理可能的复杂空格
                    clean_line = line.replace("|", " ")
                    listLine = shlex.split(clean_line)
                    
                    if len(listLine) > 0 and listLine[0].isdigit():
                        img_num = int(listLine[0])
                        
                        # 映射索引
                        relative_index = img_num - self.params_dict["first_image_num"]
                        
                        if 0 <= relative_index < self.params_dict["images_num"]:
                            # --- 核心解析 (参考 ExecDozor 索引) ---
                            # listLine[1]: Spots Num
                            # listLine[2]: Int Aver
                            # listLine[4]: Resolution
                            # listLine[8]: Main Score (DoDozorScore)
                            # listLine[10]: Visible Resolution
                            
                            spots = int(listLine[1])
                            
                            # 注意：EDNA 代码里做了负数判断等逻辑，这里简化处理
                            # 索引 8 是 Main Score
                            if len(listLine) > 8:
                                score = float(listLine[8])
                            else:
                                score = 0.0
                                
                            # 索引 4 是 Resolution
                            if len(listLine) > 4:
                                resolution = float(listLine[4])
                            else:
                                resolution = 0.0

                            # 更新数据
                            self.results_raw["score"][relative_index] = score
                            self.results_raw["spots_num"][relative_index] = spots
                            self.results_raw["spots_resolution"][relative_index] = resolution
                            
                            self.align_processing_results(relative_index, relative_index)
                            self.emit("processingResultsUpdate", False)
                except Exception as e:
                    # logging.getLogger("HWR").warning(f"Parse error: {e}")
                    pass

    def set_processing_status(self, status):
        if self.data_collection is not None and hasattr(self.data_collection, "set_online_processing_results"):
            AbstractOnlineProcessing.set_processing_status(self, status)
        else:
            logging.getLogger("HWR").info(f"SimpleDozor: Processing finished ({status})")   

        process.wait()
        self.set_processing_status("Success")