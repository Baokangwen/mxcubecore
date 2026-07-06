#
#  Project: MXCuBE
#  https://github.com/mxcube
#
#  This file is part of MXCuBE software.
#
#  MXCuBE is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  MXCuBE is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with MXCuBE. If not, see <http://www.gnu.org/licenses/>.

"""Inherited from AbstracAperture"""
import gevent
import time
import logging

from mxcubecore.HardwareObjects.abstract.AbstractAperture import (
    AbstractAperture,
)

__credits__ = ["EMBL Hamburg", "SSRF BL19U1 Customized"]
__license__ = "LGPLv3+"
__category__ = "General"

DEFAULT_POSITION_LIST = ("BEAM", "OFF", "PARK")

class Aperture(AbstractAperture):
    """Aperture control hwobj uses exporter or Tine channels and commands
       to control aperture position
    """

    def __init__(self, name):
        """Inherited from AbstractAperture"""
        AbstractAperture.__init__(self, name)

        self.chan_diameter_index = None
        self.chan_diameters = None
        self.chan_position = None
        self.chan_state = None

    def init(self):
        """
        Connects to necessary channels
        """
        self._position_list = DEFAULT_POSITION_LIST

        self.chan_diameters = self.get_channel_object("ApertureDiameters")
        
        # =========================================================
        # 🎯 强制加载我们在底层测试出的绝对正确的光斑列表
        # =========================================================
        self._diameter_size_list = [5, 20, 50, 100, 150]
        logging.getLogger("HWR").info(f"✅ [Aperture] 强制加载硬件孔位列表: {self._diameter_size_list}")

        self.chan_diameter_index = self.get_channel_object("CurrentApertureDiameterIndex")
        if self.chan_diameter_index is not None:
            self._current_diameter_index = self.chan_diameter_index.get_value()
            
            # 🚨 防弹保护：防止刚启动时底层返回 None 导致 Python 崩溃
            if self._current_diameter_index is not None:
                self.diameter_index_changed(self._current_diameter_index)
                
            self.chan_diameter_index.connectSignal(
                "update", self.diameter_index_changed
            )
        else:
            self._current_diameter_index = 1
            logging.getLogger("HWR").warning("⚠️ [Aperture] 无法连接到 CurrentApertureDiameterIndex 通道，默认设为 1(20um)")

        self.chan_position = self.get_channel_object("AperturePosition")
        if self.chan_position:
            self._current_position_name = self.chan_position.get_value()
            self.current_position_name_changed(self._current_position_name)
            self.chan_position.connectSignal(
                "update", self.current_position_name_changed
            )
            
        self.chan_state = self.get_channel_object("State")

    def diameter_index_changed(self, diameter_index):
        """Callback when diameter index has been changed"""
        # 🚨 防弹保护：忽略无效值
        if diameter_index is None:
            return
            
        self._current_diameter_index = diameter_index
        try:
            self.emit(
                "diameterIndexChanged",
                self._current_diameter_index,
                self._diameter_size_list[self._current_diameter_index] / 1000.0,
            )
        except IndexError:
            logging.getLogger("HWR").warning(f"⚠️ [Aperture] 底层传回了未知的孔位下标: {diameter_index}")

    def current_position_name_changed(self, position):
        """
        Position change callback
        """
        if position and position != "UNKNOWN":
            self.set_position_name(position)

    def set_diameter_index(self, diameter_index):
        """
        Sets aperture diameter by index
        """
        super().set_diameter_index(diameter_index)
        self.chan_diameter_index.set_value(diameter_index)

    # =========================================================
    # 🎯 补充丢失的桥接方法：响应前端 MXCuBE3 的 set_value 请求
    # =========================================================
    def set_value(self, value):
        logging.getLogger("HWR").info(f"🔄 [Aperture] Web 前端调用了 set_value({value})，正在重定向至 set_diameter...")
        self.set_diameter(value)

    def set_diameter(self, diameter_size, timeout=10.0):
        """
        强力闭环控制版光阑切换函数：带超时检测、真实状态回读
        """
        try:
            target_size = int(float(diameter_size))
            diameter_index = self._diameter_size_list.index(target_size)
        except ValueError:
            logging.getLogger("HWR").error(f"❌ [Aperture] 找不到该光斑大小: {diameter_size}")
            raise ValueError(f"Invalid aperture size: {diameter_size}")

        logging.getLogger("HWR").info(f"🚀 [Aperture] 准备将光斑切换至: {target_size}um (将向硬件写入下标: {diameter_index})")
        
        try:
            # 1. 写入指令
            self.chan_diameter_index.set_value(diameter_index)
            
            # 2. 死盯底层硬件，循环回读
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                actual_index = self.chan_diameter_index.get_value()
                
                if actual_index == diameter_index:
                    logging.getLogger("HWR").info(f"✅ [Aperture] 光阑已成功物理切换至 {target_size}um！")
                    self.chan_diameter_index.update()
                    self.diameter_index_changed(actual_index)
                    return True
                
                time.sleep(0.1)
                
            # 3. 超时报错
            error_msg = f"❌ [Aperture] 切换光阑超时！等了 {timeout} 秒，底层依然未就绪。"
            logging.getLogger("HWR").error(error_msg)
            raise RuntimeError(error_msg)
            
        except Exception as e:
            logging.getLogger("HWR").error(f"💥 [Aperture] 硬件通信异常: {str(e)}")
            raise e

    def set_position_index(self, position_index):
        self.chan_position.set_value(self._position_list[position_index])
        self.chan_position.update()

    def set_in(self):
        self.chan_position.set_value("BEAM")
        self.chan_position.update()

    def set_out(self):
        self.chan_position.set_value("OFF")
        self.chan_position.update()

    def wait_ready(self, timeout=5):
        super(Aperture, self).wait_ready(timeout=5)

    def is_out(self):
        return self._current_position_name != "BEAM"