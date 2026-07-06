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

from mxcubecore.HardwareObjects.abstract.AbstractAperture import (
    AbstractAperture,
)

__credits__ = ["EMBL Hamburg"]
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
        Returns:
        """
        self._position_list = DEFAULT_POSITION_LIST

        self.chan_diameters = self.get_channel_object("ApertureDiameters")
        if self.chan_diameters:
            self._diameter_size_list = self.chan_diameters.get_value()
        else:
            #self._diameter_size_list = (10, 20)
            self._diameter_size_list = [20, 50, 100]
        print("ApertureDiameters are:", self._diameter_size_list)

        self.chan_diameter_index = self.get_channel_object("CurrentApertureDiameterIndex")
        if self.chan_diameter_index is not None:
        #if self.chan_diameter_index:
            self._current_diameter_index = self.chan_diameter_index.get_value()
            self.diameter_index_changed(self._current_diameter_index)
            self.chan_diameter_index.connectSignal(
                "update", self.diameter_index_changed
            )
        else:
            self._current_diameter_index = 1
        print("aperturediameterindex is:", self._current_diameter_index)


        self.chan_position = self.get_channel_object("AperturePosition")
        print("aperture position is:", self.chan_position.value)
        if self.chan_position:
            self._current_position_name = self.chan_position.get_value()
            self.current_position_name_changed(self._current_position_name)
            self.chan_position.connectSignal(
                "update", self.current_position_name_changed
            )
        self.chan_state = self.get_channel_object("State")

    def diameter_index_changed(self, diameter_index):
        """Callback when diameter index has been changed"""
        self._current_diameter_index = diameter_index
        self.emit(
            "diameterIndexChanged",
            self._current_diameter_index,
            #self._diameter_size_list[self._current_diameter_index] ,
            self._diameter_size_list[self._current_diameter_index] / 1000.0,

        )

    def current_position_name_changed(self, position):
        """
        Position change callback

        Args:
            position: aperture position (str)
        Returns:
        """
        if position != "UNKNOWN":
            self.set_position_name(position)

    def set_diameter_index(self, diameter_index):
        """
        Sets aperture diameter

        Args:
            diameter_index: diameter index (int)
        Returns:
        """
        super().set_diameter_index(diameter_index)
        self.chan_diameter_index.set_value(diameter_index)

    # def set_diameter(self, diameter_size, timeout=None):
    #     """
    #     Sets new aperture size

    #     Args:
    #         diameter_size: diameter size in microns (int)
    #         timeout: wait timeout is seconds
    #     Returns:
    #     """
    #     diameter_index = self._diameter_size_list.index(diameter_size)
    #     self.chan_diameter_index.set_value(diameter_index)
    #     self.chan_diameter_index.update()

    def set_diameter(self, diameter_size, timeout=None):
        """
        Sets new aperture size (带强力 Debug 版)
        """
        print("\n" + "="*50)
        print(f"🚀 [Aperture DEBUG] 收到前端请求，目标光斑大小: '{diameter_size}' (类型: {type(diameter_size)})")
        
        try:
            # 1. 强制转换为整型，防止字符串 '20' 导致的找不到元素报错
            target_size = int(float(diameter_size))
            
            # 2. 打印当前 Python 脑子里的硬件列表，看是不是错位的
            print(f"📋 [Aperture DEBUG] 当前加载的孔位列表: {self._diameter_size_list}")
            
            # 3. 计算下标
            diameter_index = self._diameter_size_list.index(target_size)
            print(f"🎯 [Aperture DEBUG] 换算出的硬件下标为: {diameter_index}")
            
            # 4. 发送指令
            print(f"📡 [Aperture DEBUG] 正在向硬件通道发送下标 {diameter_index}...")
            self.chan_diameter_index.set_value(diameter_index)
            self.chan_diameter_index.update()
            
            # 5. 等待 1 秒，然后去底层读回来，看看硬件到底认不认账
            import time
            time.sleep(1.0)
            actual_index = self.chan_diameter_index.get_value()
            print(f"👀 [Aperture DEBUG] 硬件当前实际处于下标: {actual_index}")
            
            if actual_index == diameter_index:
                print("✅ [Aperture DEBUG] 成功！硬件已联动。")
            else:
                print("❌ [Aperture DEBUG] 失败！硬件拒绝写入或未发生位移。")
                
        except Exception as e:
            # 必须把被吞掉的错误打印出来
            print(f"💥 [Aperture DEBUG] 代码执行崩溃，异常信息: {str(e)}")
            
        print("="*50 + "\n")
    def set_position_index(self, position_index):
        """
        Sets new aperture position

        Args:
            position_index: position index (int)
        Returns:
        """
        self.chan_position.set_value(self._position_list[position_index])
        self.chan_position.update()

    def set_in(self):
        """
        Sets aperture to the BEAM position

        Returns:
        """
        self.chan_position.set_value("BEAM")
        self.chan_position.update()

    def set_out(self):
        """Sets aperture to the OUT position

        Returns:
        """
        self.chan_position.set_value("OFF")
        self.chan_position.update()

    def wait_ready(self, timeout=5):
        """Waits till aperture is ready

        Returns:
        """
        super(Aperture, self).wait_ready(timeout=5)

    def is_out(self):
        """Returns True if aperture is on the beam

        Returns: True if is in, otherwise returns False
        """
        return self._current_position_name != "BEAM"
