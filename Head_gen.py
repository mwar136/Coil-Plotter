import time
import sys
import platform
from ConfigParser import SafeConfigParser
import PyDragonfly
from PyDragonfly import CMessage, MT_EXIT, copy_to_msg, copy_from_msg
from dragonfly_utils import respond_to_ping
from argparse import ArgumentParser
from dragonfly_utils import respond_to_ping
import Dragonfly_config as rc
import numpy as np

class SampleGenerator(object):
    def __init__(self, server):
        self.serial_no = 2
        self.freq = 50 # Hz
        self.serial_no = 2
        self.tail = np.zeros((3))
        self.head = np.zeros((3))
        self.setup_dragonfly(server)
        self.run()

    def setup_dragonfly(self, server):
        self.mod = PyDragonfly.Dragonfly_Module(0, 0)
        self.mod.ConnectToMMM(server)
        self.mod.Subscribe(MT_EXIT)
        self.mod.Subscribe(rc.MT_PING)
        self.mod.SendModuleReady()
        print "Connected to Dragonfly at", server
        
        
    def run(self):
        self.delta_time_calc = time.time() #time.time()
        while True:
            if (time.time() - self.delta_time_calc) % 2 == 0:

                self.tail[0] = self.tail[0] + 1
                self.head[1] = self.head[1] + 1
                out_mdf = rc.MDF_PLOT_POSITION()
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


if __name__ == "__main__":
    parser = ArgumentParser(description = 'Send SAMPLE_GENERATED messages' \
        ' under a range of conditions')
    parser.add_argument(type=str, dest='mm_ip', nargs='?', default='')
    args = parser.parse_args()
    print("Using MM IP=%s" % (args.mm_ip))
    itm = SampleGenerator(args.mm_ip)