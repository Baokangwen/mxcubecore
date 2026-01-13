import gevent
from datetime import datetime
import logging
import traceback
import os
import csv
import re

from mxcubecore.HardwareObjects.abstract import AbstractSampleChanger
from mxcubecore.HardwareObjects.abstract.sample_changer import Container
from mxcubecore import HardwareRepository as HWR
from mxcubecore.queue_entry.base_queue_entry import CENTRING_METHOD


def if_running_sc(func):
    """
    装饰器函数，用于取样上样时，进行判断，如果机械手在运行，则不操作直接返回
    """
    def wrapper(self, sample, wait=False):
        if HWR.beamline.sample_changer_maintenance.running == 1:
            logging.getLogger("user_level_log").info(
                "机械手正在运动，请稍后操作"
            )
            return
        return func(self, sample, wait)
    return wrapper


def set_running_sc(func):
    """
    装饰器函数，在机械手通过此py文件运动时，设置CatsMaintMockup.py 中的状态
    """
    def wrapper(self, sample, wait):
        # 设置机械手在运动
        HWR.beamline.sample_changer_maintenance.change_running_state(1)
        HWR.beamline.sample_changer_maintenance._update_global_state()

        try:
            res = func(self, sample, wait)  
        except Exception as e:
            raise e
        finally:
            # 结束机械手运动状态
            HWR.beamline.sample_changer_maintenance._running = 0
            HWR.beamline.sample_changer_maintenance._update_global_state()
        
        if self._ifcmdSucceeded:
            self._ifcmdSucceeded = False
            return res
        else:
            print('self._ifcmdSucceeded in wrapper')
            logging.getLogger("HWR").error(
                "socket timeout, please check the network connection"
            )
            raise Exception("socket timeout, please check the network connection")
    return wrapper


def if_ErrorCode(func):
    """
    装饰器函数，用于当发送机械手命令，机械手返回报错时，获取报错信息
    """
    def wrapper(self, *args):
        try:
            res = func(self, *args)
        except Exception as e:
            print("type(e) from if_ErrorCode:", type(e))
            print("e from if_ErrorCode::", e)
            errorCode = e
            return errorCode
        else:
            return res
    return wrapper


