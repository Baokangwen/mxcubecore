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
        参考 ExecDozor.generateCommands 生成配置
        """
        # --- 获取参数 ---
        try:
            dist = self.detector_hwobj.get_distance()
            pixel_x, pixel_y = self.detector_hwobj.get_pixel_size()
            beam_x, beam_y = self.detector_hwobj.get_beam_position()
            wave = HWR.beamline.energy.get_wavelength()
            det_type = self.detector_hwobj.get_type() # 如果有的话
        except:
            logging.getLogger("HWR").warning("SimpleDozor: Using default detector params")
            dist = 345.11
            pixel_x = pixel_y = 0.172
            beam_x = 1229
            beam_y = 1270
            wave = 0.97861
            det_type = "unknown"

        run_num = self.params_dict["run_number"]
        mxcube_template = self.params_dict["template"]
        
        # --- 路径模板转换逻辑 (保留之前的稳健逻辑) ---
        try:
            temp_path_str = mxcube_template % (run_num, 0)
        except TypeError:
            temp_path_str = mxcube_template % (0)

        precision = 4
        if "%05d" in mxcube_template: precision = 5
        elif "%06d" in mxcube_template: precision = 6
        elif "%03d" in mxcube_template: precision = 3
        
        wildcards = "?" * precision
        
        # HDF5 特殊处理 (参考 EDNA)
        if mxcube_template.endswith(".h5"):
            # EDNA 逻辑：如果 HDF5，模板通常是 master 文件或 data 文件
            # 这里简化处理，依然使用 ???? 替换数字
            pass 

        base_part, ext_part = os.path.splitext(temp_path_str)
        base_part_trimmed = base_part[:-precision]
        dozor_template = f"{base_part_trimmed}{wildcards}{ext_part}"
        
        # 获取对应库文件
        library = self._get_dozor_library(dozor_template)

        # --- 写入文件 (格式参考 ExecDozor) ---
        with open(processing_input_filename, 'w') as f:
            f.write("!\n")
            # f.write(f"detector {det_type}\n") # 可选
            if library:
                f.write(f"library {library}\n")
            
            # 探测器尺寸 (参考 EDNA 的 IX_MIN/MAX 常量逻辑)
            # 这里我们直接用光心反推，或者你可以在 XML 里配置 ix_max
            nx = int(beam_x * 2) 
            ny = int(beam_y * 2)
            f.write(f"nx {nx}\n")
            f.write(f"ny {ny}\n")
            
            f.write(f"pixel {pixel_x}\n")
            f.write(f"exposure {self.params_dict.get('exp_time', 1.0):.3f}\n")
            f.write(f"spot_size 3\n")
            f.write(f"spot_level 5\n") # EDNA 默认是 6
            f.write(f"detector_distance {dist:.3f}\n")
            f.write(f"X-ray_wavelength {wave:.3f}\n")
            f.write("fraction_polarization 0.990\n")
            f.write("pixel_min 0\n")
            f.write("pixel_max 64000\n") # Pilatus 典型值
            
            # 坏点区域 (Bad Zona) - 参考 EDNA
            # 如果你有坏点，可以在这里硬编码或者从 XML 读
            # f.write("bad_zona 1 10 1 10\n") 
            
            f.write(f"orgx {beam_x:.1f}\n")
            f.write(f"orgy {beam_y:.1f}\n")
            f.write(f"oscillation_range {self.params_dict.get('osc_range', 0.1):.3f}\n")
            
            # 计算起始角度 (参考 ExecDozor)
            # overall_starting_angle = startingAngle - (first_image - 1) * osc_range
            # 注意：MXCuBE 的 osc_start 通常已经是当前采集的起始角了
            start_angle = self.params_dict.get('osc_start', 0.0)
            f.write(f"starting_angle {start_angle:.3f}\n")
            
            f.write(f"first_image_number {self.params_dict['first_image_num']}\n")
            f.write(f"number_images {self.params_dict['images_num']}\n")
            f.write(f"name_template_image {dozor_template}\n")
            f.write("end\n")

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