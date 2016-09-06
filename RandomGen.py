from time import time
from argparse import ArgumentParser
from ConfigParser import SafeConfigParser
import sys
import numpy as np

from numpy import zeros, int32
import PyDAQmx as pdq

from PyDragonfly import Dragonfly_Module, CMessage, copy_to_msg, MT_EXIT
import Dragonfly_config as rc
from dragonfly_utils import respond_to_ping        

"""This example is a PyDAQmx version of the ContAcq_IntClk.c example
It illustrates the use of callback functions

This example demonstrates how to acquire a continuous amount of
data using the DAQ device's internal clock. It incrementally stores the data
in a Python list.
"""

class DAQInterface(pdq.Task):

    def __init__(self, parent, cfg):
        tot_samp           = cfg.nsamp * cfg.nchan               # 8000; 14000
        print "tot_samp", tot_samp
        self.nsamp_per_irq = int(cfg.nsamp    / float(cfg.nirq)) # 20; 10
        print "nsamp_per_irq", self.nsamp_per_irq
        self.tsamp_per_irq = int(tot_samp / float(cfg.nirq))     # 160; 140
        print "tsamp_per_irq", self.tsamp_per_irq
        
        pdq.Task.__init__(self)
        self.data = zeros(self.tsamp_per_irq)
        self.CreateAIVoltageChan("Dev1/ai0:" + str(cfg.nchan - 1), "", pdq.DAQmx_Val_RSE, 
            cfg.minV, cfg.maxV, pdq.DAQmx_Val_Volts, None)
        self.CfgSampClkTiming("", cfg.nsamp, pdq.DAQmx_Val_Rising,
            pdq.DAQmx_Val_ContSamps, self.nsamp_per_irq)
        
        self.AutoRegisterEveryNSamplesEvent(
            pdq.DAQmx_Val_Acquired_Into_Buffer, self.nsamp_per_irq, 0)
        self.AutoRegisterDoneEvent(0)
        self.parent = parent
        
    def EveryNCallback(self):
        read    = pdq.int32() # num samples actually read
        timeout = 10.0        # seconds
        self.ReadAnalogF64(self.nsamp_per_irq, timeout, 
            pdq.DAQmx_Val_GroupByScanNumber, self.data,
            self.tsamp_per_irq, pdq.byref(read), None)
            
        self.parent_callback(self.data)
        return 0 # The function should return an integer
        
    def DoneCallback(self, status):
        print "Status", status.value
        return 0 # The function should return an integer
        
    def register_callback(self, fn):
        self.parent_callback = fn

class Config(object):
    pass
        
class RandomGen(object):
    def __init__(self, config_file, mm_ip):
        daq_config = self.load_config(config_file)
        self.setup_daq(daq_config)
        self.setup_dragonfly(mm_ip)
        self.serial_no = 2
        self.variable = 0        # 0 and 1 cause problems for LogReader
        self.run()
    
    def load_config(self, config_file):
        cfg = SafeConfigParser()
        cfg.read(config_file)
        daq_config = Config()
        daq_config.minV  = cfg.getfloat('main', 'minV')
        daq_config.maxV  = cfg.getfloat('main', 'maxV')
        daq_config.nsamp = cfg.getint('main', 'nsamp_per_chan_per_second')
        daq_config.nchan = cfg.getint('main', 'nchan')
        daq_config.nirq  = self.freq = cfg.getint('main', 'nirq_per_second')
        return daq_config
    
    def setup_daq(self, daq_config):
        self.daq_task = DAQInterface(self, daq_config)
        self.daq_task.register_callback(self.on_daq_callback)
        print "DrAQonfly: DAQ configured"
      
    def setup_dragonfly(self, mm_ip):
        self.mod = Dragonfly_Module(0, 0)
        self.mod.ConnectToMMM(mm_ip)
        self.mod.Subscribe(MT_EXIT)
        self.mod.Subscribe(rc.MT_PING)
        self.mod.SendModuleReady()
        print "DrAQonfly: connected to dragonfly"

    def on_daq_callback(self, data):
        mdf = rc.MDF_PLOT_POSITION()
        self.serial_no += 1
        mdf.tool_id  = 0
        mdf.missing     = 0
        self.variable += 1
        mdf.xyz[:] = np.array([self.variable]*3)
        mdf.ori[:] = np.array([self.variable]*4)# will work but need!!! reading modules to know the format of buffer
        #mdf.buffer[data.size:] = -1
        msg = CMessage(rc.MT_PLOT_POSITION)
        copy_to_msg(mdf, msg)
        self.mod.SendMessage(msg)
        print self.variable
        sys.stdout.write('|'); sys.stdout.flush()
        
        # now check for exit message
        in_msg = CMessage()
        rcv = self.mod.ReadMessage(msg, 0)
        if rcv == 1:
            hdr = msg.GetHeader()
            msg_type = hdr.msg_type
            dest_mod_id = hdr.dest_mod_id
            if msg_type == MT_EXIT:
                if (dest_mod_id == 0) or (dest_mod_id == self.mod.GetModuleID()):
                    print "Received MT_EXIT, disconnecting..."
                    self.daq_task.StopTask()
                    self.mod.SendSignal(rc.MT_EXIT_ACK)
                    self.mod.DisconnectFromMMM()
                    self.stop()
            elif msg_type == rc.MT_PING:
                respond_to_ping(self.mod, msg, 'RandomGen')
                
    def run(self):
        self.daq_task.StartTask()
        print "!"
        while True:
            pass

    def stop(self):
        self.daq_task.StopTask()
        self.daq_task.ClearTask()
        
if __name__ == "__main__":
    parser = ArgumentParser(description = 'Interface with NI DAQ hardware' \
        ' and emit DAQ_DATA messages')
    parser.add_argument(type=str, dest='config')
    parser.add_argument(type=str, dest='mm_ip', nargs='?', default='')
    args = parser.parse_args()
    print("Using config file=%s, MM IP=%s" % (args.config, args.mm_ip))
    rg = RandomGen(args.config, args.mm_ip)