class FlexSampleChanger(AbstractSampleChanger.SampleChanger):
    __TYPE__ = "Flex"
    NO_OF_BASKETS = 37
    NO_OF_SAMPLES_IN_BASKET = 16

    def __init__(self, *args, **kwargs):
        super(FlexSampleChanger, self).__init__(self.__TYPE__, False, *args, **kwargs)

    def init(self):
        self._selected_sample = -1
        self._selected_basket = -1
        self._scIsCharging = None
        self.centring_method = "AUTO_LOOP"

        self.no_of_baskets = self.get_property(
            "no_of_baskets", FlexSampleChanger.NO_OF_BASKETS
        )

        self.no_of_samples_in_basket = self.get_property(
            "no_of_samples_in_basket", FlexSampleChanger.NO_OF_SAMPLES_IN_BASKET
        )

        for i in range(self.no_of_baskets):
            basket = Container.Basket(
                self, i + 1, samples_num=self.no_of_samples_in_basket
            )
            self._add_component(basket)

        self._init_sc_contents()
        self.signal_wait_task = None
        AbstractSampleChanger.SampleChanger.init(self)

        self.log_filename = self.get_property("log_filename")

        self._dewar = 1
        self.exporter_addr = '10.30.61.74:9001'
        self._ifcloseLid_inBeginning = True
        self.count = 1
        self.pulling_state_flex_flag = True

        # --- Command Definitions ---
        self._cmdExchange = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "chainedUnldLd"},
            "chainedUnldLd",
        )
        self._cmdLoadSample = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "loadSample"},
            "loadSample",
        )
        self._cmdUnLoadSample = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "unloadSample"},
            "unloadSample",
        )
        self._cmdGetState = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "getState"},
            "getState",
        )
        self._cmdGetStatus = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "getStatus"},
            "getStatus",
        )
        self._cmdGetSamplePoolLN2Level = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "getSamplePoolLN2Level"},
            "getSamplePoolLN2Level"
        )
        self._cmdGetMountedSamplePosition = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "getMountedSamplePosition"},
            "getMountedSamplePosition",
        )
        self._cmdGetPresentSamples = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "getPresentSamples"},
            "getPresentSamples",
        )
        self._cmdCheckTaskResult = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "checkTaskResult"},
            "checkTaskResult",
        )
        self._cmdGetLastTaskException = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "getLastTaskException"},
            "getLastTaskException",
        )
        self._cmdGetCurrentLoadSampleState = self.add_command(
            {"type": "exporter", "exporter_address": self.exporter_addr, "name": "getCurrentLoadSampleState"},
            "getCurrentLoadSampleState",
        )

        self._ifcmdSucceeded = False
        self.first_launch_mxcube = True 
        self.if_check_mountedPin_from_camerman = False
        self.write_sample_dir()  # 初始化为空列表
        self.get_loaded_sample_fromstart()

    def pulling_state_flex(self):
        while self.pulling_state_flex_flag:
            gevent.sleep(0.5)
            try:
                if self._ready():
                    self._set_state(AbstractSampleChanger.SampleChangerState.Ready)
                    if HWR.beamline.sample_changer_maintenance._running != 0:
                        HWR.beamline.sample_changer_maintenance._update_running_state(0)
                else:
                    self._set_state(AbstractSampleChanger.SampleChangerState.Moving)
                    if HWR.beamline.sample_changer_maintenance._running != 1:
                        HWR.beamline.sample_changer_maintenance._update_running_state(1)
            except Exception:
                pass

            try:
                current_status = self._do_getStatus()
                self._set_status(current_status)
            except Exception:
                pass

            try:
                current_sample_pool_LN2_level = self._do_getSamplePoolLN2Level()
                self._set_sampleLN2Level(current_sample_pool_LN2_level)
            except Exception:
                pass

    # =========================================================================
    #  核心修改区域：命名逻辑简化与 CSV 导入
    # =========================================================================

    def write_sample_dir(self):
        """
        [Simplified] 彻底简化：初始化为空白列表，防止 "0 -" 或 "Sample-" 前缀干扰。
        """
        self.proteinAcronym = [["" for j in range(self.no_of_samples_in_basket)] for i in range(self.no_of_baskets)]
        self.default_prefix = [["" for j in range(self.no_of_samples_in_basket)] for i in range(self.no_of_baskets)]
        logging.getLogger("user_level_log").info("SampleChanger: 命名规则已简化 (Clean Mode)")

    def _init_sc_contents(self):
        """
        [Safe Mode] 初始化默认样品。
        使用 'Sample_1_01' (下划线) 代替 '1:01' (冒号)，确保文件名安全。
        """
        # 1. 初始化 Puck
        for basket_index in range(self.no_of_baskets):
            try:
                basket = self.get_components()[basket_index]
                basket._set_info(True, None, False)
            except IndexError:
                pass

        # 2. 生成默认样品
        sample_list = []
        for basket_index in range(self.no_of_baskets):
            for sample_index in range(self.no_of_samples_in_basket):
                sample_list.append((basket_index + 1, sample_index + 1))

        # 3. 填充 Sample 对象
        for (basket_id, sample_id) in sample_list:
            address = Container.Pin.get_sample_address(basket_id, sample_id)
            sample = self.get_component_by_address(address)
            
            if sample:
                # 使用安全的文件名格式
                safe_name = "Sample_%d_%02d" % (basket_id, sample_id)
                sample._name = safe_name
                
                # Datamatrix
                datamatrix = "matr%d_%d" % (basket_id, sample_id)
                
                # 设置状态: Present=True
                sample._set_info(True, datamatrix, False)
                sample._set_loaded(False, False)
                sample._set_holder_length(Container.Pin.STD_HOLDERLENGTH)

        self._set_state(AbstractSampleChanger.SampleChangerState.Ready)

    def import_samples_from_csv(self, file_path="/tmp/sample_import.csv"):
        """
        [Final Clean] 导入 CSV，清洗非法字符，同步所有内部列表。
        """
        logger = logging.getLogger("user_level_log")
        
        if not os.path.exists(file_path):
            logger.error(f"CSV 文件未找到: {file_path}")
            return

        try:
            try:
                f = open(file_path, mode='r', encoding='utf-8-sig')
                f.read(); f.seek(0)
            except UnicodeDecodeError:
                f = open(file_path, mode='r', encoding='gbk')
            
            with f:
                reader = csv.reader(f)
                rows = list(reader)
                count = 0
                updated_baskets = set()

                for row in rows:
                    if not row or len(row) < 3: continue  
                    try:
                        basket_id = int(row[0].strip())
                        sample_id = int(row[1].strip())
                        raw_name = row[2].strip()
                        if not raw_name: continue
                        
                        # 安全过滤：将非法字符替换为下划线
                        safe_name = re.sub(r'[\\/*?:"<>| ]', '_', raw_name)
                    except ValueError:
                        continue

                    address = Container.Pin.get_sample_address(basket_id, sample_id)
                    sample = self.get_component_by_address(address)
                    
                    if sample:
                        sample._name = safe_name
                        sample._set_info(True, safe_name, False)
                        
                        # 同步 Flex 内部列表 - ProteinAcronym
                        if hasattr(self, 'proteinAcronym'):
                             try: self.proteinAcronym[basket_id - 1][sample_id - 1] = safe_name
                             except: pass
                        
                        # [FIXED] 同步 Flex 内部列表 - DefaultPrefix
                        # 解决 "Sample-1:01" 后缀问题：将 default_prefix 也设为名字，防止 UI 使用默认位置占位符
                        if hasattr(self, 'default_prefix'):
                             try: self.default_prefix[basket_id - 1][sample_id - 1] = safe_name
                             except: pass
                        
                        updated_baskets.add(basket_id)
                        count += 1

                # 确保 Puck 在位
                for b_id in updated_baskets:
                    try:
                        basket = self.get_components()[b_id - 1]
                        basket._set_info(True, None, False)
                    except: pass

            self.emit("contentsUpdated")
            self.update_info()
            try: self.emit("valueChanged", "contents", self.get_contents())
            except: pass
            
            logger.info(f"成功导入 {count} 个样品 (非法字符已过滤)")
            
        except Exception as e:
            logger.error(f"导入异常: {str(e)}")
            traceback.print_exc()

    def clear_and_reset_samples(self):
        """
        [Reset] 重置为默认状态 (Sample_X_XX)。
        """
        logger = logging.getLogger("user_level_log")
        try:
            self._init_sc_contents()
            self.write_sample_dir() # 再次清空内部列表
            
            self.emit("contentsUpdated")
            self.update_info()
            logger.info("样品列表已重置为默认状态。")
            return True
        except Exception as e:
            logger.error(f"重置失败: {str(e)}")
            return False

    # =========================================================================
    #  常规机械手控制逻辑 (Hardware Control)
    # =========================================================================

    def change_load_sample(self,sample):
        previous_sample = self.get_loaded_sample()
        self._reset_loaded_sample()
        puck,pin = sample.split(":")
        self._selected_basket = puck = int(puck)
        self._selected_sample = pin = int(pin)

        mounted_sample = self.get_component_by_address(
            Container.Pin.get_sample_address(puck, pin)
        )

        if mounted_sample is not previous_sample:
            self._trigger_loaded_sample_changed_event(mounted_sample)
        self.update_info()
        self.emit("fsmConditionChanged", "sample_is_loaded", True)
        self.emit("fsmConditionChanged", "sample_mounting_sample_changer", False)

    def checkTaskResult(self,task_id):
        print('task_id in checkTaskResult: ',task_id,type(task_id))
        taskRes = self._cmdCheckTaskResult(task_id)
        print('taskRes: ',taskRes)
        if taskRes < 0 :
            taskExceptionRes = self._cmdGetLastTaskException()
            print('taskExceptionRes: ',taskExceptionRes)
            raise Exception("error in task: "+taskExceptionRes)

    @if_ErrorCode
    def _do_mount(self, magazine, position,wait=True,timeout=None):
        parm = '1\t'+str(magazine)+'\t'+str(position)
        res = self._cmdLoadSample(parm)
        if wait:
            self.wait_centring_ready_when_load(magazine,position,res,timeout)
        return res

    @if_ErrorCode
    def _do_unmount(self, magazine, position,wait=True,timeout=None):
        parm = '1\t' + str(magazine) + '\t' + str(position)
        res = self._cmdUnLoadSample(parm)
        if wait:
            self.wait_ready(timeout)
            self.checkTaskResult(res)
        return res

    @if_ErrorCode
    def _do_exchange(self, oldMagazine, oldPosition, newMagazine, newPosition,wait=True,timeout = None):
        print("oldMagazine,oldPosition,NewMagazine,NewPosition:", oldMagazine, oldPosition, newMagazine, newPosition)
        parm = '1\t' + str(newMagazine) + '\t' + str(newPosition)
        print("parm in exchange method and typeof(parm): ",parm,type(parm))
        res = self._cmdLoadSample(parm)
        MD2 = HWR.beamline.diffractometer
        print('current phase and state of md2: ', MD2.get_current_phase(), MD2.get_state())
        if wait:
            print("waiting the return message")
            self.wait_centring_ready_when_load(newMagazine, newPosition, res, timeout)
        return res

    @if_ErrorCode
    def _do_getMountedSamplePosition(self,wait=True,timeout=None):
        res = self._cmdGetMountedSamplePosition()
        return res

    @if_ErrorCode
    def _do_getState(self):
        res = self._cmdGetState()
        return res
    
    @if_ErrorCode
    def _do_getStatus(self):
        res = self._cmdGetStatus()
        return res
    
    @if_ErrorCode
    def _do_getSamplePoolLN2Level(self):
        res = self._cmdGetSamplePoolLN2Level()
        return res

    def _ready(self):
        state = self._do_getState()
        if state == 'Ready':
            return True
        else:
            return False

    def wait_ready(self, timeout=None):
        if timeout is not None and timeout <= 0:
            logging.getLogger("HWR").warning(
                "DEBUG: Strange timeout value passed %s" % str(timeout)
            )
            timeout = 30
        with gevent.Timeout(
            timeout, RuntimeError("Timeout waiting for FlexRobot to be ready")
        ):
            while not self._ready():
                gevent.sleep(0.5)

    def wait_centring_ready_when_load(self,puck_num,pin_num,task_id,timeout=None):
        MD2 = HWR.beamline.diffractometer
        timeout = 300
        if timeout is not None and timeout <= 0:
            logging.getLogger("HWR").warning(
                "DEBUG: Strange timeout value passed %s" % str(timeout)
            )
            timeout = 30
        with gevent.Timeout(
                timeout, RuntimeError("Timeout waiting for FlexRobot to be ready")
        ):
            print('current phase and state of md2 in wait centring ready: ',MD2.get_current_phase(),MD2.get_state())

            while True:
                load_sample_state = self._cmdGetCurrentLoadSampleState()
                gevent.sleep(0.3)
                if load_sample_state == 'on_gonio' and MD2.get_state() =='Ready':
                    break
                if self._ready():
                    self.checkTaskResult(task_id)

            res = self._do_getMountedSamplePosition()
            if res[1]==puck_num and res[2]==pin_num:
                print("sample is ready to centring")
            else:
                self.checkTaskResult(task_id)

    def get_log_filename(self):
        return self.log_filename

    def load_sample(self, holder_length, sample_location=None, wait=False):
        print("进入ActorSampleChanger.py的load_sample函数")
        self.load(sample_location, wait)

    @property
    def ifcloseLid_inBeginning(self):
        return self._ifcloseLid_inBeginning

    def change_ifcloseLid_inBeginning_state(self, state: bool):
        self._ifcloseLid_inBeginning = state

    def MD2_Centring(self):
        HWR.beamline.diffractometer.set_phase("Centring")
        HWR.beamline.diffractometer._wait_ready(30000)
        if self.centring_method == "AUTO_LOOP":
            logging.getLogger("HWR").info("CENTRING_METHOD: auto LOOP CENTRING")
            HWR.beamline.diffractometer.start_auto_sample_centring("LOOP_CENTRING_ONLY")
        elif self.centring_method == "MANUAL":
            logging.getLogger("HWR").info("CENTRING_METHOD: MANUAL CENTRING")

    def test_exception(self):
        try:
            raise ConnectionRefusedError
        except Exception as e:
            return e

    @if_running_sc
    @set_running_sc
    def exchange(self, newsample, wait=False):
        print("进入exchange函数")

        oldsample = self.get_loaded_sample().get_address()
        print("oldsample: ", oldsample, "newsample: ", newsample)
        oldBasket, oldSample = oldsample.split(":")
        newBasket, newSample = newsample.split(":")

        # 清除oldsample 的 loaded属性
        self.get_loaded_sample()._set_loaded(False, True) 

        self.emit("fsmConditionChanged", "sample_mounting_sample_changer", True)

        newBasket = int(newBasket)
        newSample = int(newSample)
        oldBasket = int(oldBasket)
        oldSample = int(oldSample)

        msg = "Exchanging sample %d:%d" % (newBasket, newSample)
        logging.getLogger("user_level_log").info(
            "Sample changer: %s. Please wait..." % msg
        )
        self.emit("progressInit", (msg, 100))
        print("before self.emit(progressStep,int(step/2))")
        for step in range(2 * 100):
            self.emit("progressStep", int(step / 2.0))
            # 优化：使用 gevent.sleep 防止阻塞
            gevent.sleep(0.001)
        print("self.emit(progressStep,int(step/2)) ended")

        print("oldSample!=newSample or oldBasket != newSample:", oldSample != newSample or oldBasket != newBasket)
        if oldSample != newSample or oldBasket != newBasket:
            self._ifcmdSucceeded = self._do_exchange(oldBasket, oldSample, newBasket, newSample)
            print("DEBUG!!!self._ifcmdSucceeded:", self._ifcmdSucceeded, type(self._ifcmdSucceeded))

            if self._ifcmdSucceeded == False:
                print('_ifcmdSucceeded is false.')
                self._set_state(AbstractSampleChanger.SampleChangerState.Ready)
                return
            elif (type(self._ifcmdSucceeded) is Exception) or (type(self._ifcmdSucceeded) is OSError) or (
                    type(self._ifcmdSucceeded) is TimeoutError) or (type(self._ifcmdSucceeded) is KeyError) or (
                    type(self._ifcmdSucceeded) is ConnectionRefusedError) or (
                    type(self._ifcmdSucceeded) is ConnectionAbortedError) or (
                    type(self._ifcmdSucceeded) is ConnectionResetError) or (
                    type(self._ifcmdSucceeded) is BrokenPipeError) or(
                    type(self._ifcmdSucceeded) is RuntimeError):
                # 在发生错误后恢复机械手的各种状态
                print("there is some error with exchange command, start try to restore status")
                self.update_info()
                self.emit("progressStop", ())
                self.emit("fsmConditionChanged", "sample_mounting_sample_changer", True)

                self._set_state(AbstractSampleChanger.SampleChangerState.Ready)
                HWR.beamline.sample_changer_maintenance._running = 0
                HWR.beamline.sample_changer_maintenance._update_global_state()

                self._ifcmdSucceeded = str(self._ifcmdSucceeded)
                logging.getLogger("user_level_log").error(
                    "ErrorCode from robot: %s,  " % self._ifcmdSucceeded)
                raise Exception(f"ErrorCode from robot: {self._ifcmdSucceeded},  ")

            # 命令完成
            mounted_sample = self.get_component_by_address(
                Container.Pin.get_sample_address(newBasket, newSample)
            )
            self._trigger_loaded_sample_changed_event(mounted_sample)
            self._selected_basket = newBasket
            self._selected_sample = newSample
            self.send_sample_address_to_statemessage()
        
        # exchange的是同一个或者exchange完成
        self.update_info()
        logging.getLogger("user_level_log").info("Sample changer: Sample loaded")
        self.emit("progressStop", ())

        self.emit("fsmConditionChanged", "sample_is_loaded", True)
        self.emit("fsmConditionChanged", "sample_mounting_sample_changer", False)

        self._set_state(AbstractSampleChanger.SampleChangerState.Ready)
        print("self.get_loaded_sample().get_address()", self.get_loaded_sample().get_address())
        
        self.count += 1
        self.MD2_Centring()
        return self.get_loaded_sample()

    def change_MD2_state(self, timeout=3):
        MD2 = HWR.beamline.diffractometer
        if MD2.get_current_phase() != "Transfer":
            MD2.set_phase("Transfer", wait=True)
            gevent.sleep(0.5)
            print("切换完成")
        gevent.sleep(timeout)
        if MD2.get_current_phase() == "Transfer":
            return True
        else:
            return False

    def change_Cryo_state(self, timeout=1):
        MD2 = HWR.beamline.diffractometer
        MD2.Cryo_Is_Back.set_value(True)

    def check_MD2_state(self):
        MD2 = HWR.beamline.diffractometer
        if not self.change_MD2_state():
            logging.getLogger("user_level_log").error(
                "The MD2 seems cannot change to sample change status while mounting, please try again first.")
            raise Exception(
                "The MD2 seems cannot change to sample change status while mounting, please try again first.")

    def check_MD2_Magnet(self):
        MD2 = HWR.beamline.diffractometer
        logging.getLogger("HWR").info("smart magnet state: %s", str(MD2.sample_isloaded_magnet.get_value()))
        if MD2.sample_isloaded_magnet.get_value():
            logging.getLogger("user_level_log").error(
                "The smart magnet says there's a sample already been mounted, if there's not, please contact the teacher on duty")
            raise Exception(
                "The smart magnet says there's a sample already been mounted, if there's not, please contact the teacher on duty")

    @if_running_sc
    @set_running_sc
    def load(self, sample, wait=False):
        print("进入load函数")
        self.emit("fsmConditionChanged", "sample_mounting_sample_changer", True)
        previous_sample = self.get_loaded_sample()

        if isinstance(sample, tuple):
            basket, sample = sample
        else:
            basket, sample = sample.split(":")

        self._selected_basket = basket = int(basket)
        self._selected_sample = sample = int(sample)
        self.send_sample_address_to_statemessage()

        msg = "Loading sample %d:%d" % (basket, sample)
        logging.getLogger("user_level_log").info(
            "Sample changer: %s. Please wait..." % msg
        )
        self.emit("progressInit", (msg, 100))
        for step in range(2 * 100):
            self.emit("progressStep", int(step / 2.0))
            # 优化: gevent.sleep
            gevent.sleep(0.01)

        mounted_sample = self.get_component_by_address(
            Container.Pin.get_sample_address(basket, sample)
        )

        if mounted_sample is not previous_sample:
            self._ifcmdSucceeded = self._do_mount(basket, sample)
            print("self._ifcmdSucceeded:", self._ifcmdSucceeded, type(self._ifcmdSucceeded))

            if self._ifcmdSucceeded == False:
                self._selected_sample = -1
                self._selected_basket = -1
                self.send_sample_address_to_statemessage()
                self._set_state(AbstractSampleChanger.SampleChangerState.Ready)
                return

            elif (type(self._ifcmdSucceeded) is Exception) or (type(self._ifcmdSucceeded) is OSError) or (
                    type(self._ifcmdSucceeded) is TimeoutError) or (type(self._ifcmdSucceeded) is KeyError) or (
                    type(self._ifcmdSucceeded) is ConnectionRefusedError) or (
                    type(self._ifcmdSucceeded) is ConnectionAbortedError) or (
                    type(self._ifcmdSucceeded) is ConnectionResetError) or (
                    type(self._ifcmdSucceeded) is BrokenPipeError) or(
                    type(self._ifcmdSucceeded) is RuntimeError):
                # 在发生错误后恢复机械手的各种状态
                self._selected_sample = -1
                self._selected_basket = -1
                self.send_sample_address_to_statemessage()
                self.update_info()
                self.emit("progressStop", ())
                self.emit("fsmConditionChanged", "sample_mounting_sample_changer", False)

                self._set_state(AbstractSampleChanger.SampleChangerState.Ready)
                HWR.beamline.sample_changer_maintenance._running = 0
                HWR.beamline.sample_changer_maintenance._update_global_state()

                self._ifcmdSucceeded = str(self._ifcmdSucceeded)
                logging.getLogger("user_level_log").error(
                    "ErrorCode from robot: %s,  " % self._ifcmdSucceeded)
                raise Exception(f"ErrorCode from robot: {self._ifcmdSucceeded},  ")

            self._trigger_loaded_sample_changed_event(mounted_sample)

        self.send_sample_address_to_statemessage()
        self.update_info()
        logging.getLogger("user_level_log").info("Sample changer: Sample loaded")
        self.emit("progressStop", ())

        self.emit("fsmConditionChanged", "sample_is_loaded", True)
        self.emit("fsmConditionChanged", "sample_mounting_sample_changer", False)

        self._set_state(AbstractSampleChanger.SampleChangerState.Ready)
        print("self.get_loaded_sample().get_address()", self.get_loaded_sample().get_address())
        
        self.count += 1
        self.MD2_Centring()
        return self.get_loaded_sample()

    def unload_error_recover(self):
        """
        在发生错误后恢复机械手的各种状态
        """
        self._trigger_loaded_sample_changed_event(self.get_loaded_sample())
        self._set_state(AbstractSampleChanger.SampleChangerState.Ready)
        HWR.beamline.sample_changer_maintenance._running = 0
        HWR.beamline.sample_changer_maintenance._update_global_state()

    def clear_memory(self):
        """
        用来清除已经上样信息 (Robot Status Memory)
        注意：这与清空样品名的 reset 不同
        """
        if self.get_loaded_sample():
            sample = self.get_loaded_sample()
            sample._set_loaded(False, True)

        self._selected_basket = -1
        self._selected_sample = -1

        self._trigger_loaded_sample_changed_event(self.get_loaded_sample())
        self.send_sample_address_to_statemessage()

        self.emit("fsmConditionChanged", "sample_is_loaded", False)

    @if_running_sc
    @set_running_sc
    def unload(self, sample_slot=None, wait=None):
        logging.getLogger("user_level_log").info("Unloading sample")

        try:
            logging.getLogger("user_level_log").info(
                "即将把样品下到的位置:" + sample_slot + ",已上样样品本来所处的位置:" + self.get_loaded_sample().get_address())
        except AttributeError:
            logging.getLogger("user_level_log").error("还没有上样，无法取下样品")
            self.unload_error_recover()
            raise Exception("Can not unload since there has no sample was mounted")

        if sample_slot == self.get_loaded_sample().get_address():
            logging.getLogger("user_level_log").info("即将把样品下到的位置与已上样样品本来所处的位置一致，开始下样")
        else:
            logging.getLogger("user_level_log").error("即将把样品下到的位置与已上样样品本来所处的位置不一致")
            self.unload_error_recover()
            raise Exception("the location selected is not the same as the location where the mounted sample was taken")

        sample = self.get_loaded_sample()
        sample._set_loaded(False, True) 

        if self._selected_sample > 0 and self._selected_sample <= 16:
            self._ifcmdSucceeded = self._do_unmount(self._selected_basket, self._selected_sample)
            if self._ifcmdSucceeded == False:
                self._set_state(AbstractSampleChanger.SampleChangerState.Ready)
                return
            elif (type(self._ifcmdSucceeded) is Exception) or (type(self._ifcmdSucceeded) is OSError) or (
                    type(self._ifcmdSucceeded) is TimeoutError) or (type(self._ifcmdSucceeded) is KeyError) or (
                    type(self._ifcmdSucceeded) is ConnectionRefusedError) or (
                    type(self._ifcmdSucceeded) is ConnectionAbortedError) or (
                    type(self._ifcmdSucceeded) is ConnectionResetError) or (
                    type(self._ifcmdSucceeded) is BrokenPipeError) or(
                    type(self._ifcmdSucceeded) is RuntimeError):

                self.unload_error_recover()
                self._ifcmdSucceeded = str(self._ifcmdSucceeded)
                raise Exception(f"ErrorCode from robot: {self._ifcmdSucceeded},  ")

            self._selected_basket = -1
            self._selected_sample = -1

            self._trigger_loaded_sample_changed_event(self.get_loaded_sample())
            self.send_sample_address_to_statemessage()
            self.emit("fsmConditionChanged", "sample_is_loaded", False)
        else:
            logging.getLogger("HWR").debug("cannot unload, the location is wrong")

    def synchronize_with_flex(self):
        ret = self._do_getMountedSamplePosition()
        print("self._do_getMountedSamplePosition(): ",ret,type(ret))

        MountedPin = ret

        # 有样品，相当于换样
        if MountedPin[0] != -1: # [-1,-1,-1]
            self._selected_basket = MountedPin[1]
            self._selected_sample = MountedPin[2]
            
            mounted_sample = self.get_component_by_address(
                Container.Pin.get_sample_address(self._selected_basket, self._selected_sample)
            )
            self._trigger_loaded_sample_changed_event(mounted_sample)
            self.send_sample_address_to_statemessage()
            self.update_info()
            logging.getLogger("user_level_log").info("Sample changer: Sample loaded")

            self.emit("fsmConditionChanged", "sample_is_loaded", True)
            self.emit("fsmConditionChanged", "sample_mounting_sample_changer", False)

        # 没有样品，相当于下样
        else:
            self._selected_basket = MountedPin[1] # -1
            self._selected_sample = MountedPin[2] # -1

            self._trigger_loaded_sample_changed_event(self.get_loaded_sample())
            self.send_sample_address_to_statemessage()
            self.emit("fsmConditionChanged", "sample_is_loaded", False)

        return ret

    def get_loaded_sample_fromstart(self):
        try:
            if self.first_launch_mxcube:
                self.first_launch_mxcube = False
        except AttributeError:
            pass
        else:
            if not self.if_check_mountedPin_from_camerman:
                self.if_check_mountedPin_from_camerman = True
                print("try to get loaded sample info from flex robot")
                ret = self._cmdGetMountedSamplePosition()
                print("the result of loaded sample info: ",ret)
                MountedPin = ret
                self._selected_basket = MountedPin[1]
                self._selected_sample = MountedPin[2]

    def get_loaded_sample(self):
        return self.get_component_by_address(
            Container.Pin.get_sample_address(
                self._selected_basket, self._selected_sample
            )
        )

    def is_mounted_sample(self, sample):
        return (
                self.get_component_by_address(
                    Container.Pin.get_sample_address(sample[0], sample[1])
                )
                == self.get_loaded_sample()
        )

    def send_msg_to_statemessage(self, msg):
        HWR.beamline.sample_changer_maintenance.change_message_error(msg)

    def send_sample_address_to_statemessage(self):
        try:
            address = self.get_loaded_sample().get_address()
        except AttributeError:
            HWR.beamline.sample_changer_maintenance.change_message_sampleState("None")
        else:
            HWR.beamline.sample_changer_maintenance.change_message_sampleState(address)

    def _do_abort(self):
        return

    def _do_change_mode(self):
        return

    def _do_update_info(self):
        return

    def _do_select(self, component):
        return

    def _do_scan(self, component, recursive):
        return

    def _do_load(self, sample=None):
        return

    def _do_unload(self, sample_slot=None):
        return

    def _do_reset(self):
        return

    def notice_for_developer(self):
        pass