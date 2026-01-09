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
        self.lib_cbf = self.getProperty("library_cbf")
        self.lib_hdf5 = self.getProperty("library_hdf5")
        
        # 兜底默认值
        if self.lib_cbf is None:
            self.lib_cbf = "/home/dozor_test/dozor_example/xds-zcbf.so"
            
        self.detector_hwobj = self.getObjectByRole("detector")

    def _get_dozor_library(self, template):
        """
        根据文件类型返回对应的库
        """
        if template.endswith(".h5") and self.lib_hdf5:
            return self.lib_hdf5
        return self.lib_cbf

    def create_processing_input_file(self, processing_input_filename):
        """
        生成 Dozor 配置文件 (dozor_input.dat)
        """
        # --- FIX START: 确保父目录存在 ---
        # 获取要写入文件的文件夹路径
        directory = os.path.dirname(processing_input_filename)
        if not os.path.exists(directory):
            try:
                # 递归创建目录 (类似 mkdir -p)
                os.makedirs(directory, exist_ok=True)
                logging.getLogger("HWR").info(f"SimpleDozor: Created directory {directory}")
            except OSError as e:
                logging.getLogger("HWR").error(f"SimpleDozor: Failed to create directory {directory}: {e}")
                raise e # 抛出异常终止后续操作
        # --- FIX END ---

        # 1. 获取探测器对象
        try:
            det = HWR.beamline.detector
        except:
            det = self.getObjectByRole("detector")

        # 2. 获取参数 (增加单位自动修正逻辑)
        try:
            # --- 距离 (Distance) ---
            if hasattr(det, "get_detector_distance"):
                dist = det.get_detector_distance()
            else:
                dist = det.get_distance()
            
            if dist > 10000:
                dist = dist / 1000.0
            
            # --- 像素大小 (Pixel Size) ---
            pixel_x = det.get_pixel_size_x()
            pixel_y = det.get_pixel_size_y()
            
            # 【关键修正】如果小于 1，说明是米，乘以 1000 转成毫米
            if pixel_x < 1.0: pixel_x *= 1000.0
            if pixel_y < 1.0: pixel_y *= 1000.0

            # --- 光心 (Beam Center) ---
            beam_x, beam_y = det.get_beam_position()
            
            # --- 波长 (Wavelength) ---
            wave = HWR.beamline.energy.get_wavelength()
            
        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Error reading detector params: {e}")
            # 兜底默认值
            dist = 345.11
            pixel_x = pixel_y = 0.172
            beam_x = 1229
            beam_y = 1270
            wave = 0.979

        # 3. 获取扫描参数
        first_image_num = self.params_dict.get('first_image_num', 1)
        images_num = self.params_dict.get('images_num', 1)
        template = self.params_dict.get('template', 'unknown_template')
        
        exp_time = self.params_dict.get('exp_time', 1.0)
        osc_range = self.params_dict.get('osc_range', 0.0)
        start_angle = self.params_dict.get('osc_start', 0.0)

        # 4. 获取库文件
        library = self._get_dozor_library(template)

        # 5. 写入文件
        with open(processing_input_filename, 'w') as f:
            f.write("!\n")
            if library:
                f.write(f"library {library}\n")
            
            # 探测器尺寸 (Pilatus 6M)
            f.write(f"nx 2463\n") 
            f.write(f"ny 2527\n")
            
            f.write(f"pixel {pixel_x:.4f}\n")
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
            
        logging.getLogger("HWR").info(f"SimpleDozor: Input file created at {processing_input_filename}")
        
    def run_processing(self, data_collection):
        """
        执行处理
        """
        logging.getLogger("HWR").info("SimpleDozor: run_processing called")

        # =================================================================
        # 1. 智能判断参数类型
        # =================================================================
        is_mesh = False
        
        if isinstance(data_collection, dict):
            logging.getLogger("HWR").info("SimpleDozor: Input is DICTIONARY (Custom Scan)")
            self.params_dict = data_collection
            is_mesh = True
        else:
            logging.getLogger("HWR").info("SimpleDozor: Input is OBJECT (Standard Scan)")
            self.data_collection = data_collection
            self.prepare_processing()
            is_mesh = True 

        # =================================================================
        # 2. 生成配置文件
        # =================================================================
        try:
            # 确保从字典里取出的路径是字符串
            process_dir = str(self.params_dict["process_directory"])
            dat_file = os.path.join(process_dir, "dozor_input.dat")
            
            self.create_processing_input_file(dat_file)
        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Failed to create input file: {e}")
            self.set_processing_status("Failed")
            return

        # =================================================================
        # 3. 构造命令
        # =================================================================
        cmd = [self.dozor_exec]
        
        if is_mesh:
            cmd.append('-mesh')
        else:
            cmd.append('-pall')

        cmd.append(dat_file)
        
        logging.getLogger("HWR").info(f"SimpleDozor: Executing CMD: {' '.join(cmd)}")

        # =================================================================
        # 4. 启动进程
        # =================================================================
        process = None # --- FIX: 初始化变量，防止 except 中引用报错 ---
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
            # --- FIX: 安全关闭 ---
            if process is not None:
                try:
                    process.kill()
                except:
                    pass

    def _monitor_output(self, process):
        """
        监控输出并在结束后更新状态
        """
        logging.getLogger("HWR").info("SimpleDozor: Monitoring output...")
        
        try:
            for line in process.stdout:
                # 原始行：10001 | 910 101.08 ...
                if "|" in line and "image" not in line and "SPOTS" not in line:
                    try:
                        clean_line = line.replace("|", " ")
                        listLine = shlex.split(clean_line)
                        
                        if len(listLine) > 0 and listLine[0].isdigit():
                            img_num = int(listLine[0])
                            
                            # 映射索引
                            relative_index = img_num - self.params_dict["first_image_num"]
                            
                            if 0 <= relative_index < self.params_dict["images_num"]:
                                spots = int(listLine[1])
                                score = float(listLine[8]) if len(listLine) > 8 else 0.0
                                resolution = float(listLine[4]) if len(listLine) > 4 else 0.0

                                # 更新数据
                                self.results_raw["score"][relative_index] = score
                                self.results_raw["spots_num"][relative_index] = spots
                                self.results_raw["spots_resolution"][relative_index] = resolution
                                
                                self.align_processing_results(relative_index, relative_index)
                                self.emit("processingResultsUpdate", False)
                    except Exception as e:
                        pass
        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Monitor loop error: {e}")

        # --- FIX: 进程结束后在这里更新状态 ---
        process.wait() # 等待进程彻底退出
        logging.getLogger("HWR").info("SimpleDozor: Process finished successfully.")
        self.set_processing_status("Success")

    def set_processing_status(self, status):
        # 封装状态设置，兼容新旧接口
        if self.data_collection is not None and hasattr(self.data_collection, "set_online_processing_results"):
            AbstractOnlineProcessing.set_processing_status(self, status)
        else:
            # 如果是纯字典模式，没有 data_collection 对象，仅打印日志
            logging.getLogger("HWR").info(f"SimpleDozor: Processing Status -> {status}")