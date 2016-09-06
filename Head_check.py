import sys
import os
import logging
import time
import numpy as np
import wx
import threading
from argparse import ArgumentParser
from IPython.config.loader import PyFileConfigLoader

import PyDragonfly
from PyDragonfly import CMessage, MT_EXIT, copy_to_msg, copy_from_msg
from dragonfly_utils import respond_to_ping

import Dragonfly_config as rc
import quaternionarray as qa
import amcmorl_py_tools.vecgeom as vg
from amcmorl_py_tools.vecgeom import transformations as tf

from TrackedPoint import TrackedPoint as TP

class Head_check(object):
    def __init__(self, config_file, server):
        self.find_data()
        self.load_config(config_file)
        self.load_logging()
        self.setup_dragonfly(server)
        self.run()

    def find_data(self):
        app = wx.PySimpleApp()
        dialog = wx.FileDialog(None,  style=wx.FD_OPEN)
        if dialog.ShowModal() == wx.ID_OK:
            self.file_path = dialog.GetPath() 
        dialog.Destroy()
        app = 0
        #self.file_path = "C:\\Users\\amcmorl\\Dave25-07-16.txt"
        self.open_file(self.file_path)
    
 
    def open_file(self, file_name):
        with open(file_name, 'r') as calib:
            Right_Tragus = []
            Left_Tragus = []
            Nasion = []
            Cz = []
            lines = calib.readlines()
            for i, line in enumerate(lines):
                if 'Right Tragus' in line:
                    Right_Tragus.extend((lines[i+1], lines[i+2], lines[i+3]))
                if 'Left Tragus' in line:
                    Left_Tragus.extend((lines[i+1], lines[i+2], lines[i+3]))
                if 'Nasion' in line:
                    Nasion.extend((lines[i+1], lines[i+2], lines[i+3]))
                if 'Cz' in line:
                    Cz.extend((lines[i+1], lines[i+2], lines[i+3]))

            self.glasses_to_RT = TP(
                                    self._make_array(Right_Tragus, 1),
                                    self._make_array(Right_Tragus, 2),
                                    self._make_array(Right_Tragus, 0)
                                   )
            self.glasses_to_LT = TP(
                                    self._make_array(Left_Tragus, 1),
                                    self._make_array(Left_Tragus, 2),
                                    self._make_array(Left_Tragus, 0)
                                   )                       
            self.glasses_to_Nasion = TP(
                                    self._make_array(Nasion, 1),
                                    self._make_array(Nasion, 2),
                                    self._make_array(Nasion, 0)
                                   )
            self.glasses_to_cz = TP(
                                    self._make_array(Cz, 1),
                                    self._make_array(Cz, 2),
                                    self._make_array(Cz, 0)
                                   )

    def _make_array(self, arr, x): #x indexes array
        pos = arr[x].split()[-1]
        return np.array(pos.split(',')).astype(np.float)
     
    
    def load_config(self, config_file):
        cfg = PyFileConfigLoader(config_file)
        cfg.load_config()
        self.config = cfg.config
        
        # special casing for SAMPLE_GENERATED
        if (self.config.trigger == 'SAMPLE_GENERATED'):
            self.config.trigger_msg = rc.MT_SAMPLE_GENERATED
            self.config.trigger_mdf = rc.MDF_SAMPLE_GENERATED
        else:
            self.config.trigger_msg = \
                eval('rc.MT_' + self.config.trigger)
            self.config.trigger_mdf = \
                eval('rc.MDF_' + self.config.trigger)
        print "Triggering with", self.config.trigger
        print "TMS Mapping Collection: loading config"
        
        #self.ntools = len(self.config.tool_list)
        self.plate = self.config.tools.index('CB609')
        self.marker = self.config.tools.index('CT315')
        self.glasses = self.config.tools.index('ST568')
        self.pointer = self.config.tools.index('P717')
    
    def setup_dragonfly(self, server):
        self.mod = PyDragonfly.Dragonfly_Module(0, 0)
        self.mod.ConnectToMMM(server)
        self.mod.Subscribe(MT_EXIT)
        self.mod.Subscribe(rc.MT_PING)
        self.mod.Subscribe(rc.MT_POLARIS_POSITION)
        self.mod.Subscribe(rc.MT_HOTSPOT_POSITION)
        self.mod.Subscribe(rc.MT_TMS_TRIGGER)
        
        self.mod.SendModuleReady()
        print "TMS_Mapping_Collection: connected to dragonfly"
        
    def load_logging(self):
        log_file = os.path.normpath(os.path.join(self.config.config_dir, 'TMS_mapping_collection.log'))
        print "log file: " + log_file
        logging.basicConfig(filename=log_file, level=logging.DEBUG)
        logging.info(' ')
        logging.info(' ')
        logging.debug("**** STARTING UP ****")
        logging.info("  %s  " % time.asctime())
        logging.info("*********************")
    

    
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
                    respond_to_ping(self.mod, msg, 'Head_check')
                else:
                    self.process_message(msg)
    
    def process_message(self, in_msg):
        msg_type = in_msg.GetHeader().msg_type
        #print('? %d STATUS=%s TESTING=%s' % (msg_type, str(self.status), str(self.testing)))
        if msg_type == rc.MT_POLARIS_POSITION:
            # handling input message
            in_mdf = rc.MDF_POLARIS_POSITION()
            copy_from_msg(in_mdf, in_msg)
            if in_mdf.tool_id == (self.glasses + 1):
                positions = np.array(in_mdf.xyz[:])
                orientations = qa.norm(self.shuffle_q(np.array(in_mdf.ori[:])))
                self.find_pos_to_glasses(positions, orientations)

                
    def shuffle_q(self, q):
        return np.roll(q, -1, axis=0)
        
    def find_pos_to_glasses(self, glasses_position, glasses_orientation): #Saves 0, 0, 0 array to file when object called
        cz_pos, cz_rot = self.glasses_to_cz.get_pos(glasses_orientation, glasses_position)
        Nasion_pos, nasion_rot = self.glasses_to_Nasion.get_pos(glasses_orientation, glasses_position)
        LT_pos, LT_rot = self.glasses_to_LT.get_pos(glasses_orientation, glasses_position)
        RT_pos, RT_rot = self.glasses_to_RT.get_pos(glasses_orientation, glasses_position)
      
        print 'CZ: ', cz_pos
        print 'Nasion: ', Nasion_pos
        print 'LT: ', LT_pos
        print 'RT: ', RT_pos     


if __name__=="__main__":
    parser = ArgumentParser(description = 'Trial controller for TMS mapping')
    parser.add_argument(type=str, dest='config')
    parser.add_argument(type=str, dest='mm_ip', nargs='?', default='127.0.0.1:7111')
    args = parser.parse_args()
    frame = Head_check(args.config, args.mm_ip)