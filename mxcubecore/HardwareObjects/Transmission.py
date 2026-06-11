import logging
import gevent
from mxcubecore.HardwareObjects.abstract.AbstractTransmission import AbstractTransmission

class Transmission(AbstractTransmission):
    def __init__(self, name):
        super(Transmission, self).__init__(name)
        self.labels = []
        self.indexes = []
        self.filters = [] 
        self.attno = 0
        
        self.preset_combinations = {
            100: [],         
            90:  [0],        
            80:  [1],        
            70:  [0, 1],     
            60:  [2],        
            50:  [0, 2],     
            40:  [1, 2],     
            30:  [0, 1, 2],  
            20:  [3],        
            10:  [0, 3],     
            0:   [0, 1, 2, 3] 
        }

    def get_limits(self):
        return (0.0, 100.0)
        
    def is_ready(self):
        return True

    def init(self):
        if hasattr(self, "update_state") and hasattr(self, "STATES"):
            self.update_state(self.STATES.READY)

        self.filters = []
        self.indexes = []
   
        for i in range(4): 
            chan_state = self.get_channel_object(f"state_{i}")
            if chan_state is not None:
                self.filters.append({
                    "index": i,
                    "state": chan_state
                })
                self.indexes.append(i)
                chan_state.connect_signal("update", self._on_status_changed)
                print(f"[Transmission] find FIL{i}  PV")
            else:
                print(f"[Transmission] cannot find state_{i} ")
                
        self.attno = len(self.filters)
        self._update()

    def getAttState(self):
        curr_bits = 0
        for flt in self.filters:
            if flt["state"] is not None:
                val = flt["state"].get_value()
                if str(val).strip() in ("In", "IN", "in", "1", 1):
                    curr_bits |= (1 << flt["index"])
        return curr_bits

    def is_in(self, attenuator_index):
        curr_bits = self.getAttState()
        return bool((1 << attenuator_index) & curr_bits)

    def _set_value(self, value):
        print(f"\n [Transmission] target: {value}%")

        if hasattr(self, "update_state"): self.update_state(self.STATES.BUSY)
            
        value = max(0, min(100, float(value)))
        target_level = int(round(value / 10.0) * 10)
        target_indexes = self.preset_combinations.get(target_level, [])
  
        for flt in self.filters:
            idx = flt["index"]
            cmd = "In" if idx in target_indexes else "Out"
            flt["state"].set_value(cmd)
                

        def force_update():
            gevent.sleep(0.8)
            self._update()
            gevent.sleep(1.0)
            self._update()

            if hasattr(self, "update_state"): self.update_state(self.STATES.READY)
            print(" [Transmission] done。")
            
        gevent.spawn(force_update)
        return float(value)

    def toggle(self, attenuator_index):
        flt = next((f for f in self.filters if f["index"] == attenuator_index), None)
        if not flt or flt["state"] is None:
            return

        if self.is_in(attenuator_index):
            flt["state"].set_value("Out")
        else:
            flt["state"].set_value("In")

    def get_value(self):
        current_indexes = []
        for flt in self.filters:
            if self.is_in(flt["index"]):
                current_indexes.append(flt["index"])
                
        current_indexes.sort()
        for level, indexes in self.preset_combinations.items():
            if current_indexes == sorted(indexes):
                return float(level)
                
        return 100.0

    def _update(self):
        self.emit("attStateChanged", self.getAttState())
        self.emit("attFactorChanged", self.get_value())
        self.emit("valueChanged", self.get_value())

    def _on_status_changed(self, value=None):
        self._update()