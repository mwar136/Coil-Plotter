import sys
import os
import logging
import time
import numpy as np

from IPython.config.loader import PyFileConfigLoader
from argparse import ArgumentParser

from PyDragonfly import Dragonfly_Module, MT_EXIT, CMessage, copy_to_msg, copy_from_msg
import Dragonfly_config as rc
from dragonfly_utils import respond_to_ping

from traits.api import HasTraits, Instance
from traitsui.api import View, Item
from mayavi.core.ui.api import SceneEditor, MlabSceneModel
from tvtk.api import tvtk
from mayavi import mlab, tools
import mayavi
import wx
import quaternionarray as qa

from TrackedPoint import TrackedPoint as TP


class PlotHead(HasTraits):
    scene = Instance(MlabSceneModel, ())

    # The layout of the panel created by Traits
    view = View(Item('scene', editor=SceneEditor(), resizable=True,
                    show_label=False),
                    resizable=True)

    def __init__(self, config_file, server, parent):
        HasTraits.__init__(self)
        self.count = 0
        self.parent = parent
        self.pointer_position = np.zeros((1,3))
        self.head_data = np.zeros((1,3))
        self.load_config(config_file)
        self.init_plot()
        self.setup_dragonfly(server)
    
    def load_config(self, config_file):
        cfg = PyFileConfigLoader(config_file)
        cfg.load_config()
        self.config = cfg.config
        self.filename = self.config.head_model
        self.plate = self.config.tools.index('CB609')
        self.marker = self.config.tools.index('CT315')
        self.glasses = self.config.tools.index('ST568')
        self.pointer = self.config.tools.index('P717')
        self.pointer_Ti = np.array(self.config.tool_list[self.pointer].Ti)
        self.pointer_Qi = qa.norm(np.array(self.config.tool_list[self.pointer].Qi))
        self.pointer_Ni = np.array(self.config.tool_list[self.pointer].Ni)
        self.pointer_Xi = self.pointer_Ni - self.pointer_Ti
        self.tp = TP(self.pointer_Qi, self.pointer_Ni, self.pointer_Ti)

    def init_plot(self):
        '''
        # create a window with 14 plots (7 rows x 2 columns)
        ## create a window with 8 plots (4 rows x 2 columns)
        reader = tvtk.OBJReader()
        reader.file_name = self.filename
        mapper = tvtk.PolyDataMapper()
        mapper.input = reader.output
        actor = tvtk.Actor()
        mapper.color_mode = 0x000000
        actor.mapper = mapper
        actor.orientation = (-90,180,0)
        self.scene.add_actor(actor)
        '''
        self.plot = mlab.plot3d(0,0,0, color=(0,0,1))
        self.plot2 = mlab.plot3d(0,0,0, color=(1,0,0))
        self.pl = self.plot.mlab_source
        self.pl2 = self.plot2.mlab_source
        
        self.timer = wx.Timer(self.parent)
        self.timer.Start(50)
        self.parent.Bind(wx.EVT_TIMER, self.timer_event)

        
    def process_message(self, msg):
        # read a Dragonfly message
        msg_type = msg.GetHeader().msg_type
        dest_mod_id = msg.GetHeader().dest_mod_id
        if  msg_type == MT_EXIT:
            if (dest_mod_id == 0) or (dest_mod_id == self.mod.GetModuleID()):
                print 'Received MT_EXIT, disconnecting...'
                self.mod.SendSignal(rc.MT_EXIT_ACK)
                self.mod.DisconnectFromMMM()
                return
        elif msg_type == rc.MT_PING:
            respond_to_ping(self.mod, msg, 'PlotHead')
        elif msg_type == rc.MT_POLARIS_POSITION:
            in_mdf = rc.MDF_POLARIS_POSITION()
            copy_from_msg(in_mdf, msg)
            positions = np.asarray(in_mdf.xyz[:])
            orientations = self.shuffle_q(np.asarray(in_mdf.ori[:]))
            if in_mdf.tool_id == (self.pointer + 1):
                Qf = qa.norm(orientations)
                Qr = qa.mult(Qf, qa.inv(self.pointer_Qi)).flatten()
                #find_nans(self.store_head, Qr, 'Qr')
                Tk = positions
                #find_nans(self.store_head, Tk, 'Tk')
                tip_pos = (qa.rotate(Qr, self.pointer_Xi) + Tk).flatten()
                self.pointer_position = np.append(self.pointer_position, (tip_pos[np.newaxis,:]), axis=0)
                #self.pl.reset(x=self.pointer_position[:,0], y=self.pointer_position[:,1], z=self.pointer_position[:,2])
                print ("old=", tip_pos)
                print ("new=", self.tp.get_pos(orientations, positions)[0])
               #elif in_mdf.tool_id == (self.glasses + 1):
            #    self.head_data = np.append(self.head_data, (head[np.newaxis,:]), axis=0)
            #    self.pl2.reset(x=self.head_data[:,0], y=self.head_data[:,1], z=self.head_data[:,2])
                
    def setup_dragonfly(self, server):
        subscriptions = [MT_EXIT, \
                         rc.MT_PING, \
                         rc.MT_POLARIS_POSITION]
        self.mod = Dragonfly_Module(0, 0)
        self.mod.ConnectToMMM(server)
        for sub in subscriptions:
            self.mod.Subscribe(sub)
        self.mod.SendModuleReady()
        print "Connected to Dragonfly at ", server
    
    def timer_event(self, parent):
        done = False
        sys.stdout.flush()
        while not done:
            msg = CMessage()
            rcv = self.mod.ReadMessage(msg, 0)
            if rcv == 1:
                self.process_message(msg)
            else:
                done = True
    
    def shuffle_q(self, q):
        return np.roll(q, -1, axis=0)

class MainWindow(wx.Frame):

    def __init__(self, parent, id, config, server):
        wx.Frame.__init__(self, parent, id, 'Mayavi in Wx')
        self.mayavi_view = PlotHead(config, server, self)
        # Use traits to create a panel, and use it as the content of this
        # wx frame.
        self.control = self.mayavi_view.edit_traits(
                        parent=self,
                        kind='subpanel').control
        self.Show(True)
                    
if __name__ == "__main__":
    parser = ArgumentParser(description = 'Real-time display of TMS Coil position')
    parser.add_argument(type=str, dest='config')
    parser.add_argument(type=str, dest='mm_ip', nargs='?', default='127.0.0.1:7111')
    args = parser.parse_args()
    print("Using config file=%s, MM IP=%s" % (args.config, args.mm_ip))
    #fig = mlab.figure()
    #PH= PlotHead(args.config, args.mm_ip)
    app = wx.PySimpleApp()
    frame = MainWindow(None, wx.ID_ANY, args.config, args.mm_ip)
    app.MainLoop()