
import sys
if sys.version_info[0] == 3:
    if sys.version_info[1] <= 7:
        from time import gmtime, strftime, time, sleep, clock
    else:
        from time import gmtime, strftime, time, sleep
        from time import perf_counter as clock
else:
    from time import gmtime, strftime, time, sleep, clock

from numpy import nan

sys.path.append('/Users/femto-13/All-Projects-on-femto/LaserLab/Software/')

class DAQ(object):
    freq = nan
    running = False
    def __init__(self, client):
        self.running = True
        self.buffer_shape = (25600, 10)#8192000)
        self.client = client

    def init(self):
        from circular_buffer_numpy.circular_buffer import CircularBuffer
        client = self.client
        self.circular_buffer = CircularBuffer(shape = self.buffer_shape, dtype = 'int16')
        self.packet_shape = client.packet_shape.read().data
        self.packet_length = self.packet_shape[0]
        self.freq = int(client.freq.read().data[0])
        self.packet_buffer_length = int(self.buffer_shape[0]/self.packet_length)
        self.start_time = None


    def start(self):
        from _thread import start_new_thread
        start_new_thread(self.run,())

    def stop(self):
        self.running = False

    def run_once(self):
        data = self.get_data()
        if self.start_time == None:
            self.start_time = time() - data.shape[1]/self.freq

        self.circular_buffer.append(data)
        self.packet_pointer = int(((self.circular_buffer.pointer+1)/self.packet_length)-1)
        self.g_packet_pointer = int(((self.circular_buffer.g_pointer+1)/self.packet_length)-1)

    def get_data(self):
        client = self.client
        while client.queue_length.read().data < 128:
            sleep(0.1)
        data = client.data.read().data.reshape((self.packet_shape))
        return data

    def run(self):
        from time import sleep
        while self.running:
            self.run_once()

    def get_packet_ij(self,i,j): #return from i to j
        length = self.circular_buffer.shape[0]
        while i > length:
            i-= length
        while j > length:
            j-= length

        if j >= i:
            #print(i,j)
            result = self.circular_buffer.get_N((j-i+1)*self.packet_length,(j+1)*self.packet_length-1)
        else:
            result = nan
        return result

    def get_ring_buffer_N(self,N,pointer):
        """
        """
        while pointer >= (self.circular_buffer.shape[0]):
            pointer = int(pointer - self.circular_buffer.shape[0])
        res = self.circular_buffer.get_N(N, pointer)
        return res

if __name__ == '__main__':
    pass
