import sys
import os
import logging
import time
import numpy as np
from argparse import ArgumentParser
from IPython.config.loader import PyFileConfigLoader


import PyDragonfly
from PyDragonfly import CMessage, MT_EXIT, copy_to_msg, copy_from_msg
from dragonfly_utils import respond_to_ping

import Dragonfly_config as rc
import quaternionarray as qa
import amcmorl_py_tools.vecgeom as vg

import vtk
from mayavi import mlab, tools
import mayavi
import threading

from TrackedPoint import TrackedPoint as TP
'''
To do:
Combine with HotspotLocator
'''
def find_nans(time, x, symb):
    if np.any(np.isnan(x)):
        print time, symb

class CoilPlotter (object):
    
    def __init__(self, config_file, mm_ip):
        self.plot_vertex_vec = np.array([-2, -3, 2.1])
        self.load_config(config_file)
        self.setup_dragonfly(mm_ip)
        self.get_frequency()
        self.current_map_data =  np.zeros((1,7))
        self.count=0
        self.run()
        
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
        print "CoilPlotter: loading config"
        #Getting tool message number
        self.plate = self.config.tools.index('CB609')
        self.marker = self.config.tools.index('CT315')
        self.glasses = self.config.tools.index('ST568')
        self.pointer = self.config.tools.index('P717')
        #Get tool P717 calibration values for pointer calculation
        self.pointer_Ti = np.array(self.config.tool_list[self.pointer].Ti)
        self.pointer_Qi = qa.norm(np.array(self.config.tool_list[self.pointer].Qi))
        self.pointer_Ni = np.array(self.config.tool_list[self.pointer].Ni)
        self.pointer_tp = TP(self.pointer_Qi, self.pointer_Ni, self.pointer_Ti)
        #Get location of obj file for head model
        
    def setup_dragonfly(self, mm_ip):
        self.mod = PyDragonfly.Dragonfly_Module(0, 0)
        self.mod.ConnectToMMM(mm_ip)
        self.mod.Subscribe(MT_EXIT)
        self.mod.Subscribe(rc.MT_PING)
        self.mod.Subscribe(rc.MT_HOTSPOT_POSITION) #Get coil HS position from HotspotLocator
        self.mod.Subscribe(rc.MT_POLARIS_POSITION) #Get position of glasses and pointer
        self.mod.Subscribe(rc.MT_TMS_TRIGGER) #Triggers capture of positions and orientation
        
        self.mod.SendModuleReady()
        print "CoilPlotter: connected to dragonfly"
    
   
    def get_frequency(self):
        # loop over receiving messages until we get a POLARIS_POSITION message
        # get a POLARIS_POSITION message, read sample_header.DeltaTime to get
        # message frequency
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
                    respond_to_ping(self.mod, msg, 'CoilPlotter')
                else:
                    msg_type = msg.GetHeader().msg_type
                    if msg_type == rc.MT_POLARIS_POSITION:
                        # handling input message
                        mdf = rc.MDF_POLARIS_POSITION()
                        copy_from_msg(mdf, msg)
                        self.fsamp = 1/mdf.sample_header.DeltaTime
                        if self.fsamp != 0:
                            break
                        
        self.user_start_calibrate()               
        # return 1 / DeltaTime from first POLARIS_POSITION msg
            
    def user_start_calibrate(self):
       #initiate calibration when tools in position
        while True:
            x = raw_input("Press enter to calibrate...")
            if not x:
                break
            print '.......'
        sys.stdout.write('starting in:')
        sys.stdout.write('5\n')
        sys.stdout.flush()
        time.sleep(1)
        sys.stdout.write('4\n')
        sys.stdout.flush()
        time.sleep(1)
        sys.stdout.write('3\n')
        sys.stdout.flush()
        time.sleep(1)
        sys.stdout.write('2\n')
        sys.stdout.flush()
        time.sleep(1)
        sys.stdout.write('1\n')
        sys.stdout.flush()
        time.sleep(1)
        sys.stdout.write('Calibrating...')
        self.create_storage()    
   
    def create_storage (self):
        self.store_head_pos = np.empty([5 * self.fsamp, 3])
        self.store_head_ori = np.empty([5 * self.fsamp, 4])
        self.store_glasses_pos = np.empty([5 * self.fsamp, 3])
        self.store_glasses_ori = np.empty([5 * self.fsamp, 4])
        self.store_head = 0
        self.store_glasses = 0
        self.calibrated = False
        self.set_collecting = False
        
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
                        break
                elif msg_type == rc.MT_PING:
                    respond_to_ping(self.mod, msg, 'CoilPlotter')
                elif (msg_type == rc.MT_POLARIS_POSITION) & (self.calibrated == False):
                    self.calibrate_head(msg)
                elif msg_type == rc.MT_TMS_TRIGGER:
                    self.set_collecting = True
                    self.got_coil = False
                    self.got_head = False
                else:
                    self.process_message(msg)
    
    def calibrate_head(self, in_msg):
        msg_type = in_msg.GetHeader().msg_type
        if msg_type == rc.MT_POLARIS_POSITION:
            # handling input message
            in_mdf = rc.MDF_POLARIS_POSITION()
            copy_from_msg(in_mdf, in_msg)
            positions = np.asarray(in_mdf.xyz[:])
            orientations = self.shuffle_q(np.asarray(in_mdf.ori[:]))
          
            #When arrays have been filled the calibration vector is generated
            if (
                (self.store_glasses >= self.store_glasses_pos.shape[0]) & 
                (self.store_glasses >= self.store_glasses_ori.shape[0]) & 
                (self.store_head >= self.store_head_pos.shape[0]) & 
                (self.store_head >= self.store_head_ori.shape[0])
                ):
                self.calibrating = False
                self.make_calibration_vector()
            #Pointer is measured from ball 1, pointer end must be calculated
            elif in_mdf.tool_id == (self.pointer + 1):
                if self.store_head < self.store_head_pos.shape[0]:
                    if np.any(np.isnan(positions)) == True:
                        raise Exception, 'nan present'
                    elif np.any(np.isnan(orientations)) == True:
                        raise Exception, 'nan present'
                    Qf = qa.norm(orientations) #Sometimes gets nan, source unknown
                    if np.any(np.isnan(Qf)):
                        print(self.store_head, 'Qf', orientations)
                    
                    #find_nans(self.store_head, Tk, 'Tk')
                    Cz_pos, Qr = self.pointer_tp.get_pos(orientations, positions)
                    #find_nans(self.store_head, Cz_pos, 'Cz')
                    self.store_head_pos[self.store_head, :] = Cz_pos
                    self.store_head_ori[self.store_head, :] = orientations
                    self.store_head += 1
            elif in_mdf.tool_id == (self.glasses + 1):
                if self.store_glasses < self.store_glasses_pos.shape[0]:
                    if np.any(np.isnan(positions)) == True:
                        raise Exception, 'nan present'
                    if np.any(np.isnan(orientations)) == True:
                        raise Exception, 'nan present'
                    self.store_glasses_pos[self.store_glasses, :] = positions
                    self.store_glasses_ori[self.store_glasses, :] = orientations
                    self.store_glasses += 1    
       
    def process_message(self, in_msg):
        msg_type = in_msg.GetHeader().msg_type
        if self.calibrated:
            if self.set_collecting:
                if (msg_type == rc.MT_HOTSPOT_POSITION) & (self.got_coil == False):
                    # handling input message
                    in_mdf = rc.MDF_HOTSPOT_POSITION()
                    copy_from_msg(in_mdf, in_msg)
                    self.current_vtail = np.array(in_mdf.xyz[:]) #Hotspot position
                    self.current_vhead = np.array(in_mdf.ori[:3]) #Vector head of coil, used to find ori
                    self.got_coil = True
                    
                elif (msg_type == rc.MT_POLARIS_POSITION) & (self.got_head == False):
                    # handling input message
                    in_mdf = rc.MDF_POLARIS_POSITION()
                    copy_from_msg(in_mdf, in_msg)
                    positions = np.array(in_mdf.xyz[:])
                    orientations = self.shuffle_q(np.array(in_mdf.ori[:]))
                    
                    if in_mdf.tool_id == (self.glasses + 1): 
                        # calculating output
                        self.head, Qr = self.tp.get_pos(orientations, positions)
                        print(self.head)
                        self.got_head = True
                       
                elif (self.got_head == True) & (self.got_coil == True):
                    plot_position = self.current_vtail - self.head + self.plot_vertex_vec
                    in_mdf = rc.MDF_POLARIS_POSITION()
                    out_mdf = rc.MDF_PLOT_POSITION()
                    copy_from_msg(in_mdf, in_msg)
                    out_mdf.xyz[:] = plot_position
                    out_mdf.ori[:] = np.append(self.current_vhead, 0)# Qk - coil active orientation
                    out_mdf.sample_header = in_mdf.sample_header
                    msg = CMessage(rc.MT_PLOT_POSITION)
                    copy_to_msg(out_mdf, msg)
                    self.mod.SendMessage(msg)
                    sys.stdout.write("C")
                    
                    self.count += 1
                    save_array = np.insert(np.concatenate(((self.current_vtail - self.head), self.current_vhead)), 0, self.count)
                    self.current_map_data = np.vstack((self.current_map_data, save_array))
                    self.got_coil = False
                    self.got_head = False
                    self.set_collecting = False
                    if self.count > 100:
                        location = raw_input("Finished! Where should it save?")
                        np.savetxt(str(location) +'.txt',self.current_map_data[1:], 
                                    delimiter=',', newline='/n')
                        mlab.savefig(str(location) + '.png', figure=self.fig)
                        mlab.close(self.fig)
                        self.count = 0
                        self.run()
            
    def make_calibration_vector(self):
        head_ori = qa.norm(self.store_head_ori.mean(axis=0))
        Ni        = self.store_head_pos.mean(axis=0)
        self.Qi   = qa.norm(self.store_glasses_ori.mean(axis=0))
        Ti        = self.store_glasses_pos.mean(axis=0)
        self.tp = TP(self.Qi, Ni, Ti)
        if ((np.any(np.isnan(head_ori))) == True or (np.any(np.isnan(Ni))) == True
        or (np.any(np.isnan(self.Qi))) == True or (np.any(np.isnan(Ti))) == True):
            sys.stdout.write("!!!!!!!! Calibration complete! !!!!!!!!!!!\n")
            self.user_start_calibrate()
            return
        msg_str_pos = "%.5e, " * 3
        msg_str_ori = "%.5e, " * 4
        sys.stdout.write('Cz orientation:    ')
        sys.stdout.write(msg_str_ori % (head_ori[0], head_ori[1], head_ori[2],\
                                    head_ori[3]) + "\n")
        sys.stdout.write('Cz position:       ')
        sys.stdout.write(msg_str_pos % (Ni[0], Ni[1], Ni[2]) + "\n")
        sys.stdout.write('Glasses orientation:     ')
        sys.stdout.write(msg_str_ori % (self.Qi[0], self.Qi[1], self.Qi[2], self.Qi[3]) + "\n")
        sys.stdout.write('Glasses position:        ')
        sys.stdout.write(msg_str_pos % (Ti[0], Ti[1], Ti[2]) + "\n")
        sys.stdout.write("********** Calibration complete! ***********\n")
        sys.stdout.flush()
        self.calibrated = True
        self.got_coil = False
        self.got_head = False
          
    def shuffle_q(self, q):
        return np.roll(q, -1, axis=0)

if __name__ == "__main__":
    parser = ArgumentParser(description = 'Interface with Polaris hardware' \
        ' and HOTSPOT LOCATOR, generate maps aznd output coil position file')
    parser.add_argument(type=str, dest='config')
    parser.add_argument(type=str, dest='mm_ip', nargs='?', default='')
    args = parser.parse_args()
    print("Using config file=%s, MM IP=%s" % (args.config, args.mm_ip))
    pdf = CoilPlotter(args.config, args.mm_ip)
    print "Finishing up"