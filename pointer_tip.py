import time
import sys
import platform
from ConfigParser import SafeConfigParser
import PyDragonfly
from PyDragonfly import CMessage, MT_EXIT, copy_to_msg, copy_from_msg
from dragonfly_utils import respond_to_ping
from argparse import ArgumentParser
from dragonfly_utils import respond_to_ping
from IPython.config.loader import PyFileConfigLoader
import Dragonfly_config as rc
import numpy as np
from TrackedPoint import TrackedPoint as TP
import quaternionarray as qa

class pointer_tip(object):
    def __init__(self, config_file, server):
        self.load_config(config_file)
        self.setup_dragonfly(server)
        self.run()

    def load_config(self, config_file):
        cfg = PyFileConfigLoader(config_file)
        cfg.load_config()
        self.config = cfg.config
        print "HotspotLocator: loading config"      
        #self.ntools = len(self.config.tool_list)
        self.plate = self.config.tools.index('CB609')
        self.marker = self.config.tools.index('CT315')
        self.glasses = self.config.tools.index('ST568')
        self.pointer = self.config.tools.index('P717')
        self.pointer_Ti = np.array(self.config.tool_list[self.pointer].Ti)
        self.pointer_Qi = qa.norm(np.array(self.config.tool_list[self.pointer].Qi))
        self.pointer_Ni = np.array(self.config.tool_list[self.pointer].Ni)
        self.pointer_tp = TP(self.pointer_Qi, self.pointer_Ni, self.pointer_Ti)
        
    def setup_dragonfly(self, server):
        self.mod = PyDragonfly.Dragonfly_Module(0, 0)
        self.mod.ConnectToMMM(server)
        self.mod.Subscribe(MT_EXIT)
        self.mod.Subscribe(rc.MT_PING)
        self.mod.Subscribe(rc.MT_POLARIS_POSITION)
        self.mod.SendModuleReady()
        print "Connected to Dragonfly at", server
        
        
    def run(self):
        while True:
            msg = CMessage()
            rcv = self.mod.ReadMessage(msg, 0.001)
            if rcv == 1:
                msg_type = msg.GetHeader().msg_type
                dest_mod_id = msg.GetHeader().dest_mod_id
                if  msg_type == MT_EXIT:
                    if (dest_mod_id == 0) or (dest_mod_id == self.mod.GetModuleID()):
                        print 'Received MT_EXIT, disconnecting...'
                        self.mod.SendSignal(rc.MT_EXIT_ACK)
                        self.mod.DisconnectFromMMM()
                        break;
                elif msg_type == rc.MT_PING:
                    respond_to_ping(self.mod, msg, 'pointer_tip')
                else:
                    self.process_message(msg) 
      
      
    def process_message(self, in_msg):
        # read a Dragonfly message
        msg_type = in_msg.GetHeader().msg_type
        if msg_type == rc.MT_POLARIS_POSITION:
            # handling input message
            in_mdf = rc.MDF_POLARIS_POSITION()
            copy_from_msg(in_mdf, in_msg)
            positions = np.array(in_mdf.xyz[:])
            orientations = qa.norm(self.shuffle_q(np.array(in_mdf.ori[:])))
            if in_mdf.tool_id == (self.pointer + 1):
                pointer_pos, Qr = self.pointer_tp.get_pos(orientations, positions)
                print pointer_pos
                
  

    def shuffle_q(self, q):
        return np.roll(q, -1, axis=0)    
        '''
        while True:
            if (time.time() - self.delta_time_calc) % 2 == 0:

                out_mdf = rc.MDF_HOTSPOT_POSITION()
                self.serial_no += 1
                out_mdf.sample_header.SerialNo  = self.serial_no
                out_mdf.sample_header.Flags     = 0
                out_mdf.sample_header.DeltaTime = (1. / 5)
                out_mdf.xyz[:] = self.tail
                out_mdf.ori[:] = np.append(self.head, 0)# Qk - coil active orientation
                msg = CMessage(rc.MT_PLOT_POSITION)
                copy_to_msg(out_mdf, msg)
                self.mod.SendMessage(msg)
                sys.stdout.write("C")
                
            if (time.time() - self.delta_time_calc) % 2 == 1:
                out_mdf = rc.MDF_POLARIS_POSITION()
                self.serial_no += 1
                out_mdf.sample_header.SerialNo  = self.serial_no
                out_mdf.sample_header.Flags     = 0
                out_mdf.sample_header.DeltaTime = (1. / 5)
                out_mdf.xyz[:] = self.tail
                out_mdf.ori[:] = np.append(self.head, 0)# Qk - coil active orientation
                out_mdf.tool_id = 3
                msg = CMessage(rc.MT_PLOT_POSITION)
                copy_to_msg(out_mdf, msg)
                self.mod.SendMessage(msg)
                sys.stdout.write("C")
        '''    
            
if __name__ == "__main__":
    parser = ArgumentParser(description = 'Send SAMPLE_GENERATED messages' \
        ' under a range of conditions')
    parser.add_argument(type=str, dest='config')
    parser.add_argument(type=str, dest='mm_ip', nargs='?', default='')
    args = parser.parse_args()
    print("Using  config file=%s, MM IP=%s" % (args.config, args.mm_ip))
    itm = pointer_tip(args.config, args.mm_ip)