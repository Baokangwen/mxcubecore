import os
import subprocess
import gevent
import logging
import shlex
import time
from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractOnlineProcessing import AbstractOnlineProcessing

class SimpleDozor(AbstractOnlineProcessing):
    def __init__(self, name):
        AbstractOnlineProcessing.__init__(self, name)
        self.dozor_exec = None
        self.lib_cbf = None  # CBF 库
        self.lib_hdf5 = None # HDF5 库
        self.detector_hwobj = None
        
        # 数据容器初始化
        self.results_raw = {}
        self.results_aligned = {}
        self.results_clean = {} # 【必加】防止 AttributeError

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
        # --- 确保父目录存在 ---
        directory = os.path.dirname(processing_input_filename)
        if not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                logging.getLogger("HWR").info(f"SimpleDozor: Created directory {directory}")
            except OSError as e:
                logging.getLogger("HWR").error(f"SimpleDozor: Failed to create directory {directory}: {e}")
                raise e 

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
            
            # 如果小于 1，说明是米，乘以 1000 转成毫米
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

        # 1. 智能判断参数类型
        is_mesh = False
        
        if isinstance(data_collection, dict):
            logging.getLogger("HWR").info("SimpleDozor: Input is DICTIONARY (Custom Scan)")
            self.params_dict = data_collection
            is_mesh = True
            # 初始化 raw 容器
            self.results_raw = {
                "score": {},
                "spots_num": {},
                "spots_resolution": {}
            }
        else:
            logging.getLogger("HWR").info("SimpleDozor: Input is OBJECT (Standard Scan)")
            self.data_collection = data_collection
            self.prepare_processing()
            is_mesh = True 

        # 2. 生成配置文件
        try:
            process_dir = str(self.params_dict["process_directory"])
            dat_file = os.path.join(process_dir, "dozor_input.dat")
            
            self.create_processing_input_file(dat_file)
        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Failed to create input file: {e}")
            self.set_processing_status("Failed")
            return

        # 3. 构造命令
        cmd = [self.dozor_exec]
        if is_mesh:
            cmd.append('-mesh')
        else:
            cmd.append('-pall')

        cmd.append(dat_file)
        
        logging.getLogger("HWR").info(f"SimpleDozor: Executing CMD: {' '.join(cmd)}")

        # 4. 启动进程
        process = None 
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
            if process is not None:
                try:
                    process.kill()
                except:
                    pass

    def get_results(self):
        """
        前端拉取数据接口
        """
        if hasattr(self, "results_clean") and self.results_clean:
            return self.results_clean
        return {}

    def _get_rgb_from_score(self, score):
        """
        将分数转换为 RGB 颜色 [R, G, B]
        0   -> 蓝色 (0, 0, 255)
        中  -> 绿色 (0, 255, 0)
        高  -> 红色 (255, 0, 0)
        """
        if score <= 0: return [0, 0, 255] # 0分或负分显示蓝色
        
        # 设定一个合理的最大值阈值，例如 50 (根据实际晶体质量调整)
        # 如果明天带光测试，可以把这里改成 50.0 或 100.0
        max_score = 50.0 
        normalized = min(max(score, 0), max_score) / max_score
        
        # 简易热力图配色：蓝 -> 绿 -> 红
        if normalized < 0.5:
            # Blue to Green
            r = 0
            g = int(255 * (normalized * 2))
            b = int(255 * (1 - normalized * 2))
        else:
            # Green to Red
            r = int(255 * ((normalized - 0.5) * 2))
            g = int(255 * (1 - (normalized - 0.5) * 2))
            b = 0
            
        return [r, g, b]

    def _calc_screen_coords(self, relative_index):
        """
        计算屏幕坐标 (用于点击移动)
        """
        try:
            diff = HWR.beamline.diffractometer
            beam = HWR.beamline.beam
            collect = HWR.beamline.collect

            osc_seq = collect.current_dc_parameters["oscillation_sequence"][0]
            mesh_range = osc_seq.get("mesh_range") 
            num_lines = osc_seq.get("number_of_lines") 
            total_images = osc_seq.get("number_of_images") 
            
            if not mesh_range or not num_lines or not diff:
                return 0.0, 0.0

            px_per_mm_y, px_per_mm_z = diff.getCalibrationData(diff.zoomMotor.get_value())
            beam_x, beam_y = beam.get_beam_position_on_screen()

            num_cols = num_lines
            num_rows = int(total_images / num_cols)
            if num_rows == 0: num_rows = 1
            
            row = int(relative_index / num_cols)
            col = int(relative_index % num_cols)

            width_mm = mesh_range[0] / 1000.0
            height_mm = mesh_range[1] / 1000.0
            
            step_w_mm = width_mm / num_cols
            step_h_mm = height_mm / num_rows

            start_offset_w = -width_mm / 2.0 + step_w_mm / 2.0
            start_offset_h = -height_mm / 2.0 + step_h_mm / 2.0
            
            delta_w_mm = start_offset_w + (col * step_w_mm)
            delta_h_mm = start_offset_h + (row * step_h_mm)

            final_x = beam_x + (delta_w_mm * px_per_mm_y)
            final_y = beam_y + (delta_h_mm * px_per_mm_z)

            return float(final_x), float(final_y)

        except Exception as e:
            logging.getLogger("HWR").error(f"Calc Coords Error: {e}")
            return 0.0, 0.0

    def align_processing_results(self, start_index, end_index):
        """
        【前端适配版】构造 DrawGridPlugin.js 数据格式
        { 'heatmap': { 1: [Score, [R,G,B]], ... } }
        """
        # 安全初始化
        if "results_clean" not in self.__dict__ or self.results_clean is None:
            self.results_clean = {}
        if "results_aligned" not in self.__dict__ or self.results_aligned is None:
            self.results_aligned = {}
        
        self.results_clean.setdefault("heatmap", {})
        
        for i in range(start_index, end_index + 1):
            raw_score = self.results_raw.get("score", {}).get(i, 0.0)
            
            # --- 恢复真实分数 ---
            display_score = raw_score 
            
            # 计算 RGB
            rgb_color = self._get_rgb_from_score(display_score)
            
            # 计算坐标
            real_x, real_y = self._calc_screen_coords(i)

            # Web Key (1-based index)
            web_key = i + 1
            
            # 数据包: [Score, [R, G, B]]
            data_packet = [display_score, rgb_color]
            
            # 填入 results_clean (前端看这个)
            self.results_clean["heatmap"][web_key] = data_packet
            
            # 填入 results_aligned (兼容性)
            self.results_aligned.setdefault("score", {})[i] = display_score
            self.results_aligned.setdefault("x", {})[i] = real_x
            self.results_aligned.setdefault("y", {})[i] = real_y

            # 日志 (只打第一条，避免刷屏)
            if i == start_index:
                logging.getLogger("HWR").info(f"👉 WebPacket[{web_key}]: {data_packet}")

    def _monitor_output(self, process):
        """
        【完整流程监控】
        1. 提取 Grid 参数 (含 runId 和 比例尺)
        2. 发送 newProcessingRun
        3. 实时解析并更新 heatmap
        4. 结束时发送 processingFinished
        """
        logging.getLogger("HWR").info("SimpleDozor: Monitoring output...")

        # 1. 初始信号构建
        try:
            dc_params = HWR.beamline.collect.current_dc_parameters
            osc_seq = dc_params["oscillation_sequence"][0]
            run_number = dc_params.get("fileinfo", {}).get("run_number", 1)
            
            num_cols = osc_seq.get("number_of_lines", 1)
            total_images = osc_seq.get("number_of_images", 0)
            mesh_range = osc_seq.get("mesh_range", (0, 0)) 
            
            num_rows = int(total_images / num_cols) if num_cols > 0 else 1
            if num_rows == 0: num_rows = 1

            width_mm = mesh_range[0] / 1000.0
            height_mm = mesh_range[1] / 1000.0
            
            # 获取 Pixels per MM
            try:
                diff = HWR.beamline.diffractometer
                px_per_mm_y, px_per_mm_z = diff.getCalibrationData(diff.zoomMotor.get_value())
            except:
                px_per_mm_y, px_per_mm_z = 500.0, 500.0 # 默认值

            start_payload = {
                "id": run_number,               
                "runId": run_number,
                "numCols": num_cols,
                "numRows": num_rows,
                "width": width_mm,
                "height": height_mm,
                "cellWidth": (width_mm / num_cols) * 1000,   
                "cellHeight": (height_mm / num_rows) * 1000, 
                "pixelsPerMMX": px_per_mm_y, 
                "pixelsPerMMY": px_per_mm_z,
                "status": "started",
                "resultType": "heatmap",
                "algorithm": "dozor"
            }
            
            logging.getLogger("HWR").info(f"SimpleDozor: 🚀 Link Run {run_number}, Scale={px_per_mm_y:.1f}")
            self.emit("newProcessingRun", start_payload)
            self.emit("processingStarted", start_payload)
            gevent.sleep(0.5)
            
        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Payload error: {e}")

        # 2. 容器准备
        if self.results_raw is None: self.results_raw = {}
        if "results_clean" not in self.__dict__ or self.results_clean is None:
            self.results_clean = {}
        self.results_clean.setdefault("heatmap", {})

        # 3. 循环解析
        try:
            for line in process.stdout:
                if "|" in line and "image" not in line and "SPOTS" not in line:
                    try:
                        clean_line = line.replace("|", " ")
                        listLine = shlex.split(clean_line)
                        if len(listLine) >= 3 and listLine[0].isdigit():
                            img_num = int(listLine[0])
                            first_img = self.params_dict.get("first_image_num", 1)
                            relative_index = img_num - first_img
                            total_images = self.params_dict.get("images_num", 0)

                            if 0 <= relative_index < total_images:
                                spots = int(listLine[1])
                                score = float(listLine[2]) if len(listLine) > 2 else 0.0
                                resolution = float(listLine[3]) if len(listLine) > 3 else 0.0
                                
                                self.results_raw.setdefault("score", {})[relative_index] = score
                                self.results_raw.setdefault("spots_num", {})[relative_index] = spots
                                self.results_raw.setdefault("spots_resolution", {})[relative_index] = resolution
                                
                                self.align_processing_results(relative_index, relative_index)
                                
                                # 发送更新 (带 runId)
                                update_payload = self.results_clean.copy()
                                update_payload['id'] = run_number
                                self.emit("processingResultsUpdate", (False, update_payload))
                                gevent.sleep(0.01) # 微小延时防止阻塞

                    except Exception:
                        pass
        except Exception as e:
            logging.getLogger("HWR").error(f"SimpleDozor: Monitor loop error: {e}")

        process.wait()
        
        # 4. 结束处理
        total_images = self.params_dict.get("images_num", 0)
        self.align_processing_results(0, total_images - 1)
        
        logging.getLogger("HWR").info("SimpleDozor: Process finished.")
        
        final_payload = self.results_clean.copy()
        final_payload['id'] = run_number
        
        self.emit("processingResultsUpdate", (True, final_payload))
        self.emit("processingFinished") # 无参数
        self.set_processing_status("Success")

    def set_processing_status(self, status):
        # 封装状态设置，兼容新旧接口
        if self.data_collection is not None and hasattr(self.data_collection, "set_online_processing_results"):
            AbstractOnlineProcessing.set_processing_status(self, status)
        else:
            logging.getLogger("HWR").info(f"SimpleDozor: Processing Status -> {status}")