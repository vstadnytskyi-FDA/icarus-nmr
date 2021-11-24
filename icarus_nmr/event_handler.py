#!/bin/env python
"""
The Event Detector LL for the High Pressure Apparatus
author: Valentyn Stadnytskyi
dates: June 09 2018 - November 16 2018

1.0.0 - the improved copy from the old class from the older SL
1.1.0 - Bugs fixed and Fully tested version that works with SL server! Exciting
      - EvalEvent function was changed. The list is cleared at the end of analysis.

Events:
two numbers: first D channel number and second direction 0(down) and 1(up)
00 - D0 goes low
01 - D0 goes high
10 - D1 goes low
11 - D1 goes high
20 - D2 goes low
21 - D2 goes high
and so on

3 digital numbers starting with 100 are analog events:
100 - analog event of high pressure pump stroke

version 3.0.0 - added tube_length and medium
 - 4.0.0 - majopr upgrade to Python 3 and minor restructuring

"""


import sys

from ubcs_auxiliary.advsleep import precision_sleep

import traceback

import sys
if sys.version_info[0] == 3:
    if sys.version_info[1] <= 7:
        from time import gmtime, strftime, time, sleep, clock
    else:
        from time import gmtime, strftime, time, sleep
        from time import perf_counter as clock
else:
    from time import gmtime, strftime, time, sleep, clock

from logging import debug,info,warn,error
from numpy import nan, std, inf, nanmean, nanstd, nonzero, zeros, nanargmax, nanargmin, nanmin, nanmax, asarray
import platform
import pickle
import traceback
import scipy.stats
from scipy.interpolate import UnivariateSpline

from ubcs_auxiliary.saved_property import DataBase, SavedProperty
from ubcs_auxiliary.threading import new_thread
from pdb import pm


prefix = platform.node()+'_'
EVENT_CODE = {}
EVENT_CODE['D0_GOES_LOW']=EVENT_CODE_D0_GOES_LOW = 0
EVENT_CODE_D0_GOES_HIGH = 1
EVENT_CODE_D1_GOES_LOW = 10
EVENT_CODE_D1_GOES_HIGH = 11
EVENT_CODE_D2_GOES_LOW = 20
EVENT_CODE_D2_GOES_HIGH = 21
EVENT_CODE_D3_GOES_LOW = 30
EVENT_CODE_D3_GOES_HIGH = 31
EVENT_CODE_D4_GOES_LOW = 40
EVENT_CODE_D4_GOES_HIGH = 41
EVENT_CODE_D5_GOES_LOW = 50
EVENT_CODE_D5_GOES_HIGH = 51
EVENT_CODE_D6_GOES_LOW = 60
EVENT_CODE_D6_GOES_HIGH = 61

EVENT_CODE_A_PUMP_STROKE = 100

EVENT_CODE_T_PERIOD = 200
EVENT_CODE_T_3HZ_UPDATE = 300
EVENT_CODE_T_10HZ_UPDATE = 301
EVENT_CODE_T_TIMEOUT = 399

EVENTS_ORDER_ANALYSIS = [0,1,10,11,20,21,30,31,40,41,50,51,60,61,100,200,300,301,999]


BIT_HP_PUMP = 0b1
BIT_VALVE1 = 0b10
BIT_VALVE2 = 0b100
BIT_VALVE3 = 0b1000
BIT_LOG = 0b10000
BIT_5 = 0b100000
BIT_6 = 0b1000000


class Handler(object):
    db = DataBase(root = 'TEMP', name = 'event_detector')
    pr_serial_number = '00000'
    ppLogFolder ='log/'
    history_buffer_size  =  1000000 #1000000
    event_buffer_shape=  (100,2)

    timeout_period_time = 30.0

    depressure_before_time =  20.0
    depressure_after_time = 100.0
    pressure_before_time = 20.0
    pressure_after_time = 100.0



    selected_pressure_units = 'kbar'
    user_units = {'kbar': 6.894756709891046e-05, 'atm': 1/14.696, 'psi': 1}
    #self.selected_pressure_units = 'kbar'
    scale_top_valve1 = (220./50)#(50/6.894756709891046e-05) #(1*6.894756709891046e-05)*(14267/8192) # 200 psi per 10 Volts per 2**15 bits
    scale_bot_valve1 = (220./50)#(50/6.894756709891046e-05) # 200 psi per 10 Volts per 2**15 bits
    scale_top_valve2 = (220./50)#(50/6.894756709891046e-05) # 200 psi per 10 Volts per 2**15 bits
    scale_bot_valve2 = (220./50)#(50/6.894756709891046e-05) # 200 psi per 10 Volts per 2**15 bits

    coeff_sample_pressure = 100000.0
    coeff_target_pressure = 0.92

    bit_HPpump = 0b1
    bit_valve1 = 0b10
    bit_valve2 = 0b100
    bit_valve3 = 0b1000
    bit_log = 0b10000

    medium = 'none'
    tube_length = 100.0


    counters_pump = 0
    counters_depressurize = 0
    counters_pressurize = 0
    counters_valve3 = 0
    counters_logging = 0
    counters_D5 = 0
    counters_D6 = 0
    counters_period = 0
    counters_delay = 0
    counters_pump_stroke = 0
    counters_timeout = 0
    counters_periodic_update = 0
    counters_periodic_update_cooling = 0

    save_trace_to_a_file = False

    email_dic_packed = ''

    periodic_udpate_hz = 3
    periodic_udpate_cooling_hz = 10


    save_data_period = 0

    slow_leak_threshold = -20.0
    slow_leak_threshold_counter = 5

    def __init__(self, daq, client = None):
        """
        to create an instance
        """
        self.name = prefix + 'EventDetector'
        self.daq = daq
        self.client = client
        self.logging_state = 0
        self.save_trace_to_a_file = False
        bit_to_kbar_coeff = 2**-15*10**5*6.894756709891046e-05
        kbar_to_ul_coeff = (0.500/2.5) # 0.500 mL / 2.5kbar
        self.cooling_coefficient = 4000*60*60*bit_to_kbar_coeff*kbar_to_ul_coeff
        # 4000 ticks/second * 60 seconds/min * 60 min/hour * 500 uL / 2.5 kbar
        self.buffer_shape = (25600,10)#8192000)

        self.current_dio = 127

        self.io_push_queue = None
        self.io_pull_queue = None

        self.threads = {}

    def init(self):
        """
        initialize the instance of the class:
        - create event buffer (as circular buffer)
            - pointer in the DAQ buffer
            - event integer
        - create variables

        Parameters
        ----------

        Returns
        -------

        Examples
        --------
        >>> self.init()
        """
        from numpy import zeros
        from circular_buffer_numpy.circular_buffer import CircularBuffer
        from time import time

        self.circular_buffer = CircularBuffer(shape = self.buffer_shape, dtype = 'int16')

        self.packet_buffer_length = int(self.buffer_shape[0]/self.daq .packet_length)
        self.event_buffer_shape = (1000,3) #100000 will be ~ 2 weeks assuming 5 events per sequence(1 min).
        self.event_buffer = CircularBuffer(shape = self.event_buffer_shape, dtype = 'int64')

        self.events_list = [] #the list of events that need evaluation.

        self.running = False #thread is running flag

        #
        self.bit_HPpump = BIT_HP_PUMP
        self.bit_valve1 = BIT_VALVE1
        self.bit_valve2 = BIT_VALVE2
        self.bit_valve3 = BIT_VALVE3
        self.bit_log = BIT_LOG

        self.packet_pointer = 0 #TODO What is this variable?
        self.g_packet_pointer = 0 #TODO What is this variable?

        self.user_units = {'kbar': 2/29007.55, 'atm': 1/14.696, 'psi': 1}
        self.selected_pressure_units = 'kbar'
        #self.pumpCounter = 0
        #self.scaleTopValve1 = 50000
        #self.scaleBotValve1 = 50000
        #self.scaleTopValve2 = 100000
        #self.scaleBotValve2 = 100000
        #self.scaleValve1 = 50000.0
        #self.scaleValve2 = 45000.0
        #self.coeff_target_pressure = 45000.0

        self.coeff_sample_pressure = 100000.0


        self.medium = 'mineral spirits'


        if self.medium == 'mineral spirits':
            self.pressure_difference_percentage_threshold = 0.1
        elif self.medium == 'water':
            self.pressure_difference_percentage_threshold = 0.05



        std_err_dic = {}
        std_err_dic[b'std_err'] = 0
        std_err_dic[b'x'] = 0
        std_err_dic[b'y'] = 0
        std_err_dic[b'Sx'] = 0
        std_err_dic[b'Sx2'] = 0
        std_err_dic[b'Sxy'] = 0
        std_err_dic[b'Sy'] = 0
        std_err_dic[b'Sy2'] = 0
        std_err_dic[b'N'] = 0
        std_err_dic[b'Delta'] = 0
        std_err_dic[b'a'] = 0
        std_err_dic[b'b'] = 0
        std_err_dic[b'Sigma2'] = 0
        self.std_err_dic = std_err_dic


        ###

        self.depressurize_data = []
        dic = {}
        dic[b'fallTime_0'] = nan
        dic[b'pulseWidthDepressure_0'] = nan
        dic[b'tSwitchDepressure_0'] = nan
        dic[b'pDepre_0'] = nan
        dic[b'gradientDepressure_0'] = nan
        dic[b'tSwitchDepressureEst_0'] = nan
        dic[b'gradientDepressureEst_0'] = nan
        dic[b'fallTime_1'] = nan
        dic[b'pulseWidthDepressure_1'] = nan
        dic[b'tSwitchDepressure_1'] = nan
        dic[b'pDepre_1'] = nan
        dic[b'gradientDepressure_1'] = nan
        dic[b'depressurize_data'] = zeros((4000,10), dtype = 'int16')

        #the append function is done twice so analysis of two different consequetive events can be saved. This is especially important when visualizing data in pre and depre charts.
        self.depressurize_data.append(dic)
        self.depressurize_data.append(dic)

        self.pressurize_data = []
        dic = {}
        dic[b'riseTime_0'] = nan
        dic[b'pulseWidthPressure_0'] = nan
        dic[b'tSwitchPressure_0'] = nan
        dic[b'pPre_0'] = nan
        dic[b'gradientPressure_0'] = nan
        dic[b'tSwitchPressureEst_0'] = nan
        dic[b'gradientPressureEst_0'] = nan
        dic[b'riseTime_1'] = nan
        dic[b'pulseWidthPressure_1'] = nan
        dic[b'tSwitchPressure_1'] = nan
        dic[b'pPre_1'] = nan
        dic[b'gradientPressure_1'] = nan
        dic[b'pressurize_data'] = zeros((4000,10), dtype = 'int16')

        #the append function is done twice so analysis of two different consequetive events can be saved. This is especially important when visualizing data in pre and depre charts.
        self.pressurize_data.append(dic)
        self.pressurize_data.append(dic)

        self.period_event = {b'period':nan,
                           b'delay':nan,
                           b'pressurize_width':nan,
                           b'depressurize_width':nan,
                           b'pump_width':nan,
                           b'data': {b'y_max':zeros((10,4000), dtype = 'int16')
                                    ,b'y_min':zeros((10,4000), dtype = 'int16'),
                                     b'x':zeros((4000,), dtype = 'int16')}
                            }

        #dictionary of indices for all last events. For examlpe: b'D0' shows when was the last D0 event.
        self.last_event_index = {b'D0':0,
                                 b'D1':0,
                                 b'D10':0,
                                 b'D11':0,
                                 b'D20':0,
                                 b'D21':0,
                                 b'D30':0,
                                 b'D31':0,
                                 b'D40':0,
                                 b'D41':0,
                                 b'D50':0,
                                 b'D51':0,
                                 b'D60':0,
                                 b'D61':0,
                                 b'A100':0, #pump stroke event
                                 b'A200':0, #period event
                                 b'A300':0, #3 Hz periodic update
                                 b'A301':0, #10 Hz periodic update
                                 b'A999':0  #timeout event
                                 }
        self.exp_start_time = 0

        #duration of pulses: Pump, depressurize, etc and distance between two identical events period, pump_stroke, etc.
        self.last_event_width = {b'pump':0,
                            b'depressurize':0,
                            b'pressurize':0,
                            b'valve3':0,
                            b'logging':0,
                            b'D5':0,
                            b'D6':0,
                            b'period':0,
                            b'delay':0,
                            b'timeout':0,
                            b'periodic_update':0,
                            b'periodic_update_cooling':0,
                            b'pump_stroke':0,
                                 }


        # TODO: Write description for this counter dictionary
        self.counters_global = {b'pump':self.counters_pump,
                    b'depressurize':self.counters_depressurize,
                    b'pressurize':self.counters_pressurize,
                    b'valve3':self.counters_valve3,
                    b'logging':self.counters_logging,
                    b'D5':self.counters_D5,
                    b'D6':self.counters_D6,
                    b'period':self.counters_period,
                    b'delay':self.counters_delay,
                    b'timeout':self.counters_timeout,
                    b'periodic_update':self.counters_periodic_update,
                    b'periodic_update_cooling':self.counters_periodic_update_cooling,
                    b'pump_stroke':self.counters_pump_stroke,
                    b'emergency': 0} #emergency counter for leak detection

        # TODO: Write description was this counter (current) dictionary
        self.counters_current= {b'pump':0,
                    b'depressurize':0,
                    b'pressurize':0,
                    b'valve3':0,
                    b'logging':0,
                    b'D5':0,
                    b'D6':0,
                    b'period':0,
                    b'delay':0,
                    b'timeout':0,
                    b'periodic_update':0,
                    b'periodic_update_cooling':0,
                    b'pump_stroke':0,
                    b'emergency': 0} #emergency counter for leak detection

        ###Chi2 analysis section
        self.std_err_dic = {b'std_err':0,
                       b'x':0,
                       b'y':0,
                       b'Sx':0,
                       b'Sx2':0,
                       b'Sxy':0,
                       b'Sy':0,
                       b'Sy2':0,
                       b'N':0,
                       b'Delta':0,
                       b'a':0,
                       b'b':0,
                       b'Sigma2':0
                       }

        self.fail_value = -1.0

        # auxiliary circular buffers
        self.slow_leak_buffer = CircularBuffer(shape = (1000,3), dtype = 'float')
        self.pump_stroke_buffer = CircularBuffer(shape = (100,3), dtype = 'float')
        self.estimated_leak_buffer = CircularBuffer(shape = (100,3), dtype = 'float')

        self.slow_leak_flag = False
        self.last_full_slow_leak_buffer = self.slow_leak_buffer.buffer[:,:0]

        self.emergency_shutdown_flag = False

        # Cooling calculations sections
        import os
        from icarus_nmr import event_handler
        cooling_master_tck = pickle.load( open( os.path.split(event_handler.__file__)[0]+"/files/cooling_master_curve_restricted_50.pickle", "rb" ) , encoding='latin1')
        self.cooling_master_func = UnivariateSpline._from_tck(cooling_master_tck._eval_args)
        bit_to_kbar_coeff = 2**-15*10**5*6.894756709891046e-05
        kbar_to_ul_coeff = (500/2.5) # 500uL/2.5kbar
        self.cooling_coefficient = 4000*60*60*bit_to_kbar_coeff*kbar_to_ul_coeff # 4000 per second * 60 seconds * 60 minutes * bit to kbar * kbar to ul -> leak in uL per hour

        self.corrections = {}
        self.corrections[b'offset tSwitchDepressure'] = 2.6*4
        self.corrections[b'offset tSwitchPressure'] = 3.95*4
        self.corrections[b'multiplier gradientDepressure'] = 1/2.0
        self.corrections[b'multiplier gradientPressure'] = 1/1.86

        self.bit3_meas_dic = {}

        self.history_init()

        for i in range(10):
            self.daq.run_once()

    def reset_to_factory_setting(self):
        """
        run once at the very beginning to setup up parameters in the settings file

        Parameters
        ----------

        Returns
        -------

        Examples
        --------
        >>> self.reset_to_factory_setting()
        """
        self.ppLogFolder = 'log/'
        self.depressure_before_time = 5.0
        self.depressure_after_time = 100.0
        self.pressure_before_time = 5.0
        self.pressure_after_time = 300.0
        self.coeff_target_pressure = 0.895
        self.coeff_sample_pressure = 100000.0
        self.scaleTopValve1 = 100000.0
        self.scaleBotValve1 = 100000.0
        self.scaleTopValve2 = 200000.0
        self.scaleBotValve2 = 200000.0

        self.user_units = {'psi': 1, 'atm': 0.06804572672836146, 'kbar': 6.89475728e-5}
        self.selected_pressure_units = 'kbar'
        self.event_buffer_shape = (2,100)
        self.history_buffer_size = 100000
        self.save_trace_to_a_file = False

        self.counters_global = {b'pump':0,
                            b'depressurize':0,
                            b'pressurize':0,
                            b'valve3':0,
                            b'logging':0,
                            b'D5':0,
                            b'D6':0,
                            b'period':0,
                            b'pump_stroke':0}

        self.bit_HPpump = 0b1 #bit representation of high-pressure pump valve
        self.bit_valve1 = 0b10 #bit representation of depressurization valve
        self.bit_valve2 = 0b100 #bit representation of rpessurization valve
        self.bit_valve3 = 0b1000 #bit representation of unused 3rd valve
        self.bit_log = 0b10000 #bit representation of logging bit

        self.time_last_pump_pulse = time() #creates variable for the last pump pulse time


    def start(self):
        """
        starts event detector thread only if self.running is False.
        To prevent multiple threads from running

        Parameters
        ----------

        Returns
        -------

        Examples
        --------
        >>> self._start()
        """
        if self.running:
            warning('The event detector thread is already running')
        else:
            self.threads['running'] = new_thread(self.run)

    def run(self):
        """
        function that runs in a separate thread

        Parameters
        ----------

        Returns
        -------

        Examples
        --------
        >>> self._run()
        """
        from time import time

        self.running = True

        while self.running and self.daq_running:
           self.run_once()
        self.running = False
        if self.daq_running == False:
            self.stop()

    def run_once(self):
        from time import time
        t = time()
        ###compares its' own packet pointer with DAQ packet pointer
        ###if local packet poitner is smaller than DAQ, means that there are packets that need to be analyzed

        def distance(back = 0, front = 0,size = 1):
            if front > back:
                distance = front - back
            elif front < back:
                distance = size + front - back
            elif front == back:
                distance = 0
            return distance

        if distance(back = self.packet_pointer,front = self.daq_packet_pointer,size = self.daq_packet_buffer_length) > 6:

            self.run_once_once()
            if len(self.events_list) > 0:
                self.evaluate_events()
                self.events_list = []
        else:
            self.daq.run_once()

        #info(self.packet_pointer,self.daq_packet_pointer)


    def run_once_once(self):

        import numpy as np
        #get packet to analyse. however, if the transition happens between packets
        #the algorith will not detect it.
        #Hence, I need to grab 2 packets to analyse
        #first packet + 1 point from the next packet.
        packet_pointer = self.packet_pointer
        g_packet_pointer = self.g_packet_pointer
        self.daq.run_once()
        new_packet = np.copy(self.get_daq_packet_ij(packet_pointer,packet_pointer+1)[:self.daq_packet_length+1,:])
        info(f'new packet shape {new_packet.shape}')
        info(f'packet_pointer: {packet_pointer}')
        info(f'packet_pointer: {self.daq_packet_length}')

        self.events_list += self.find_dio_events(data = new_packet)
        self.events_list +=  self.find_aio_events(data = new_packet)
        self.events_list +=  self.find_time_events(data = new_packet)
        if self.packet_pointer == self.daq_packet_buffer_length-1:
            self.packet_pointer = 0
        else:
            self.packet_pointer += 1
            self.g_packet_pointer += 1

        ###Sort Detected events according to a specified algorithm.
        self.events_list = self.sort_events(self.events_list)
        ###Evaluation of the detected events



    def stop(self):
        """
        orderly stop of the event detector
        """
        del self

    def kill(self):
        """
        orderly exit and delete the instance

        Parameters
        ----------

        Returns
        -------

        Examples
        --------
        >>> self.kill()
        """
        del self

    def get_event_pointer(self):
        try:
            return self.event_buffer.pointer
        except Exception:
            error(traceback.format_exc())
            return nan
    def set_event_pointer(self,value):
        pass
    event_pointer = property(get_event_pointer,set_event_pointer)


###############################################################################
###  Event Finders and Evaluators
###############################################################################

    def find_aio_events(self, data , local = False):
        """
        analyses the a packet(data) for the analog events.
        INPUTS:
        data - packet (numpy array)
        local - flag for local test purposes (boolean)
        OUTPUTS:
        list of events - every event is saved as a dictionary
                        {b'channel: 'code', b'value': 'value', b'index': 'index in the array'}

        supported codes:
        -  timeout
        -  A100 - analog 100 stands for pump stroke

        returns Analog inout/output events in the datastrean

        Parameters
        ----------
        data:  (numpy array)
            numpy array (Nx10) of data
        local: boolean
            Optional flag

        Returns
        -------

        Examples
        --------
        >>>
        """
        from numpy import zeros, nanmean
        from time import time

        lst_result = []

        ###LOCAL DATA ULPOAD for testing purposes
        packet_pointer = self.packet_pointer
        g_packet_pointer = self.g_packet_pointer
        length = data.shape[0]+g_packet_pointer*self.daq_packet_length

        ### ANALYSIS OF PUMP STROKE EVENT
        t = length - self.last_event_index[b'A100']- self.daq_freq*2
        info('analog events data', data.shape)
        flag, index, value = self.analyse_pump_event(data = data)
        if t > 0:
            gated_on = True
        else:
            gated_on = False
        if flag:
            idx = index + (packet_pointer+1)*self.daq_packet_length + 1
            g_idx = index + (g_packet_pointer+1)*self.daq_packet_length + 1
            evt_code = 100
            if gated_on:
                lst_result.append({b'channel' : 'pump_stroke',

                                   b'value': value ,
                                   b'index' : idx,
                                   b'global_index' :
                                   g_idx, b'evt_code': evt_code}) #local dictionary for evaluate_events
            arr = zeros((3,1))
            arr[0] = g_idx
            arr[1] = value
            arr[2] = int(gated_on)
            self.pump_stroke_buffer.append(arr)

        return lst_result

    def find_time_events(self, data, local = False):
        """
        analyses the a packet(data) for the analog events.
        INPUTS:
        data - packet (numpy array)
        local - flag for local test purposes (boolean)
        OUTPUTS:
        list of events - every event is saved as a dictionary
                        {b'channel: 'code', b'value': 'value', b'index': 'index in the array'}

        supported codes:
        -  timeout
        -  A100 - analog 100 stands for pump stroke

        returns Analog inout/output events in the datastrean

        Parameters
        ----------
        data:  (numpy array)
            numpy array (Nx10) of data
        local: boolean
            Optional flag

        Returns
        -------

        Examples
        --------
        >>>
        """
        from numpy import zeros, nanmean
        from time import time

        lst_result = []
        ###LOCAL DATA ULPOAD for testing purposes

        length = data.shape[0]+self.g_packet_pointer*self.daq_packet_length
        packet_pointer = self.packet_pointer
        g_packet_pointer = self.g_packet_pointer
        ###TIMEOUT analog event
        t = length - self.last_event_index[b'A200'] - self.timeout_period_time*self.daq_freq
        if t>0:
            evt_code = 999
            idx = (packet_pointer+1)*self.daq_packet_length - int(t)+1
            g_idx = (g_packet_pointer+1)*self.daq_packet_length - int(t)+1
            lst_result.append({b'channel' : 'timeout',
                               b'index' : idx,
                               b'global_index' : g_idx,
                               b'evt_code': evt_code})
            evt_code = 200
            idx = (packet_pointer+1)*self.daq_packet_length - int(t)+1
            g_idx = (g_packet_pointer+1)*self.daq_packet_length - int(t)+1
            lst_result.append({b'channel' : 'period',
                               b'index' : idx,
                               b'global_index' : g_idx,
                               b'evt_code': evt_code})


        ### 3 HZ update event
        t = length - self.last_event_index[b'A300']- int(self.daq_freq/self.periodic_udpate_hz)
        if t > 0:
            idx = (packet_pointer+1)*self.daq_packet_length - int(t)+1
            g_idx = (g_packet_pointer+1)*self.daq_packet_length - int(t)+1
            evt_code = 300
            lst_result.append({b'channel' : 'periodic_update',
                               b'index' : idx,
                               b'global_index' : g_idx,
                               b'evt_code': evt_code}) #local dictionary for evaluate_events

        ### 10 HZ update event
        t = length - self.last_event_index[b'A301']- int(self.daq_freq/self.periodic_udpate_cooling_hz)
        if t > 0:
            idx = (packet_pointer+1)*self.daq_packet_length - int(t)+1
            g_idx = (g_packet_pointer+1)*self.daq_packet_length - int(t)+1
            evt_code = 301
            lst_result.append({b'channel' : 'periodic_update_cooling',
                               b'index' : idx,
                               b'global_index' : g_idx,
                               b'evt_code': evt_code}) #local dictionary for evaluate_events

        return lst_result

    def parse_binary_number(self,value = 0):
        """
        takes an integer and converts it to 8 bit representation as an array.
        If float number is passed, it will be converted to int.
        """
        from ubcs_auxiliary.numerical import binary_to_array
        return parse_binary_number(value = value)

    def parse_binary(self,value = 0):
        """parses the difference between before and after integers
        and returns an array with with changes in binaries:
        0 - no change
        1 - went high
        -1 - went low
        array index stands for bit
        bit 0 1 2 3 4 5 6 7 instead of standard binary representation
        where the lowest bit comes last
        """
        from ubcs_auxiliary.numerical import binary_to_array
        return binary_to_array(value = value)



    def find_dio_events(self, data, packetPointer = 0, local = False):
        """
        look for the events in the digital channel of the data array.
        The function will retrieve data from the circular buffer.
        However, for testing purposes an array can be passed for analysis.

        The digital events codes:
        DXY: X - channel; Y - 0(down) 1(up)

        A special period event is generated when D2 goes low as well.
        """
        from numpy import std, zeros, isnan, nan,nonzero, nanstd, sum
        lst_result = []
        #create an array with 2 elements
        #for appending to the event circular buffer

        packet_pointer = self.packet_pointer
        g_packet_pointer = self.g_packet_pointer

        data1 = data[:-1,9]
        data2 = data[1:,9]
        diff = data2-data1
        if nanstd(diff) != 0 and ~isnan(nanstd(diff)):
            indices = nonzero(diff!=0)
            debug('indices %r' % indices)
            for idx in indices[0]:
                before = int(data[idx,9])
                after = int(data[idx+1,9])
                bin_array = self.parse_binary(value = after) - self.parse_binary(value = before)
                evn_idx = idx+packet_pointer*self.daq_packet_length
                g_evn_idx = idx+g_packet_pointer*self.daq_packet_length
                debug(bin_array)
                for dio in range(7):
                    value =  bin_array[dio]
                    if int(value) == -1:
                        str_val = 'low'
                        value = 0 # to have it competable with the rest of the code the high->low transition has to be 0
                    elif int(value) == 1:
                        str_val = 'high'
                    else:
                        str_val = 'none'
                    if str_val != 'none':
                        lst_result.append({b'channel' : 'D'+str(dio),
                                           b'value': str_val,
                                           b'index' : evn_idx,
                                           b'global_index' : g_evn_idx,
                                           b'evt_code': int(dio*10+int(value))})
                        #If detect D2 goes low(event D20), create and event A200 - period event.
                        if int(dio*10+int(value)) == 20:
                                lst_result.append({b'channel' : 'period',
                                                   b'index' : evn_idx,
                                                   b'global_index' : g_evn_idx,
                                                   b'evt_code': 200})
        return lst_result


    def sort_events(self,lst_in = []):
        """sorts input list of events according to events_order_list hard coded inside of this function
        """
        events_order_list = EVENTS_ORDER_ANALYSIS
        lst_out = []
        #steps through the events_order_list and checks if this event is present in the input list
        for item in events_order_list:
            for item_in in lst_in:
                if item_in[b'evt_code'] == item:
                    lst_out.append(item_in)

        #appends all events with unknown event codes at the end.
        for item_in in lst_in:
            if item_in[b'evt_code'] not in events_order_list:
                lst_out.append(item_in)
        return lst_out

    def evaluate_events(self):
        """
        This function evaluates events
        it goes through the list self.DIOEventsLst of the dictionaries
        to evaluate events. The list is sorted by the index (occurance)
        in the circular buffer of the DAQ. The last entries are always
        analog events.

        Analysis is divided into several steps:
        checking D1 and D2 for:
        1) get data from the circular buffer
        2) calculate pStart or pEnd: static pressures at the start and end
        3) update pulseDepressure pulsePressure counter: counter
        4) get pulseWidthDepressure or pulseWidthPressure: digital pulse width
        5) calculate fall or rise time: time to go from one pressure to another
        6) tSwitchDepressure or tSwitchPressure: how long did it take between digital change and actual analog change
        checking D0 for logging on/off (pulled low/pulled high)
        checking D4 if it went low
        checking D6 if it went low
        """
        from numpy import size, where, gradient,median, nanmedian, nan, zeros,\
             isnan, nonzero, argmax,argmin,argwhere, copyto, \
             empty_like, abs, copy, mean, round

        from time import time
        array = zeros((3,1))
        freq = self.daq.freq
        units = self.user_units[self.selected_pressure_units]

        # stepping through events and analysing them one by one.
        for dic in self.events_list:
            temp_dic = {}
            array[0] = dic[b'index']
            array[1] = dic[b'global_index']
            array[2] = dic[b'evt_code']
            self.event_buffer.append(data = array)

            if dic[b'channel'] == 'D0' and dic[b'value'] == 'low':

                self.counters_global[b'pump'] += 1
                self.counters_current[b'pump'] += 1
                self.last_event_index[b'D0'] = dic[b'global_index']
                #this event is not used for anything but still gets identified
                #to keep the code more transparent


            elif dic[b'channel'] == 'D0' and dic[b'value'] == 'high':
                self.last_event_index[b'D1'] = dic[b'global_index']

                self.last_event_width[b'pump'] =  (dic[b'global_index'] -self.last_event_index[b'D0'])/self.daq.freq

                #this event is not used for anything but still gets identified
                #to keep the code more transparent


            elif dic[b'channel'] == 'D1' and dic[b'value'] == 'low': #Depressurize event D1 goes low
                self.counters_global[b'depressurize'] += 1
                self.counters_current[b'depressurize'] += 1
                self.last_event_index[b'D10'] = dic[b'global_index']

                before_idx = int(self.depressure_before_time*self.daq_freq/1000.0)
                after_idx = int(self.depressure_after_time*self.daq_freq/1000.0)

                data = self.get_ring_buffer_N(N = before_idx+after_idx, pointer = dic[b'index']+after_idx)

                depressurize_dict = {}
                depressurize_dict[b'depressurize_data'] = data

                try:
                    units = self.user_units[self.selected_pressure_units]
                    depressurize_dict = {**depressurize_dict,**self.analyse_depressure_event(data = data, channel = 0)}
                    debug('depressurize_dict channel 0 = %r' %(depressurize_dict))
                    ###convert to user friendly units
                    depressurize_dict[b'tSwitchDepressure_0'] = depressurize_dict[b'tSwitchDepressure_0']*1000.0/self.daq.freq
                    depressurize_dict[b'fallTime_0'] = depressurize_dict[b'fallTime_0']*1000.0/self.daq.freq
                    depressurize_dict[b'pDepre_0'] = depressurize_dict[b'pDepre_0']*units*self.coeff_sample_pressure*2.0**-15
                    depressurize_dict[b'gradientDepressure_0'] = depressurize_dict[b'gradientDepressure_0']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15
                    depressurize_dict[b'tSwitchDepressureEst_0'] = depressurize_dict[b'tSwitchDepressureEst_0']*1000.0/self.daq.freq
                    depressurize_dict[b'gradientDepressureEst_0'] = depressurize_dict[b'gradientDepressureEst_0']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15

                except Exception:
                    depressurize_dict[b'fallTime_0'] = nan
                    depressurize_dict[b'tSwitchDepressure_0'] = nan
                    depressurize_dict[b'pDepre_0'] = nan
                    depressurize_dict[b'gradientDepressure_0'] = nan
                    depressurize_dict[b'tSwitchDepressureEst_0'] = nan
                    depressurize_dict[b'gradientDepressureEst_0'] = nan
                    error(traceback.format_exc())


                try:
                    units = self.user_units[self.selected_pressure_units]
                    depressurize_dict = {**depressurize_dict,**self.analyse_depressure_event(data = data, channel = 1)}

                    depressurize_dict[b'tSwitchDepressure_1'] = depressurize_dict[b'tSwitchDepressure_1']*1000.0/self.daq.freq
                    depressurize_dict[b'fallTime_1'] = depressurize_dict[b'fallTime_1']*1000.0/self.daq.freq
                    depressurize_dict[b'pDepre_1'] = depressurize_dict[b'pDepre_1']*units*self.coeff_sample_pressure*2.0**-15
                    depressurize_dict[b'gradientDepressure_1'] = depressurize_dict[b'gradientDepressure_1']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15

                except Exception:
                    depressurize_dict[b'fallTime_1'] = nan
                    depressurize_dict[b'tSwitchDepressure_1'] = nan
                    depressurize_dict[b'pDepre_1'] = nan
                    depressurize_dict[b'gradientDepressure_1'] = nan
                    error(traceback.format_exc())


                self.depressurize_data.append(depressurize_dict)
                self.depressurize_data.pop(0)
                if self.save_trace_to_a_file and (self.logging_state == 1 or self.logging_state == 11):
                    self.data_log_to_file(data, name = 'depre')

                #slow leak buffer analysis and later reset
                self.slow_leak_module()


                msg = ''
                msg+='event index = %r \n' %dic[b'global_index']
                msg+='self.slow_leak_flag = %r \n' %self.slow_leak_flag
                #info(msg)

                self.push_depressurize_event()
                before0 = 0 #self.history_buffers[b'pPre_after_0'].buffer[3,self.history_buffers[b'pPre_after_0'].pointer]
                before1 = 0 #self.history_buffers[b'pPre_after_1'].buffer[3,self.history_buffers[b'pPre_after_1'].pointer]
                temp_dic = {b'tSwitchDepressure_0':depressurize_dict[b'tSwitchDepressure_0'],
                            b'tSwitchDepressure_1':depressurize_dict[b'tSwitchDepressure_1'],
                            b'tSwitchDepressureEst_0':depressurize_dict[b'tSwitchDepressureEst_0'],
                            b'gradientDepressure_0':depressurize_dict[b'gradientDepressure_0'],
                            b'gradientDepressure_1':depressurize_dict[b'gradientDepressure_1'],
                            b'gradientDepressureEst_0':depressurize_dict[b'gradientDepressureEst_0'],
                            b'fallTime_0':depressurize_dict[b'fallTime_0'],
                            b'fallTime_1':depressurize_dict[b'fallTime_1'],
                            b'pDepre_0':depressurize_dict[b'pDepre_0'],
                            b'pDepre_1':depressurize_dict[b'pDepre_1'],
                            b'pDiff_0':depressurize_dict[b'pDepre_0'] - before0,
                            b'pDiff_1':depressurize_dict[b'pDepre_1'] - before1,
                            b'depressure_valve_counter':self.counters_global[b'depressurize'],
                            }



            elif dic[b'channel'] == 'D1' and dic[b'value'] == 'high':
                self.last_event_index[b'D11'] = dic[b'global_index']
                self.last_event_width[b'depressurize'] =  round((dic[b'global_index'] -self.last_event_index[b'D10'])*1000/self.daq.freq,2)
                #icarus_SL.inds.depressurize_pulse_width = self.last_event_width[b'depressurize']

                temp_dic = {b'depressure_pulse_width':self.last_event_width[b'depressurize']
                            }
                self.history_append(dic= temp_dic,event_code = 11, global_pointer = dic[b'global_index'], period_idx = self.counters_current[b'period'])



            elif dic[b'channel'] == 'D2' and dic[b'value'] == 'low':
                self.last_event_width[b'delay'] = round((dic[b'global_index']-self.last_event_index[b'D10'])*1000/self.daq.freq,2)
                #icarus_SL.inds.delay_width = self.last_event_width[b'delay']
                self.last_event_index[b'D20'] = dic[b'global_index']
                self.counters_global[b'pressurize'] += 1
                self.counters_current[b'pressurize'] += 1



                ###Find the beggining of the pressurize valve pulse
                before_idx = int(self.pressure_before_time*self.daq_freq/1000.0)
                after_idx = int(self.pressure_after_time*self.daq_freq/1000.0)

                data = self.get_ring_buffer_N(N = before_idx+after_idx, pointer = dic[b'index']+after_idx)

                pressurize_dict = {}
                pressurize_dict[b'pressurize_data'] = data

                try:
                    pressurize_dict = {**pressurize_dict,**self.analyse_pressure_event(data = data, channel = 0, freq = self.daq.freq)}

                    ###Convert to user friendly units
                    pressurize_dict[b'riseTime_0'] = pressurize_dict[b'riseTime_0']*(1000/freq)
                    pressurize_dict[b'tSwitchPressure_0'] = pressurize_dict[b'tSwitchPressure_0']*(1000/freq)
                    pressurize_dict[b'pPre_0'] = pressurize_dict[b'pPre_0']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15
                    pressurize_dict[b'gradientPressure_0'] = pressurize_dict[b'gradientPressure_0']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15
                    pressurize_dict[b'tSwitchPressureEst_0'] = pressurize_dict[b'tSwitchPressureEst_0']*(1000/freq)
                    pressurize_dict[b'gradientPressureEst_0'] = pressurize_dict[b'gradientPressureEst_0']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15


                except Exception:
                    error(traceback.format_exc())
                    pressurize_dict[b'riseTime_0'] = nan
                    pressurize_dict[b'tSwitchPressure_0'] = nan
                    pressurize_dict[b'pPre_0'] = nan
                    pressurize_dict[b'gradientPressure_0'] = nan
                    pressurize_dict[b'tSwitchPressureEst_0'] = nan
                    pressurize_dict[b'gradientPressureEst_0'] = nan

                try:
                    pressurize_dict = {**pressurize_dict,**self.analyse_pressure_event(data = data, channel = 1, freq = self.daq.freq)}

                    ###Convert to user friendly units
                    pressurize_dict[b'riseTime_1'] = pressurize_dict[b'riseTime_1']*(1000/freq)
                    pressurize_dict[b'tSwitchPressure_1'] = pressurize_dict[b'tSwitchPressure_1']*(1000/freq)
                    pressurize_dict[b'pPre_1'] = pressurize_dict[b'pPre_1']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15
                    pressurize_dict[b'gradientPressure_1'] = pressurize_dict[b'gradientPressure_1']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15
                except Exception:
                    error(traceback.format_exc())
                    pressurize_dict[b'riseTime_1'] = nan
                    pressurize_dict[b'tSwitchPressure_1'] = nan
                    pressurize_dict[b'pPre_1'] = nan
                    pressurize_dict[b'gradientPressure_1'] = nan


                self.pressurize_data.append(pressurize_dict)
                self.pressurize_data.pop(0)

                self.push_pressurize_event()

                temp_dic = {b'tSwitchPressure_0':pressurize_dict[b'tSwitchPressure_0'],
                            b'tSwitchPressure_1':pressurize_dict[b'tSwitchPressure_1'],
                            b'tSwitchPressureEst_0':pressurize_dict[b'tSwitchPressureEst_0'],
                            b'gradientPressure_0':pressurize_dict[b'gradientPressure_0'],
                            b'gradientPressure_1':pressurize_dict[b'gradientPressure_1'],
                            b'gradientPressureEst_0':pressurize_dict[b'gradientPressureEst_0'],
                            b'riseTime_0':pressurize_dict[b'riseTime_0'],
                            b'riseTime_1':pressurize_dict[b'riseTime_1'],
                            b'pPre_0':pressurize_dict[b'pPre_0'],
                            b'pPre_1':pressurize_dict[b'pPre_1'],
                            b'delay':self.last_event_width[b'delay'],
                            b'pressure_valve_counter':self.counters_global[b'pressurize']
                            }
                self.history_append(dic= temp_dic,event_code = 20, global_pointer = dic[b'global_index'], period_idx = self.counters_current[b'period'])

                if self.save_trace_to_a_file and (self.logging_state == 1 or self.logging_state == 11):
                    self.data_log_to_file(data, name = 'pre')



            elif dic[b'channel'] == 'D2' and dic[b'value'] == 'high':
                ### if digital 2 goes high; the pressurize valve is closed;
                self.last_event_index[b'D21'] = dic[b'global_index']
                self.last_event_width[b'pressurize'] =  round((dic[b'global_index'] -self.last_event_index[b'D20'])*1000/self.daq.freq,2)
                #icarus_SL.inds.pressurize_pulse_width = self.last_event_width[b'pressurize']

                #10 ms of data 16 ms shifted from the event
                after_idx = int(10*self.daq_freq/1000.0)
                shift_idx = int(16*self.daq_freq/1000.0)


                data = self.get_ring_buffer_N(N = after_idx, pointer = dic[b'index']+after_idx+shift_idx)
                units = self.user_units[self.selected_pressure_units]
                after0 = mean(data[5,:])*units*self.coeff_sample_pressure*2.0**-15
                after1 = mean(data[6,:])*units*self.coeff_sample_pressure*2.0**-15
                temp_dic = {b'pPre_after_0':after0,
                            b'pPre_after_1':after1,
                            b'pressure_pulse_width':self.last_event_width[b'pressurize']}

                self.history_append(dic= temp_dic,event_code = 21, global_pointer = dic[b'global_index'], period_idx = self.counters_current[b'period'])
                self.counters_global[b'periodic_update'] = 0
                self.counters_current[b'periodic_update'] = 0


                self.slow_leak_flag = True



            elif dic[b'channel'] == 'D3' and dic[b'value'] == 'low':
                """
                unused bit goes low
                """
                self.counters_global[b'valve3'] += 1
                self.counters_current[b'valve3'] += 1
                self.last_event_index[b'D30'] = dic[b'global_index']



            elif dic[b'channel'] == 'D3' and dic[b'value'] == 'high':
                """
                unused bit 3 goes high
                """
                self.last_event_index[b'D31'] = dic[b'global_index']
                self.last_event_width[b'valve3'] =  (dic[b'global_index'] -self.last_event_index[b'D30'])/self.daq.freq
                #get data from N points up to the pointer
                data = self.get_ring_buffer_N(N = int(self.last_event_width[b'valve3']*self.daq.freq) , pointer = self.last_event_index[b'D31'])

                #log into a log file
                temp_dic[b'meanbit3'] = mean(data[:,5])
                self.history_append(dic = temp_dic,
                                          event_code = 31,
                                          global_pointer = dic[b'global_index'],
                                          period_idx = self.counters_current[b'period']
                                          )
                #save to a file
                if self.save_trace_to_a_file and (self.logging_state == 1 or self.logging_state == 11):
                    self.data_log_to_file(data, name = 'meanbit3')



            elif dic[b'channel'] == 'D4' and dic[b'value'] == 'low':
                """
                logging bit goes low
                """
                self.counters_global[b'logging'] += 1
                self.counters_current[b'logging'] += 1
                self.last_event_index[b'D40'] = dic[b'global_index']
                self.set_logging_state(value = 1) # 11 stands for True but created by pulling the pin low
                #msg = 'D4 went low. Logging is initiated and log folder %r is created' % (get_ring_buffer_N)
                #self.logging_permanent_log_append(message = msg)

            elif dic[b'channel'] == 'D4' and dic[b'value'] == 'high':
                """
                logging bit goes high
                """
                self.last_event_index[b'D41'] = dic[b'global_index']
                self.last_event_width[b'logging'] =  (dic[b'global_index'] - self.last_event_index[b'D40'])/self.daq.freq


                #msg = 'D4 went high. Logging is turned off and logging into the log folder %r is over' % (self.logFolder)
                #self.logging_permanent_log_append(message = msg)
                self.set_logging_state(value = 0)  # 10 stands for False but created by pulling the pin high


            elif dic[b'channel'] == 'D5' and dic[b'value'] == 'low':
                self.counters_global[b'D5'] += 1
                self.counters_current[b'D5'] += 1
                self.last_event_index[b'D50'] = dic[b'global_index']
                #this event is not used for anything but still gets identified
                #to keep the code more transparent

            elif dic[b'channel'] == 'D5' and dic[b'value'] == 'high':
                self.last_event_index[b'D51'] = dic[b'global_index']
                self.last_event_width[b'D5'] =  (dic[b'global_index'] -self.last_event_index[b'D50'])/self.daq.freq

                #this event is not used for anything but still gets identified
                #to keep the code more transparent

            elif dic[b'channel'] == 'D6' and dic[b'value'] == 'low':
                self.counters_global[b'D6'] += 1
                self.counters_current[b'D6'] += 1
                self.last_event_index[b'D60'] = dic[b'global_index']
                #this event is not used for anything but still gets identified
                #to keep the code more transparent


            elif dic[b'channel'] == 'D6' and dic[b'value'] == 'high':
                self.last_event_index[b'D61'] = dic[b'global_index']
                self.last_event_width[b'D6'] =  (dic[b'global_index'] -self.last_event_index[b'D60'])/self.daq.freq

                #this event is not used for anything but still gets identified
                #to keep the code more transparent
                pass

            elif dic[b'channel'] == 'pump_stroke':

                ###check for pump stroke frequency fault event: start
                new = dic[b'global_index']
                last = self.last_event_index[b'A100']
                if self.fault_pump_stroke_frequency(distance = 4):
                    self.warn_value[b'pump_stroke_counter'] += 1
                    self.warn_index[b'pump_stroke_counter'] = self.counters_current[b'period']
                else:
                    self.warn_value[b'pump_stroke_counter'] = 0
                fault_lst = self.check_for_faults(names = [b'pump_stroke_counter'])
                self.evaluate_faults(fault_lst = fault_lst)
                ###check for pump stroke frequency fault event: end

                self.last_event_width[b'pump_stroke'] =  (dic[b'global_index'] - self.last_event_index[b'A100'])/self.daq.freq
                self.last_event_index[b'A100'] = dic[b'global_index']
                self.counters_global[b'pump_stroke'] += 1
                self.counters_current[b'pump_stroke'] += 1
                self.push_pump_event()

                self.logtime = time()
                data = self.get_ring_buffer_N(N = 2000, pointer = dic[b'index']+1000)
                if self.save_trace_to_a_file and (self.logging_state == 1 or self.logging_state == 11):
                    self.data_log_to_file(data[0,:],name = 'pump')



                self.history_append(dic= {b'pump_stroke':self.counters_global[b'pump_stroke']},
                                          event_code = 100,
                                          global_pointer = dic[b'global_index'],
                                          period_idx = self.counters_current[b'period'])



            elif dic[b'channel'] == 'period':
                self.last_event_width[b'period'] =  round((dic[b'global_index'] - self.last_event_index[b'A200'])/self.daq.freq,5)
                self.last_event_index[b'A200'] = dic[b'global_index']
                data = self.get_ring_buffer_N(N = int(self.last_event_width[b'period']*self.daq.freq), pointer = dic[b'index'])
                self.period_event[b'data'] = self.bin_data(data = data, num_of_bins = 300)
                self.counters_global[b'period'] += 1
                self.counters_current[b'period'] += 1
                temp_dic[b'period'] = self.last_event_width[b'period']
                self.period_event[b'period'] = self.last_event_width[b'period']
                self.period_event[b'pressurize_width'] = self.last_event_width[b'pressurize']
                self.period_event[b'depressurize_width'] = self.last_event_width[b'depressurize']
                self.period_event[b'delay'] = self.last_event_width[b'delay']
                self.push_new_period(value = self.period_event)

            elif dic[b'channel'] == 'periodic_update':
                self.last_event_width[b'periodic_update'] =  (dic[b'global_index'] - self.last_event_index[b'A300'])/self.daq.freq
                self.last_event_index[b'A300'] = dic[b'global_index']
                self.counters_global[b'periodic_update'] += 1
                self.counters_current[b'periodic_update'] += 1

                self.push_target_pressure()
                self.push_sample_pressure()
                self.push_digital_state()

            elif dic[b'channel'] == 'periodic_update_cooling':
                self.last_event_width[b'periodic_update_cooling'] =  (dic[b'global_index'] - self.last_event_index[b'A301'])/self.daq.freq
                self.last_event_index[b'A301'] = dic[b'global_index']
                self.counters_global[b'periodic_update_cooling'] += 1
                self.counters_current[b'periodic_update_cooling'] += 1

                # if self.slow_leak_flag:
                #     arr = zeros((3,1))
                #     arr[0] = dic[b'global_index']-self.last_event_index[b'D20']
                #     arr[1] = self.target_pressure
                #     arr[2] = self.sample_pressure
                #     if self.slow_leak_buffer.pointer > 1:
                #         sample_pressure = mean(self.slow_leak_buffer.buffer[2,:self.slow_leak_buffer.pointer])
                #         new_pressure = self.sample_pressure
                #         ratio = self.fault_pressure_drop(pressure_vector = sample_pressure, new_value = new_pressure)
                #         self.warn_value[b'pressure_drop'] = ratio
                #         fault_lst = self.check_for_faults(names = [b'pressure_drop'])
                #         self.evaluate_faults(fault_lst = fault_lst)
                #     self.slow_leak_buffer.append(arr)


            elif dic[b'channel'] == 'timeout':
                """

                """
                #(1) Calculate pressure at the end of the period. Calculate difference between
                before_idx = int(self.pressure_before_time*self.daq_freq/1000.0)
                after_idx = int(self.pressure_after_time*self.daq_freq/1000.0)
                data = self.get_ring_buffer_N(N = after_idx, pointer = dic[b'index']+after_idx)
                units = self.user_units[self.selected_pressure_units]
                after0 = mean(data[5,:])*units*self.coeff_sample_pressure*2.0**-15
                after1 = mean(data[6,:])*units*self.coeff_sample_pressure*2.0**-15
                temp_dic = {}
                #before0 = #self.history_buffers[b'pPre_after_0'].buffer[3,self.history_buffers[b'pPre_after_0'].pointer]
                #before1 = #self.history_buffers[b'pPre_after_1'].buffer[3,self.history_buffers[b'pPre_after_1'].pointer]
                # self.slow_leak_module()
                # temp_dic = {
                #             b'pPre_after_0':after0,
                #             b'pPre_after_1':after1,
                #             b'pDepre_0':after0,
                #             b'pDepre_1':after1,
                #             b'pDiff_0':after0 - before0,
                #             b'pDiff_1':after1 - before1,
                #             b'leak_value':float(self.estimated_leak_buffer.get_last_N(1)[2])
                #             }
                #(2) reset periodic update_counter
                self.counters_global[b'periodic_update'] = 0
                self.counters_current[b'periodic_update'] =0
                self.slow_leak_flag = True

                self.last_event_width[b'timeout'] =  (dic[b'global_index'] - self.last_event_index[b'A999'])/self.daq.freq
                self.last_event_index[b'A999'] = dic[b'global_index']

                self.counters_global[b'timeout'] += 1
                self.counters_current[b'timeout'] += 1

                temp_dic[b'period'] = self.last_event_width[b'timeout']



                self.history_append(dic = temp_dic,
                                          event_code = 999,
                                          global_pointer = dic[b'global_index'],
                                          period_idx = self.counters_current[b'period']
                                          )

        self.update_counters_for_persistent_property() #makes this code competable with Friedrich's persistent_property module that doesn't support dictionaries
        self.events_list = []





################################################
######## Push events section
################################################
    ### Input-Output controller section
    def io_push(self,io_dict = None):
        """
        a wrapper that takes care of write command to the io module

        Parameters
        ----------
        io_dict :: dictionary
            a string name of the variable

        Returns
        -------

        Examples
        --------
        >>> self.io_push()
        """
        if self.io_push_queue is not None:
            self.io_push_queue.put(io_dict)

    def io_pull(self, io_dict):
        """
        a wrapper that takes care of 'read' command to the io module

        Parameters
        ----------
        name :: string
            a string name of the variable
        value :: object
            the new value of the variable to be read from the io module

        Returns
        -------

        Examples
        --------
        >>> self.io_pull()
        """
        if self.io_push_queue is not None:
            for key, value in io_dict.items:
                info(f'received update to {key} to change to {value}')

    def push_target_pressure(self,value = None):
        from numpy import nanmedian, median, copy
        import scipy.stats
        if value == None:
            beforeIdx = int(self.depressure_before_time*self.daq_freq/1000.0)
            from_point = self.last_event_index[b'A300']-400
            to_point = self.last_event_index[b'A300']

            data = copy(self.get_ring_buffer_N(N = 400, pointer = from_point))

            target_pressure = scipy.stats.mode(data[:,0])[0][0]
            value = target_pressure*self.coeff_target_pressure
        else:
            value = value*self.coeff_target_pressure
        self.io_push({'target_pressure':value})


    def push_sample_pressure(self,value = None):
        import scipy
        from numpy import nanmedian, median, copy

        if value is None:
            beforeIdx = int(self.depressure_before_time*self.daq_freq/1000.0)
            from_point = self.last_event_index[b'A300']-400
            to_point = self.last_event_index[b'A300']

            data = copy(self.get_ring_buffer_N(N = 400, pointer = from_point))

            sample_pressure = scipy.stats.mode(data[:,5])[0][0]
            value = sample_pressure
        else:
            value = value
        self.io_push(io_dict = {'sample_pressure':value})

    def push_depressurize_event(self):
        """
        function that aggregates all information needed
        """
        import numpy as np
        if len(self.depressurize_data)>0:
            data = self.depressurize_data[0]
            self.io_push(io_dict = {'table_time_to_switch_depre':data[b'tSwitchDepressure_0']})
            self.io_push(io_dict = {'table_fall_slope':data[b'fallTime_0']})
            self.io_push(io_dict = {'table_valve_counter_depre':self.counters_global[b'depressurize']})
            def chart_one(x,y):
                """
                charting function that takes x and y
                """
                xs_font = 10
                s_font = 12
                m_font = 16
                l_font = 24
                xl_font = 32

                import io
                from matplotlib.figure import Figure
                from matplotlib import pyplot
                from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg
                from scipy import stats
                figure = Figure(figsize=(7.68,2.16),dpi=100)#figsize=(7,5))
                axes = figure.add_subplot(1,1,1)
                t1 = time()
                from numpy import nonzero, zeros,nan, ones, argwhere, mean, nanmean, arange
                from scipy import stats

                units = self.user_units[self.selected_pressure_units]
                dataPlot = y.T
                x = (arange(len(dataPlot[0,:])))/(4000/1000.0)
                samplePre0 = dataPlot[5,:] #sample0
                samplePre1 = dataPlot[6,:] #sample1
                depreLower=dataPlot[1,:] #depressure lower
                depreUpper=dataPlot[2,:] #depressure upper
                target=dataPlot[0,:]
                pulse = zeros((len(dataPlot[9,:]),))
                pulse_light = zeros((len(dataPlot[9,:]),))
                for i in range(len(pulse)):
                    if dataPlot[9,i] & BIT_VALVE1 != 0:
                        pulse[i] = 1
                    else:
                        pulse[i] = 0
                for i in range(len(pulse_light)):
                    if dataPlot[9,i] & BIT_VALVE2 != 0:
                        pulse_light[i] = 1
                    else:
                        pulse_light[i] = 0

                target = target*0 + stats.mode(dataPlot[0,:]).mode


                axes.plot(x,units*self.coeff_sample_pressure*samplePre0*2.0**-15, color = 'red', marker = 'o', markersize = 3 )
                # if icarus_AL.advance_view_flag:
                #     axes.plot(x,units*icarus_AL.coeff_sample_pressure*samplePre1*2.0**-15, color = 'orangered', marker = 'o', markersize = 3 )
                axes.plot(x,units*42860.0*pulse_light,color = 'lightblue')
                axes.plot(x,units*42860.0*pulse,color = 'g')
                axes.plot(x,self.scale_top_valve1*depreUpper*2.0**-15, color = 'darkcyan')
                axes.plot(x,self.scale_bot_valve1*depreLower*2.0**-15, color = 'darkmagenta')
                axes.plot(x,units*79600.0*target*self.coeff_target_pressure*2.0**-15,color = 'black',linestyle = '--')
                #axes[0].legend(loc=1,fontsize='x-small')

                axes.set_title("Last Depressurize Event",fontsize=m_font, color = 'g')
                axes.set_xlabel("Time (ms)",fontsize=m_font)
                axes.set_ylabel("Pressure ("+self.selected_pressure_units+")",fontsize=m_font)
                axes.tick_params(axis='y', which='both', labelleft=True, labelright=False, labelsize = m_font)

                axes.grid(True)

                figure.tight_layout()
                return figure

            def figure_to_array(figure):
                from io import BytesIO
                from PIL.Image import open
                from numpy import asarray
                figure_buf = BytesIO()
                figure.savefig(figure_buf, format='jpg')
                figure_buf.seek(0)
                image = asarray(open(figure_buf))
                return image
            length = data[b'depressurize_data'].shape[0]
            x = np.arange(0,length,1)
            y = data[b'depressurize_data']
            arr = figure_to_array(chart_one(x=x,y=y)).flatten()
            self.io_push(io_dict = {'image_depre':arr})


    def push_pressurize_event(self):
        import numpy as np
        #from icarus_SL import icarus_SL

        if len(self.pressurize_data)>1:
            data = self.pressurize_data[1]
            # dic[b'fallTime_0'] = nan
            # dic[b'pulseWidthDepressure_0'] = nan
            # dic[b'tSwitchDepressure_0'] = nan
            # dic[b'pDepre_0'] = nan
            # dic[b'gradientDepressure_0'] = nan
            # dic[b'tSwitchDepressureEst_0'] = nan
            # dic[b'gradientDepressureEst_0'] = nan
            # dic[b'fallTime_1'] = nan
            # dic[b'pulseWidthDepressure_1'] = nan
            # dic[b'tSwitchDepressure_1'] = nan
            # dic[b'pDepre_1'] = nan
            # dic[b'gradientDepressure_1'] = nan
            # dic[b'depressurize_data'] = zeros((10,4000), dtype = 'int16')

            #self.io_push(io_dict = {'table_pulse_width_depre':data[b'pulseWidthDepressure_0']})
            self.io_push(io_dict = {'table_time_to_switch_pre':data[b'tSwitchPressure_0']})
            self.io_push(io_dict = {'table_rise_slope':data[b'riseTime_0']})
            self.io_push(io_dict = {'table_valve_counter_pre':self.counters_global[b'pressurize']})

            def chart_one(x,y):
                """
                charting function that takes x and y
                """
                xs_font = 10
                s_font = 12
                m_font = 16
                l_font = 24
                xl_font = 32

                import io
                from matplotlib.figure import Figure
                from matplotlib import pyplot
                from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg
                from scipy import stats
                from numpy import nonzero, zeros,nan, ones, argwhere, mean, nanmean, arange

                figure = Figure(figsize=(7.68,2.16),dpi=100)#figsize=(7,5))
                axes = figure.add_subplot(1,1,1)

                dataPlot = y.T
                x = (arange(len(dataPlot[0,:])))*(1000.0/4000)#(DAQ.pr_rate/1000.0)
                samplePre0 = dataPlot[5,:] #sample0
                samplePre1 = dataPlot[6,:] #sample1
                preLower=dataPlot[3,:] #pressure lower
                preUpper=dataPlot[4,:] #pressure upper
                target=dataPlot[0,:]
                pulse = zeros((len(dataPlot[9,:]),))
                pulse_light = zeros((len(dataPlot[9,:]),))
                for i in range(len(pulse)):
                    if dataPlot[9,i] & BIT_VALVE2 != 0:
                        pulse[i] = 1
                    else:
                        pulse[i] = 0
                for i in range(len(pulse_light)):
                    if dataPlot[9,i] & BIT_VALVE1 != 0:
                        pulse_light[i] = 1
                    else:
                        pulse_light[i] = 0

                target = target*0 + stats.mode(dataPlot[0,:]).mode

                units = self.user_units[self.selected_pressure_units]
                axes.plot(x,units*self.coeff_sample_pressure*samplePre0*2.0**-15, color = 'red', marker = 'o', markersize = 3 ) # EventDetector.scaleValve1
                # if icarus_AL.advance_view_flag:
                #     axes.plot(x,units*icarus_AL.coeffSamplePressure*samplePre1*2.0**-15, color = 'orangered', marker = 'o', markersize = 3 ) # EventDetector.scaleValve2
                axes.plot(x,units*42860.0*pulse_light,color = 'lightgreen')
                axes.plot(x,units*42860.0*pulse,color = 'blue')
                axes.plot(x,self.scale_top_valve2*preUpper*2.0**-15, color = 'darkcyan')
                axes.plot(x,self.scale_bot_valve2*preLower*2.0**-15, color = 'darkmagenta')
                axes.set_ylabel("Pressure ("+self.selected_pressure_units+")",fontsize=m_font)
                #self.axes[dic['axis']].tick_params(axis='y', which='left', labelleft=True)
                axes.plot(x,units*79600.0*target*self.coeff_target_pressure*2.0**-15, color = 'black',linestyle = '--')
                #axes[dic['axis']].legend(loc=1,fontsize='x-small')
                axes.set_title("Last Pressurize Event",fontsize=m_font, color = 'blue')
                axes.set_xlabel("Time (ms)",fontsize=m_font)
                #self.axes[dic['axis']].tick_params(axis='y', which='right', labelright=True)
                axes.tick_params(axis='y', which='both', labelleft=True, labelright=False, labelsize = m_font)
                #self.axes[dic['axis']].set_yticklabels([-25,0,25,50,75,100,125,150])
                axes.grid(True)

                figure.tight_layout()
                return figure

            def figure_to_array(figure):
                from io import BytesIO
                from PIL.Image import open
                from numpy import asarray
                figure_buf = BytesIO()
                figure.savefig(figure_buf, format='jpg')
                figure_buf.seek(0)
                image = asarray(open(figure_buf))
                return image
            length = data[b'pressurize_data'].shape[0]
            x = np.arange(0,length,1)
            y = data[b'pressurize_data']
            arr = figure_to_array(chart_one(x=x,y=y)).flatten()
            self.io_push(io_dict = {'image_pre':arr})



    def push_pump_event(self):
        #from icarus_SL import icarus_SL
        self.valve_per_pump_value = self.valve_per_pump(counters = self.counters_global, counters_current = self.counters_current)
        value = self.valve_per_pump_value[b'current']
        self.io_push(io_dict = {'valves_per_pump_current':value})
        value = self.valve_per_pump_value[b'total']
        self.io_push(io_dict = {'valves_per_pump_total':value})
        value = self.counters_global[b'pump_stroke']
        self.io_push(io_dict = {'pump_counter':value})

    def push_estimated_leak_value(self, value = 0, pressure = 0):
        from time import strftime, localtime, time
        if pressure < 100:
            self.warning_status = {b'slow_leak':nan}
        else:
            self.warning_status = {b'slow_leak':value}

    def push_digital_state(self, value = None):
        import scipy
        from numpy import nanmedian, median, copy

        if value is None:
            beforeIdx = int(self.depressure_before_time*self.daq_freq/1000.0)
            from_point = self.last_event_index[b'A300']-3
            to_point = self.last_event_index[b'A300']
            data = copy(self.get_ring_buffer_N(N = 3, pointer = from_point))
            value = data[-1,9]
        else:
            value = value
        if value != self.current_dio:
            if self.client is None:
                pass
            else:
                self.client.set_dio(value)
            self.current_dio = value

    def push_new_period(self, value):
        import numpy as np
        data = value
        info(data)
        # b'period': nan, b'delay': nan, b'pressurize_width': nan, b'depressurize_width': nan, b'pump_width': nan,
        def chart_one(x,y):
            """
            charting function that takes x and y
            """
            xs_font = 10
            s_font = 12
            m_font = 16
            l_font = 24
            xl_font = 32

            import io
            from matplotlib.figure import Figure
            from matplotlib import pyplot
            from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg
            from scipy import stats
            figure = Figure(figsize=(7.68,2.16),dpi=100)#figsize=(7,5))
            axes = figure.add_subplot(1,1,1)

            axes.plot(x,y, color = 'red' )

            axes.set_title("Top subplot")
            axes.set_xlabel("x (value)")
            axes.set_ylabel("y (value)")
            axes.tick_params(axis='y', which='both', labelleft=True, labelright=False)
            axes.grid(True)
            figure.tight_layout()
            return figure

        def figure_to_array(figure):
            from io import BytesIO
            from PIL.Image import open
            from numpy import asarray
            figure_buf = BytesIO()
            figure.savefig(figure_buf, format='jpg')
            figure_buf.seek(0)
            image = asarray(open(figure_buf))
            return image
        x = data[b'data']['x']
        y_min = data[b'data']['y_min']
        y_max = data[b'data']['y_max']
        y_mean = data[b'data']['y_mean']
        arr = figure_to_array(chart_one(x=x,y=y_mean[6,:])).flatten()
        dic = {}
                # : nan, : nan, : nan, : nan, : nan,
        dic['image_period'] = arr
        dic['table_pulse_width_depre'] = data[b'depressurize_width']
        dic['table_pulse_width_pre'] = data[b'pressurize_width']
        dic['table_delay'] = data[b'delay']
        dic['table_period'] = data[b'period']
        dic[b'pump_width'] = 0
        self.io_push(io_dict = dic)


##########################################################################################
###  Data Analysis functions section
##########################################################################################
    def import_test_data(self):
        """
        some old function to test data
        """
        from numpy import loadtxt, transpose
        data_depre = transpose(loadtxt('data_for_testing/riseTime_problems/1533928647.41_depre.csv', delimiter = ','))
        data_pre = transpose(loadtxt('data_for_testing/riseTime_problems/1533928637.69_pre.csv', delimiter = ','))
        return data_depre,data_pre

    def import_test_buffers(self):
        from numpy import loadtxt
        from circular_buffer_LL import CBServer
        event_buff = loadtxt('data_for_testing/event_buffer1.txt')
        buff_buff = loadtxt('data_for_testing/buffer1.txt')
        buff_pointer = int(loadtxt('data_for_testing/pointers.txt')[0])
        event_pointer = int(loadtxt('data_for_testing/pointers.txt')[1])

        event_buffer = CBServer(size = event_buff.shape, var_type = 'int32')
        event_buffer.append(event_buff[:,:(event_pointer+1)])

        buff = CBServer(size = buff_buff.shape, var_type = 'int16')
        buff.append(buff_buff[:,:(buff_pointer+1)])
        return buff, event_buffer

    def import_test_period(self):
        from numpy import loadtxt, transpose, concatenate
        dirname = 'data_for_testing/Aug13_water_/2018-08-13-17-14-21/buffer_files/'
        filename_depre = '1534199757.72_depre.csv'
        filename_pre = '1534199787.82_depre.csv'
        data_depre = transpose(loadtxt(dirname+filename_depre,delimiter = ','))
        data_pre = transpose(loadtxt(dirname+filename_pre,delimiter = ','))
        data = concatenate((data_pre,data_depre), axis = 1)
        return data,data_pre,data_depre




    def valve_per_pump(self, counters = {}, counters_current = {}):
        pre_local = counters_current[b'pressurize']
        pre = counters[b'pressurize']
        pump_local = counters_current[b'pump_stroke']
        pump = counters[b'pump_stroke']
        dic = {}
        if pump > 0:
            dic[b'total'] = (pre) / (pump)
        else:
            dic[b'total'] = nan
        if pump_local > 0:
            dic[b'current'] = (pre_local) / (pump_local)
        else:
            dic[b'current'] = nan
        return dic



    def analyse_period(self, data, freq = 4000.0, test = False):
        """
        analyzes the last period
        returns: dictionary of last_period_analysis
        """
        from numpy import nonzero,argwhere,empty_like, copyto, nan , isnan,zeros
        from time import time
        ###find indices of all events

        period_buffer = data
        lst_result = self.find_dio_events(data = period_buffer, local = True)
        period_event = zeros((2,len(lst_result)))
        #info(len(lst_result))
        #info(period_event)
        i = 0
        for item in lst_result:
            period_event[0,i] = int(item[b'index'])
            period_event[1,i] = int(item[b'evt_#'])
            i +=1
        debug('period_event %r' % period_event)
        idx = {}
        ##            end = argwhere(event_buffer_vector[1,:] == 20)[-1][0]
##            start = argwhere(event_buffer_vector[1,:] == 20)[-2][0]
        idx[b'period start'] = int(period_event[0,argwhere(period_event[1,:] == 21)[0][0]])
        idx[b'period end'] = int(period_event[0,argwhere(period_event[1,:] == 21)[-1][0]])

        idx[b'pre start'] = int(period_event[0,argwhere(period_event[1,:] == 20)[0][0]])
        try:
            idx[b'pre end'] = int(period_event[0,argwhere(period_event[1,:] == 21)[0][0]])
        except:
            idx[b'pre end'] = 0
            error(traceback.format_exc())
        try:
            idx[b'depre start'] = int(period_event[0,argwhere(period_event[1,:] == 10)[-1][0]])
            idx[b'depre end'] = int(period_event[0,argwhere(period_event[1,:] == 11)[-1][0]])
        except:
            error(traceback.format_exc())
            idx[b'depre start'] = nan
            idx[b'depre end'] = nan
        try:
            idx[b'HP start'] = int(period_event[0,argwhere(period_event[1,:] == 0)[0][0]])
            idx[b'HP end'] = int(period_event[0,argwhere(period_event[1,:] == 1)[0][0]])
        except:
            error(traceback.format_exc())
            idx[b'HP start'] = nan
            idx[b'HP end'] = nan
        warn('period %r' % period_event)
        warn("period[0,1] = %r ,idx[b'HP start'] = %r"% (period_event[0,1],idx[b'HP start']))


        warn('len period = %r' %(len(period_buffer[0,:])))
        #period_events_buffer = event_buffer_vector[:,start:end]
        beforeIdx = int(200*freq/1000.0) #self.depressureBeforeTime
        afterIdx = int(self.depressureAfterTime*freq/1000.0)*3
        idxI = idx[b'depre start']
        debug('(beforeIdx %r, idxI %r, afterIdx %r)' % (beforeIdx,idxI,afterIdx))
        if not isnan(idxI):
            data = period_buffer[:,idxI-beforeIdx:idxI+afterIdx]
            debug('depre data shape %r and std = %r ' % (data.shape,std(data[9,:])))
            dic_depre = {}

            dic_depre0 = self.analyse_depressure_event(data = data, channel = 0)


            debug('dic_depre %r' % dic_depre)


            dic_depre1 = self.analyse_depressure_event(data = data, channel = 1)

            dic_depre = {**dic_depre0,**dic_depre1}
        else:
            dic_depre  = {}
            dic_depre[b'pDepre_0'] = nan
            dic_depre[b'fallTime_0'] = nan
            dic_depre[b'pulseWidthDepressure_0'] = nan
            dic_depre[b'tSwitchDepressure_0'] = nan
            dic_depre[b't1Depressure_0'] = nan
            dic_depre[b'gradientDepressureCubic_0'] = nan
            dic_depre[b'pDepre_1'] = nan
            dic_depre[b'fallTime_1'] = nan
            dic_depre[b'pulseWidthDepressure_1'] = nan
            dic_depre[b'tSwitchDepressure_1'] = nan
            dic_depre[b't1Depressure_1'] = nan
            dic_depre[b'gradientDepressureCubic_1'] = nan

        beforeIdx = int(self.pressureBeforeTime*freq/1000.0)
        afterIdx = int(self.pressureAfterTime*freq/1000.0)
        idxI = idx[b'pre start']
        data = period_buffer[:,idx[b'pre start']-1:idx[b'pre end']+4] #circ_buff.get_N(N = beforeIdx+afterIdx, M = idxI+afterIdx) # M is pointer
        if test:
            import matplotlib.pyplot as plt
            plt.plot(data[9,:])
            plt.pause(0.01)
            plt.show()
        dic_pre ={}
        dic_pre0 = self.analyse_pressure_event(data = data, channel = 0, freq= self.daq.freq)
        dic_pre1 = self.analyse_pressure_event(data = data, channel = 1, freq = self.daq.freq)
        dic_pre = {**dic_pre0,**dic_pre1}


        last_period_analysis = {}
        meas = {}
        units = self.user_units[self.selected_pressure_units]
        #pressure
        meas[b'ppulse_width'] = (idx[b'pre end'] - idx[b'pre start'])*1.0/freq
        last_period_analysis[b'pPre_0'] = dic_pre[b'pPre_0']*units*self.coeff_sample_pressure*2.0**-15
        last_period_analysis[b'riseTime_0'] = dic_pre[b'riseTime_0']*1000.0/freq
        #last_period_analysis[b'pulseWidthPressure'] = (dic_pre[b'pulseWidthPressure'])*1000.0/freq
        last_period_analysis[b'pulseWidthPressure_0'] = (idx[b'pre end']-idx[b'pre start'])*1000.0/freq

        last_period_analysis[b'tSwitchPressure_0'] = dic_pre[b'tSwitchPressure_0']*1000.0/freq
        last_period_analysis[b'pPre_1'] = dic_pre[b'pPre_1']*units*self.coeff_sample_pressure*2.0**-15
        last_period_analysis[b'riseTime_1'] = dic_pre[b'riseTime_1']*1000.0/freq
        last_period_analysis[b'pulseWidthPressure_1'] = last_period_analysis[b'pulseWidthPressure_0']
        last_period_analysis[b'tSwitchPressure_1'] = dic_pre[b'tSwitchPressure_1']*1000.0/freq
        last_period_analysis[b'gradPreMax_0'] = dic_pre[b'gradientPressureCubic_0']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15
        last_period_analysis[b'gradPreMax_1'] = dic_pre[b'gradientPressureCubic_1']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15


        #Depressure
        meas[b'dpulse_width'] = (idx[b'depre end'] - idx[b'depre start'])*1.0/freq
        last_period_analysis[b'pDepre_0'] = dic_depre[b'pDepre_0']*units*self.coeff_sample_pressure*2.0**-15
        last_period_analysis[b'tSwitchDepressure_0'] = dic_depre[b'tSwitchDepressure_0']*1000.0/freq
        last_period_analysis[b'fallTime_0'] = dic_depre[b'fallTime_0']*1000.0/freq
        #last_period_analysis[b'pulseWidthDepressure'] = (dic_depre[b'pulseWidthDepressure'])*1000.0/freq
        last_period_analysis[b'pulseWidthDepressure_0'] = (idx[b'depre end']-idx[b'depre start'])*1000.0/freq
        last_period_analysis[b'pDepre_1'] = dic_depre[b'pDepre_1']*units*self.coeff_sample_pressure*2.0**-15
        last_period_analysis[b'tSwitchDepressure_1'] = dic_depre[b'tSwitchDepressure_1']*1000.0/freq
        last_period_analysis[b'fallTime_1'] = dic_depre[b'fallTime_1']*1000.0/freq
        #last_period_analysis[b'pulseWidthDepressure2'] = (dic_depre[b'pulseWidthDepressure2'])*1000.0/freq
        last_period_analysis[b'pulseWidthDepressure_1'] = last_period_analysis[b'pulseWidthDepressure_0']
        last_period_analysis[b'time_last_period'] = time()
        last_period_analysis[b'gradDepreMax_0'] = dic_depre[b'gradientDepressureCubic_0']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15
        last_period_analysis[b'gradDepreMax_1'] = dic_depre[b'gradientDepressureCubic_1']*units*(freq/1000.0)*self.coeff_sample_pressure*2.0**-15

        last_period_analysis[b'pumpCounter'] = self.counters_global[b'pump']

        last_period_analysis[b'depre end'] = idx[b'depre end']
        last_period_analysis[b'depre start'] = idx[b'depre start']
        last_period_analysis[b'pre end'] = idx[b'pre end']
        last_period_analysis[b'pre start'] = idx[b'pre start']
        last_period_analysis[b'HP end'] = idx[b'HP end']
        last_period_analysis[b'HP start'] = idx[b'HP start']
        last_period_analysis[b'period end'] = idx[b'period end']
        last_period_analysis[b'period start'] = idx[b'period start']

        nom = self.counters_global[b'pre_valve2']-self.counters_global[b'pre_valve2_start']
        denom = self.counters_global[b'pump']-self.counters_global[b'pump_start']
        if denom !=0:
            valve_per_pump = 1.0*(nom) / (denom)
        else:
            valve_per_pump = -0.0

        last_period_analysis[b'valve_per_pump'] = valve_per_pump


        last_period_analysis[b'period'] = meas[b'period'] = (idx[b'period end'] - idx[b'period start'])*1.0/freq

        last_period_analysis[b'delay'] = meas[b'delay'] = (idx[b'period end']-idx[b'depre start'])*1000.0/freq
        if not isnan(idx[b'HP start']):
            meas[b'pump_delay'] = (idx[b'HP start'] - idx[b'pre start'] )*1.0/freq
        else:
            meas[b'pump_delay'] = 00.0/freq

        last_period_analysis = self.estimate_values_at_sample(dic = last_period_analysis, tube_length = 144.5 , liquid = 'water')

        return idx, last_period_analysis, meas

    def analyse_pump_event(self, data , freq = 4000, pressure_threshold = 1000, gradient_threshold = -400*1000):
        """
        looks for pump events in the input data array. Algorith computes the gradient of the data. Returns True and the index(and magnitude) of the event, if the median pressure is above pressure_threahold and minimum gradient is below gradient_threashold.

        Parameters
        ----------
        data ::  numpy array
            numpy array of the input data. The shape of the array is 10xN, where N is the size of the packet. The actual length of the array doesn't matter.
        freq :: float
            float number describing the data acquisiion frequency
        pressure_threshold :: float
            the pressure threashold defines the lower limit above which pump events are concidered
        gradient_threshold :: float
            defines the slope of the pressure vs time which triggers pump stroke event.


        Returns
        -------
        flag, idx_min, grad_min :: tuple
            returns tuple with a boolean flag, index of the event if happened in the input data and the magnitude of the event.

        Examples
        --------
        >>> self.analyse_pump_event.(data,freq = 4000,pressure_threshold = 1000, gradient_threshold = -400*1000)
        """
        from numpy import gradient, nanmedian, nan, isnan ,argmin,argwhere
        from logging import error
        info(f'analyse_pump_event data shape: {data.shape}')
        try:
            target = data[:,0]
            grad = gradient(target)
            grad_min = nanmin(grad)
            idx_min = argmin(grad)
            if grad_min < (gradient_threshold/freq) and nanmedian(target) > pressure_threshold:
                flag = True
            else:
                flag = False
        except:
            info(f'except data shape: {data.shape}')
            target = data[:,0]
            info(target)
            error(traceback.format_exc())
            flag, idx_min, grad_min = False, 0, 0



        return flag, idx_min, grad_min

    def analyse_depressure_event(self, data , channel = 0, test = False, plot = False, precision = True, freq = 4000):
        """
        takes input data and analyze it
        1) find index where digital bit 1 goes low: called t1Depressure
        2) calculates median of all data up to t1Depressure index: called pStart
        3) finds 2 points where pressure is higher and lower than midpoint pressure (0.5*pStart)
        4) calculate the straight line question P = k*idx + b; where P is pressure and idx is index
        5) find position(float) where pressure is 90%, 10% and 50% from pStart

        calculate pulseWidthDepressure = t2Depressure-t1Depressure
        calculate pStart = median [:t2Depressure]
        calculate fallTime = idx10 - idx90
        calculate tSwitchDepressure = idx50 - t1Depressure

        output: pulseWidthPressure, tSwitchPressure,tSwitchPressure, pEnd

        looks for pump events in the input data array. Algorith computes the gradient of the data. Returns True and the index(and magnitude) of the event, if the median pressure is above pressure_threahold and minimum gradient is below gradient_threashold.

        Parameters
        ----------
        data ::  numpy array
            numpy array of the input data. The shape of the array is 10xN, where N is the size of the packet. The actual length of the array doesn't matter.
        freq :: float
            float number describing the data acquisiion frequency
        pressure_threshold :: float
            the pressure threashold defines the lower limit above which pump events are concidered
        gradient_threshold :: float
            defines the slope of the pressure vs time which triggers pump stroke event.


        Returns
        -------
        dic  :: dictionary
            returns dictionary with the following keys
             b't1Pressure_0' -
             b'pDepre_0' - pressure before depressurization
             b'pressure0_0' - pressure at 0 time
             b'pressure10_0': 1001.19,
             b'pressure50_0': 5869.95,
             b'pressure90_0': 10738.71,
             b'pressure100_0': 11955.9,
             b'time90_0': 139.81000000000756,
             b'time50_0': 143.04000000000923,
             b'time10_0': 147.57000000001153,
             b'time0_0': 326,
             b'time100_0': 125.24000000000012,
             b'fallTime_0': 7.76000000000397,
             b'tSwitchDepressure_0': 64.04000000000923,
             b'tSwitchDepressureEst_0': 75.95997000000924,
             b'gradientDepressure_0'
             b'gradientDepressureEst_0'
             b'gradientDepressureCubic_0'
             b'gradientDepressureCubicEst_0'

        Examples
        --------
        >>> from icarus_nmr.tests.test_data.test_dataset import traces
        >>> data = lst_depre = traces.get_lst_depre_trace()[0]
        >>> dic = handler.analyse_depressure_event(data)
        """
        from numpy import size, where, gradient,median, \
             nanmedian, nan, zeros, isnan, nonzero, \
             argmax,argmin,argwhere, nanstd,std, mean, \
             nanmean,arange
        from scipy.optimize import curve_fit
        from scipy import interpolate

        if channel == 0:
            data_vector = data[:,5]
            suffix = b'_0'
        elif channel ==1:
            data_vector = data[:,6]
            suffix = b'_1'
        debug('--- Start Depressure analysis for channel %r ---' % channel)
        ###Timing section
        data1 = data[:-1,9]
        data2 = data[1:,9]
        diff = data2-data1
        t1 = nan
        t2 = inf
        t0 = nan
        pulse_width = nan
        if nanstd(diff) != 0 and ~isnan(nanstd(diff)):
            indices = nonzero(diff!=0)
            debug('indices %r, and values = %r' % (indices, diff[indices]))
            for idx in indices[0]:
                before = int(data[idx,9])
                after = int(data[idx+1,9])
                bin_array = self.parse_binary(value = after) - self.parse_binary(value = before)
                debug('idx = %r,bin_array[1] = %r' %(idx, bin_array[1]))
                if bin_array[1] == -1:
                    #di1 goes low detected
                    t0 = idx

        debug('t0 = %r' %(t0))


        ###Pressures Section
        if not isnan(t0): #if t1 is not nan, meaning that d2 goes low was detected.
            from_idx = int(t0-10*freq/1000)
            to_idx = int(t0+10*freq/1000)
            debug('pressure100, depre vector, from %r to %r' %(from_idx,t0+10*freq/1000))
            pressure100 = nanmean(data_vector[from_idx:to_idx])
            #smotthing data_vector and getting mean value
            arr = data_vector*0
            for i in range(len(arr)):
                arr[i] = mean(data_vector[i:i+40])
            pressure0 = min(arr)
            pressure50 = (pressure100-pressure0)*0.5 + pressure0
            pressure10 = (pressure100-pressure0)*0.1 + pressure0
            pressure90 = (pressure100-pressure0)*0.9 + pressure0
            debug('pressure 0:%r,10:%r,50:%r,90:%r,100:%r' %(pressure0,pressure10,pressure50,pressure90,pressure100))
            pressure_jump_flag = pressure100-pressure0 > 100
        else:
            pressure_jump_flag = False
            pressure0 = nan
            pressure50 = nan
            pressure10 = nan
            pressure90 = nan
            pressure100 = nan
        if pressure_jump_flag:
            grad = gradient(data_vector)
            grad_min_idx = argmin(grad)
            grad_min_value = grad[grad_min_idx]
            time90 = argwhere(data_vector[:grad_min_idx]>=pressure90)[-1][0]
            time10 = argwhere(data_vector[grad_min_idx:]<=pressure10)[0][0] + grad_min_idx
            time50 = argwhere(data_vector[t0:]<=pressure50)[0][0] + t0
            time0 = argwhere(data_vector[grad_min_idx:]<=pressure0)[0][0] + grad_min_idx
            time100 = argwhere(data_vector[:grad_min_idx]>=pressure100)[-1][0]
            fallTime = time10-time90
            tSwitchDepressure = time50-t0
        else:
            time90 = nan
            time10 = nan
            time50 = nan
            time0 = nan
            time100 = nan
            fallTime = nan
            tSwitchDepressure = nan
            grad_min_value = nan
            grad_min_idx = nan

        #precision calculation section. It will find the part of the vector where pressure transition occurs
        #it will fit it and define parameters with higher precision.
        if precision and pressure_jump_flag:
            y = data_vector[time100:time0+1]
            x = arange(time100,time0+1)
            f = interpolate.interp1d(x, y)
            x_new = arange(time100,time0, 0.01)
            y_new = f(x_new)
            grad_min_precision_idx = argmin(gradient(y_new))
            grad_min_precision_value = min(gradient(y_new))*100
            debug('x_new[argwhere(y_new>=pressure50)[0][0]]  = %r' %(x_new[argwhere(y_new<=pressure50)[0][0]] ))
            time50 = x_new[argwhere(y_new<=pressure50)[0][0]]
            debug('grad_min_precision_idx = %r, %r' %(grad_min_precision_idx,x_new[grad_min_precision_idx]))
            debug('grad_min_precision_value = %r' %(grad_min_precision_value))
            time100 = x_new[argwhere(y_new[:grad_min_precision_idx]<=pressure100)[0][0]]
            debug(time100,time50)
            time90 = x_new[argwhere(y_new[:grad_min_precision_idx]<=pressure90)[0][0]]
            time10 = x_new[argwhere(y_new[grad_min_precision_idx:]<=pressure10)[0][0]+grad_min_precision_idx]
            fallTime = time10 - time90
            tSwitchDepressure = time50-t0
            debug('precision: t 0: %r ,10: %r ,50: %r,90: %r,100: %r' %(time0,time10,time50,time90,time100))
        else:
            grad_min_precision_value = nan

        dic = {}
        #timing results
        dic[b't1Pressure'+suffix] = t0
        #pressure results
        dic[b'pDepre'+suffix] = pressure100
        dic[b'pressure0'+suffix] = pressure0
        dic[b'pressure10'+suffix] = pressure10
        dic[b'pressure50'+suffix] = pressure50
        dic[b'pressure90'+suffix] = pressure90
        dic[b'pressure100'+suffix] = pressure100

        #pressure jump results
        dic[b'time90'+suffix] = time90
        dic[b'time50'+suffix] = time50
        dic[b'time10'+suffix] = time10
        dic[b'time0'+suffix] = time0
        dic[b'time100'+suffix] = time100
        dic[b'fallTime'+suffix] = fallTime
        dic[b'tSwitchDepressure'+suffix] = tSwitchDepressure
        dic[b'tSwitchDepressureEst'+suffix] = self.estimate_values_at_sample(dic = {b'tSwitchDepressure'+suffix:dic[b'tSwitchDepressure'+suffix]}, tube_length = self.tube_length, pressure = pressure100)
        dic[b'gradientDepressure'+suffix] = abs(grad_min_value)
        dic[b'gradientDepressureEst'+suffix] = self.estimate_values_at_sample(dic = {b'gradientDepressure'+suffix:dic[b'gradientDepressure'+suffix]}, tube_length = self.tube_length, pressure = pressure100)
        debug('grad_min_value = %r' %grad_min_value)
        dic[b'gradientDepressureCubic'+suffix] = abs(grad_min_precision_value)
        dic[b'gradientDepressureCubicEst'+suffix] = self.estimate_values_at_sample(dic = {b'gradientDepressureCubic'+suffix:dic[b'gradientDepressureCubic'+suffix]}, tube_length = self.tube_length, pressure = pressure100)
        debug('grad_min_precision_value = %r' %grad_min_precision_value)
        if plot:
            import matplotlib.pyplot as plt
            plt.figure(1)
            if channel == 1:
                plt.plot(data[:,5])
            elif channel ==2:
                plt.plot(data[:,6])
            plt.axvline(x = time0, color = 'r', linestyle = '--')
            plt.text(time0,pressure0,'time 0',rotation=90)
            plt.axvline(x = time10, color = 'r', linestyle = '--')
            plt.text(time10,pressure10,'time 10',rotation=90)
            plt.axvline(x = time50, color = 'r', linestyle = '--')
            plt.text(time50,pressure50,'time 50',rotation=90)
            plt.axvline(x = time90, color = 'r', linestyle = '--')
            plt.text(time90,pressure90,'time 90',rotation=90)
            plt.axvline(x = time100, color = 'r', linestyle = '--')
            plt.text(time100,pressure100,'time 100',rotation=90)
            plt.axvline(x = t1, color = 'r', linewidth = 4)
            plt.axvline(x = t2, color = 'r', linewidth = 4)
            plt.axvline(x = grad_min_idx, color = 'b', linestyle = '--')

            plt.axhline(y = pressure100, color = 'r')
            plt.text(time100,pressure100,'pressure 100')
            plt.axhline(y = pressure50, color = 'r')
            plt.text(time50,pressure50,'pressure 50')
            plt.axhline(y = pressure90, color = 'r')
            plt.text(time90,pressure90,'pressure 90')
            plt.axhline(y = pressure10, color = 'r')
            plt.text(time10,pressure10,'pressure 10')
            plt.axhline(y = pressure0, color = 'r')
            plt.text(time0,pressure0,'pressure 0')

            plt.pause(0.1)
            plt.show()
        return dic


    def analyse_pressure_event(self, data, channel = 1, test = False, plot = False, precision = True, freq = 4000):
        """
        takes input data and analyze it
        1) find index where digital bit 1 goes low: called t1Pressure
        2) calculates median of all data up to t1Depressure index: called pStart
        3) finds 2 points where pressure is higher and lower than midpoint pressure (0.5*pStart)
        4) calculate the straight line question P = k*idx + b; where P is pressure and idx is index
        5) find position(float) where pressure is 90%, 10% and 50% from pStart

        calculate pulseWidthDepressure = t2Depressure-t1Depressure
        calculate pStart = median [:t2Depressure]
        calculate fallTime = idx10 - idx90
        calculate tSwitchDepressure = idx50 - t1Depressure

        output: pulseWidthPressure, tSwitchPressure,tSwitchPressure, pEnd

        looks for pump events in the input data array. Algorith computes the gradient of the data. Returns True and the index(and magnitude) of the event, if the median pressure is above pressure_threahold and minimum gradient is below gradient_threashold.

        Parameters
        ----------
        data ::  numpy array
            numpy array of the input data. The shape of the array is 10xN, where N is the size of the packet. The actual length of the array doesn't matter.
        channel :: integer
            an interger value selecting different channels to analyze: channel 0 or channel 1
        test :: boolean
            a flag used when the function is run in analysis state
        plot :: boolean
            boolean flag used to plot data in case of debuging
        precision :: boolean
            a flag for precision calcuylations
        freq :: float
            float number describing the data acquisiion frequency

        Returns
        -------
        dic :: dictionary
            returns a dictionary with key corresponding to results of the analysis.

            dic = {}
            #timing results
            dic[b't1Pressure'+suffix] = t0
            #pressure results
            dic[b'pDepre'+suffix] = pressure100
            dic[b'pressure0'+suffix] = pressure0
            dic[b'pressure10'+suffix] = pressure10
            dic[b'pressure50'+suffix] = pressure50
            dic[b'pressure90'+suffix] = pressure90
            dic[b'pressure100'+suffix] = pressure100

            #pressure jump results
            dic[b'time90'+suffix] = time90
            dic[b'time50'+suffix] = time50
            dic[b'time10'+suffix] = time10
            dic[b'time0'+suffix] = time0
            dic[b'time100'+suffix] = time100
            dic[b'fallTime'+suffix] = fallTime
            dic[b'tSwitchDepressure'+suffix] = tSwitchDepressure
            dic[b'tSwitchDepressureEst'+suffix] = self.estimate_values_at_sample(dic = {b'tSwitchDepressure'+suffix:dic[b'tSwitchDepressure'+suffix]}, tube_length = self.tube_length, pressure = pressure100)
            dic[b'gradientDepressure'+suffix] = abs(grad_min_value)
            dic[b'gradientDepressureEst'+suffix] = self.estimate_values_at_sample(dic = {b'gradientDepressure'+suffix:dic[b'gradientDepressure'+suffix]}, tube_length = self.tube_length, pressure = pressure100)
            debug('grad_min_value = %r' %grad_min_value)
            dic[b'gradientDepressureCubic'+suffix] = abs(grad_min_precision_value)
            dic[b'gradientDepressureCubicEst'+suffix] = self.estimate_values_at_sample(dic = {b'gradientDepressureCubic'+suffix:dic[b'gradientDepressureCubic'+suffix]}, tube_length = self.tube_length, pressure = pressure100)

        Examples
        --------
        >>> self.analyse_pump_event.(data,freq = 4000,pressure_threshold = 1000, gradient_threshold = -400*1000)
        """
        from numpy import size, where, gradient,median, nanmedian, nan, zeros, isnan, nonzero, argmax,argmin
        from numpy import argwhere,nanstd, std, mean, nanmean, arange
        from scipy.optimize import curve_fit
        from scipy import interpolate
        debug('--- Start Pressure analysis for channel %r ---' % channel)
        debug('freq = %r' % (freq))
        if channel == 0:
            pressure_vector = data[:,5]
            suffix = b'_0'
        elif channel ==1:
            pressure_vector = data[:,6]
            suffix = b'_1'
        debug('pressure_vector = %r' % (pressure_vector))

        ###Timing section###
        data1 = data[:-1,9]
        data2 = data[1:,9]
        diff = data2-data1
        t0 = nan

        pulse_width = nan
        if nanstd(diff) != 0 and ~isnan(nanstd(diff)):
            indices = nonzero(diff!=0)
            debug('indices %r, and values = %r' % (indices, diff[indices]))
            for idx in indices[0]:
                before = int(data[idx,9])
                after = int(data[idx+1,9])
                if abs(before-after) < 127:
                    bin_array = self.parse_binary(value = after) - self.parse_binary(value = before)
                    debug('idx = %r,bin_array[2] = %r' %(idx, bin_array[2]))
                    if bin_array[2] == -1:
                        #di1 goes low detected
                        t0 = idx

        debug('t0 = %r' %(t0))

        ###Pressures Section###
        if not isnan(t0): #if t1 is not nan, meaning that di2 goes low was detected.
            from_idx = int(t0-10*freq/1000)
            to_idx = int(t0)
            debug('from: %r, to: %r' %(from_idx,to_idx))
            pressure0 = nanmean(pressure_vector[from_idx:to_idx])
            debug('vector shape %r' %pressure_vector.shape)
            #debug('vector for pressure100: %r' %(pressure_vector[t1+65*freq/1000:t1+85*freq/1000]))
            from_idx = int(t0+50*freq/1000)
            to_idx = int(t0+60*freq/1000)
            pressure100 = nanmean(pressure_vector[from_idx:to_idx])
            pressure50 = (pressure100-pressure0)*0.5 + pressure0
            pressure10 = (pressure100-pressure0)*0.1 + pressure0
            pressure90 = (pressure100-pressure0)*0.9 + pressure0
            debug('pressure 0:%r,10:%r,50:%r,90:%r,100:%r' %(pressure0,pressure10,pressure50,pressure90,pressure100))
            pressure_jump_flag = pressure100-pressure0 > 100
        else:
            pressure_jump_flag = False
        #if actuall pressure difference detected, continue with calculating pressure jump parameters
        if pressure_jump_flag:
            grad = gradient(pressure_vector)
            grad_max_idx = argmax(grad)
            grad_max_value = grad[grad_max_idx]
            debug('grad index = %r, grad_value = %r, pressure at that value %r' %(grad_max_idx,grad_max_value,pressure_vector[grad_max_idx]))
            time90 = argwhere(pressure_vector[grad_max_idx:]>=pressure90)[0][0] + grad_max_idx
            time10 = argwhere(pressure_vector[t0:grad_max_idx]<=pressure10)[-1][0] + t0
            time50 = argwhere(pressure_vector[t0:]>=pressure50)[0][0] + t0
            time0 = argwhere(pressure_vector[t0:grad_max_idx]<=pressure0)[-1][0] + t0
            time100 = argwhere(pressure_vector[grad_max_idx:]<=pressure100)[-1][0] + grad_max_idx
            debug('normal: t 0,10,50,90,100: %r,%r,%r,%r,%r' %(time0,time10,time50,time90,time100))
            riseTime = time90-time10
            tSwitchPressure = time50-t0
            vec = argwhere(pressure_vector[grad_max_idx:] > pressure_vector[grad_max_idx])
            grad_right_zero_idx = vec[0][0]

        else:
            time90 = nan
            time10 = nan
            time50 = nan
            time0 = nan
            time100 = nan

            riseTime = nan
            tSwitchPressure = nan
            grad_max_value = nan
            grad_max_idx = nan

        ###precision calculation section.###
        #It will find the part of the vector where pressure transition occurs
        #it will fit it and define parameters with higher precision.
        if precision and pressure_jump_flag:
            y = pressure_vector[time0:time100+1]
            x = arange(time0,time100+1)
            f = interpolate.interp1d(x, y)
            x_new = arange(time0,time100, 0.01)
            y_new = f(x_new)
            grad_max_precision_idx = argmax(gradient(y_new))
            grad_max_precision_value = max(gradient(y_new))*100
            debug('x_new[argwhere(y_new>=pressure50)[0][0]]  = %r' %(x_new[argwhere(y_new>=pressure50)[0][0]] ))
            time50 = x_new[argwhere(y_new>=pressure50)[0][0]]
            debug('grad_max_precision_idx = %r' %grad_max_precision_idx)
            debug('argwhere(y_new[grad_max_precision_idx:]<=pressure100) = %r' %argwhere(y_new[grad_max_precision_idx:]<=pressure100))
            debug('argwhere(y_new[grad_max_precision_idx:]<=pressure100) = %r' %argwhere(y_new[grad_max_precision_idx:]<=pressure100))
            time100 = x_new[argwhere(y_new[grad_max_precision_idx:]<=pressure100)[-1][0] + grad_max_precision_idx]
            time90 = x_new[argwhere(y_new[grad_max_precision_idx:]>=pressure90)[0][0]+grad_max_precision_idx]
            time10 = x_new[argwhere(y_new[:grad_max_precision_idx]<=pressure10)[-1][0]]
            time_to_switch_precision = time50-t0
            debug('precision: t 0,10,50,90,100 %r,%r,%r,%r,%r' %(time0,time10,time50,time90,time100))

        dic = {}
        #timing results
        dic[b't1Pressure'+suffix] = t0
        #pressure results
        dic[b'pPre'+suffix] = pressure100
        dic[b'pressure0'+suffix] = pressure0
        dic[b'pressure10'+suffix] = pressure10
        dic[b'pressure50'+suffix] = pressure50
        dic[b'pressure90'+suffix] = pressure90
        dic[b'pressure100'+suffix] = pressure100

        #pressure jump results
        dic[b'time90'+suffix] = time90
        dic[b'time50'+suffix] = time50
        dic[b'time10'+suffix] = time10
        dic[b'time0'+suffix] = time0
        dic[b'time100'+suffix] = time100
        dic[b'riseTime'+suffix] = riseTime
        if precision and pressure_jump_flag:
            dic[b'tSwitchPressure'+suffix] = time_to_switch_precision
            dic[b'tSwitchPressureNonPrecision'+suffix] = tSwitchPressure
        else:
            dic[b'tSwitchPressure'+suffix] = tSwitchPressure
        dic[b'tSwitchPressureEst'+suffix] = self.estimate_values_at_sample(dic = {b'tSwitchPressure'+suffix:dic[b'tSwitchPressure'+suffix]}, tube_length = self.tube_length, pressure = pressure100)

        dic[b'gradientPressure'+suffix] = abs(grad_max_value)
        if precision and pressure_jump_flag:
            dic[b'gradientPressureCubic'+suffix] = abs(grad_max_precision_value)
        else:
            dic[b'gradientPressureCubic'+suffix] = abs(grad_max_value)
        dic[b'gradientPressureCubicEst'+suffix] = self.estimate_values_at_sample(dic = {b'gradientPressureCubic'+suffix:dic[b'gradientPressureCubic'+suffix]}, tube_length = self.tube_length, pressure = pressure100)
        dic[b'gradientPressureEst'+suffix] = self.estimate_values_at_sample(dic = {b'gradientPressure'+suffix:dic[b'gradientPressure'+suffix]}, tube_length = self.tube_length, pressure = pressure100)
         #max(gradient())*100*0.25*(dev.pr_rate/1000)

        if plot:
            import matplotlib.pyplot as plt
            plt.figure(1)
            if channel == 1:
                plt.plot(data[:,5])
            elif channel ==2:
                plt.plot(data[:,6])

            if precision and pressure_jump_flag:
                plt.plot(x_new, y_new, linestyle = '--')
                plt.axvline(x = time_to_switch_precision+t1, color = 'g', linewidth = 2)

            plt.axvline(x = tSwitchPressure+t1, color = 'g', linewidth = 2)

            plt.axvline(x = time0, color = 'r', linestyle = '--')
            plt.text(time0,pressure0,'time 0',rotation=90)
            plt.axvline(x = time10, color = 'r', linestyle = '--')
            plt.text(time10,pressure10,'time 10',rotation=90)
            plt.axvline(x = time50, color = 'r', linestyle = '--')
            plt.text(time50,pressure50,'time 50',rotation=90)
            plt.axvline(x = time90, color = 'r', linestyle = '--')
            plt.text(time90,pressure90,'time 90',rotation=90)
            plt.axvline(x = time100, color = 'r', linestyle = '--')
            plt.text(time100,pressure100,'time 100',rotation=90)
            plt.axvline(x = t1, color = 'r', linewidth = 4)
            plt.axvline(x = t2, color = 'r', linewidth = 4)
            plt.axvline(x = grad_max_idx, color = 'b', linestyle = '--')

            plt.axhline(y = pressure100, color = 'r')
            plt.text(time100,pressure100,'pressure 100')
            plt.axhline(y = pressure50, color = 'r')
            plt.text(time50,pressure50,'pressure 50')
            plt.axhline(y = pressure90, color = 'r')
            plt.text(time90,pressure90,'pressure 90')
            plt.axhline(y = pressure10, color = 'r')
            plt.text(time10,pressure10,'pressure 10')
            plt.axhline(y = pressure0, color = 'r')
            plt.text(time0,pressure0,'pressure 0')

            plt.pause(0.1)
            plt.show()

        return dic

    def slow_leak_module(self):
        self.slow_leak_flag = False
        data = self.slow_leak_buffer.buffer[:self.slow_leak_buffer.pointer+1,:]

        if self.slow_leak_buffer.pointer != -1:
            if self.last_event_index[b'A200'] > self.last_event_index[b'D20']:
                data[:,0] = data[:,0]+self.last_event_index[b'D21']
            from_idx = data[0,0]
            to_idx = data[-1,0]
            value = self.estimate_leak_value(data = data,from_idx = from_idx,to_idx = to_idx)[b'value']
            if value < self.slow_leak_threshold:
                self.warn_value[b'slow_leak_counter'] =+ 1
            else:
                self.warn_value[b'slow_leak_counter'] = 0
            self.push_estimated_leak_value(value = value, pressure = data[0,2])
            arr = zeros((3,1))
            arr[0] = self.counters_current[b'period']
            arr[1] = to_idx-from_idx
            arr[2] = value
            self.estimated_leak_buffer.append(arr)


        self.last_full_slow_leak_buffer = data
        if self.save_trace_to_a_file and (self.logging_state == 1 or self.logging_state == 11):
            self.data_log_to_file(data, name = 'cooling')
        #reset slow leak buffer
        self.slow_leak_buffer.reset()

    def estimate_leak_value(self,data = None, from_idx = 0,to_idx = 4000, debug = False):
        """
        The function takes cooling data as input and estimates the leak speed based on input global pointers from and to.
        """
        from numpy import nan
        from ubcs_auxiliary.numerical import linear_fit

        if to_idx <= from_idx:
            diff = nan
            response = nan
        else:
            diff = to_idx - from_idx
        if data is None and len(data[0,:]) <= 6:
            res = nan
            sample = None
            x = None
            master_curve = None
            a  = None
            b = None
            Sigma = None
        else:
            sample = data[:,2]
            x = data[:,0]
            master_curve = self.cooling_master_func(x)
            y_spl = master_curve*(sample[0]/master_curve[0])
            y = ratio =  (sample/y_spl)*sample[0]

            # y = a+bx
            a,b,Sigma = linear_fit(x = x, y = ratio)
            res = b
            response = {}
            if res == None:
                res = nan
        if debug:
            response[b'value'] = res * self.cooling_coefficient
            response[b'sample'] = sample
            response[b'x'] = x
            response[b'master_curve'] = master_curve
            response[b'a'] = a
            response[b'b'] = b
            response[b'Sigma'] = Sigma
            response[b'diff'] = diff
            response[b'cooling_coefficient'] = self.cooling_coefficient
            response[b'ratio'] = ratio
        else:
            response[b'value'] = res  * self.cooling_coefficient

        return response



    def estimate_values_at_sample(self, dic, tube_length = 0, pressure = 11000, liquid = 'mineral spirits'):
        """
        """

        par = {}
        par[b'none depre'] = (0,0,0)
        par[b'none pre'] = (0,0,0)
        par[b'mineral spirits depre'] = (8*10**-5,0.0072,- 3*10**-5)
        par[b'mineral spirits pre'] = (-3*10**-6,0.0336, - 0.0485)
        par[b'water depre'] = (0,0,0)
        par[b'water pre'] = (0,0,0)
        L = tube_length #in inches

        depre_a = par[b''+bytes(liquid, 'Latin-1')+b' depre'][0]
        depre_b = par[b''+bytes(liquid, 'Latin-1')+b' depre'][1]
        depre_c = par[b''+bytes(liquid, 'Latin-1')+b' depre'][2]
        pre_a = par[b''+bytes(liquid, 'Latin-1')+b' pre'][0]
        pre_b = par[b''+bytes(liquid, 'Latin-1')+b' pre'][1]
        pre_c = par[b''+bytes(liquid, 'Latin-1')+b' pre'][2]
        for key in list(dic.keys()):
            if b'tSwitchDepressure' in key:
                value = dic[key] + depre_a*L**2+depre_b*L +depre_c + self.corrections[b'offset tSwitchDepressure']
            elif b'tSwitchPressure' in key:
                value = dic[key]  + pre_a*L**2+pre_b*L +pre_c + self.corrections[b'offset tSwitchPressure']
            elif b'gradientDepressureCubic' in key:
                value= dic[key]*self.corrections[b'multiplier gradientDepressure']
            elif b'gradientPressureCubic' in key:
                value = dic[key]*self.corrections[b'multiplier gradientPressure']
            elif b'gradientDepressure' in key:
                value = dic[key]*self.corrections[b'multiplier gradientDepressure']
            elif b'gradientPressure' in key:
                value = dic[key]*self.corrections[b'multiplier gradientPressure']

        return value

    def compute_chi2(self, pEnd, pStart):
        from numpy import arange, sum, isnan,nan
        from scipy.optimize import curve_fit
        def linear(x,a,b):
            return a*x +b

        y = pEnd- pStart
        valid = ~(isnan(y))
        y = y[valid]
        if len(y)>4:
            x = arange(0,len(y))
            integral = zeros((len(y),))

            for i in range(len(y)):
                integral[i] = sum(y[:i+1])
            popt,pcov = curve_fit(linear,x,integral)
            integral_new = linear(x,*popt)
            chi2 = 0
            summ = (integral-integral_new)**2
            chi2 = sum(summ)/len(summ)
        else:
            chi2 = 0
        return chi2

    def standard_error(self,pStart = 0.0, pEnd = 0.0):
        """
        y_fit = a + b*x
        page 104 Data reduction and error analysis for the physicxal sciences Philip R. Bevington

        Parameters
        ----------
        pStart ::  float
            numpy array of the input data. The shape of the array is 10xN, where N is the size of the packet. The actual length of the array doesn't matter.
        pEnd :: float
            float number describing the data acquisiion frequency



        Returns
        -------
        flag, idx_min, grad_min :: tuple
            returns tuple with a boolean flag, index of the event if happened in the input data and the magnitude of the event.

        Examples
        --------
        >>> self.analyse_pump_event.(data,freq = 4000,pressure_threshold = 1000, gradient_threshold = -400*1000)
        """
        from numpy import isnan,nan
        dy = (pEnd-pStart) # change in y
        dx = 1.0 #change in x
        #make a local copy of the std_err dictionary to insure calls from outside would not interfere.
        std_err_dic = self.std_err_dic.copy()


        if not isnan(dy):
            try:
                #simple local names extracted out of the dictionary for i-1 points
                Delta = std_err_dic[b'Delta']
                std_err_dic[b'a_prev'] = std_err_dic[b'a']
                std_err_dic[b'b_prev'] = std_err_dic[b'b']
                a = std_err_dic[b'a']
                b = std_err_dic[b'b']
                Sigma2 = std_err_dic[b'Sigma2']
                N = std_err_dic[b'N']

                x = std_err_dic[b'x']
                y = std_err_dic[b'y']

                Sx = std_err_dic[b'Sx']
                Sx2 = std_err_dic[b'Sx2']
                Sy = std_err_dic[b'Sy']
                Sy2 = std_err_dic[b'Sy2']
                Sxy = std_err_dic[b'Sxy']



                #Calculate new y (y_i), where y_i = y_i-1 + dy
                y += dy
                #calculate new x (x_i), where x_i = x_i-1 + dx
                x += dx

                #fit data only if there are more than 3 numbers available.
                if N>3:
                    y_pred = a+b*x #y_pred - predicted based on previous i-1 points
                    #y - is the new value that includes the i-th point
                    std_err_dic[b'std_err'] = (y-y_pred)/(Sigma2**0.5)
                else:
                    std_err_dic[b'std_err'] = 0

                #Calculate new(ith) rollins sums
                #S stands for Sum.
                Sx += x*1.0 #Sx_i = Sx_i-1 +x_i
                Sx2 += x**2.0 #Sx2_i = Sx2_i-1 + x_i**2
                Sy += y*1.0 #Sy_i = Sy_i-1 + y_i
                Sy2 += y**2.0 #Sy2_i = Sy2_i-1 + y_i**2
                Sxy += x*y*1.0 #Sxy_i = Sxy_i-1 + x_i*y_i
                N += 1.0 #N_i = N_i-1 + 1.0
                if N >= 2:
                    Delta = N*Sx2 - Sx**2 # Delta_i = N_i*Sx2_i - Sx_i**2
                    a = (1.0/Delta)*(Sx2*Sy-Sx*Sxy)
                    b = (1.0/Delta)*(N*Sxy-Sx*Sy)
                    #page 115
                if N > 2:
                    Sigma2 = (1/(N-2))*(Sy2+N*a**2+(b**2)*Sx2-2*a*Sy-2*b*Sxy+2*a*b*Sx)

                std_err_dic[b'x'] = x
                std_err_dic[b'y'] = y
                std_err_dic[b'Sx'] = Sx
                std_err_dic[b'Sx2'] = Sx2
                std_err_dic[b'Sy'] = Sy
                std_err_dic[b'Sy2'] = Sy2
                std_err_dic[b'Sxy'] = Sxy
                std_err_dic[b'N'] = N
                std_err_dic[b'Delta'] = Delta
                std_err_dic[b'a'] = a
                std_err_dic[b'b'] = b
                std_err_dic[b'Sigma2'] = Sigma2
                self.std_err_dic = std_err_dic
            except:
                error(traceback.format_exc())
        return std_err_dic[b'std_err']

    def test_standard_error(self, number = 10, plot = True):
        from numpy import loadtxt, arange, genfromtxt
        from matplotlib import pyplot as plt
        from scipy.optimize import curve_fit
        self.std_err_dic = {}
        self.std_err_dic[b'std_err'] = 0
        self.std_err_dic[b'x'] = 0
        self.std_err_dic[b'y'] = 0
        self.std_err_dic[b'Sx'] = 0
        self.std_err_dic[b'Sx2'] = 0
        self.std_err_dic[b'Sxy'] = 0
        self.std_err_dic[b'Sy'] = 0
        self.std_err_dic[b'Sy2'] = 0
        self.std_err_dic[b'N'] = 1
        self.std_err_dic[b'Delta'] = 0
        self.std_err_dic[b'a'] = 0
        self.std_err_dic[b'b'] = 0
        self.std_err_dic[b'Sigma2'] = 0

        array = genfromtxt('/Users/femto-13/All-Projects-on-femto/NMR-Pressure-Jump/data_for_testing/2018-12-04-15-37-43-leak-full-periods.log', delimiter = ',')
        def linear(x,a,b):return a + b*x
        integral = 0.0*array[:,29];
        chi = 0.0*array[:,29];
        for i in range(number):
            chi[i] = self.standard_error(pStart = array[i,4], pEnd = array[i,5])

        integral[0] = 0
        for i in range(1,len(array[:,5])):
            diff = array[i,5] - array[i,4]
            integral[i] = integral[i-1] + diff
        x = arange(0,len(array[:,5])+1,1)
        dic = self.std_err_dic
        y = linear(x,a = -dic[b'a_prev'],b = dic[b'b_prev'])
        ynew = linear(x,a = -dic[b'a'],b = dic[b'b'])
        popt,pcov = curve_fit(linear,x[0:number],integral[0:number])
        ynew_fit =  linear(x,*popt)
        if plot:
            plt.subplot(211)
            plt.plot(x[0:number-1],integral[0:number-1],'ob', label = '0 -> i-1 points')
            plt.plot(x[number-1],integral[number-1],'db', label = 'ith point')
            plt.plot(x[0:number],y[0:number],'-b', label = 'w/o last point')
            plt.plot(x[0:number],ynew[0:number],'--b',label = 'w last point')
            plt.plot(x[0:number],ynew_fit[0:number],'--g',label = 'w last point python fit')
            plt.legend()
            plt.subplot(212)
            plt.plot(x[0:number],chi[0:number],'-o',label = 'standard error')
            plt.legend()
            plt.pause(0.1)
            plt.show()






    def fit_analyize_pressure(self, data = '', freq = 0):
        from scipy.optimize import curve_fit
        popt, pcov = curve_fit(sigmoid, x_pre, sample_pre,p0 =(53,2,12000,6000))



    def sigmoid(x, x0, k, A, y0):
        """
        y_fit = a + b*x
        page 104 Data reduction and error analysis for the physicxal sciences Philip R. Bevington

        Parameters
        ----------
        x :: array
        x0 :: float
        k :: float
        A :: float
        y0 :: float



        Returns
        -------
        y ::

        Examples
        --------
        >>> sigmoid(x,x0,k A,y0)
        """
        from numpy import exp
        y = A / (1 + exp(-(k*(x-x0))))**2 + y0
        return y

##########################################################################################
###  Fault detection section
##########################################################################################

    def fault_detection_init(self):
        """
        initializes fault and warning detection.
        creates all necessary variables and data structures
        """
        from time import time
        self.fault = 0 # no faults
        self.warning = 0 # no warnings
        self.warn_value = {}
        self.warn_value[b'pressure_difference'] = 0
        self.warn_value[b'pump_stroke_counter'] = 0
        self.warn_value[b'pressure_drop'] = 0
        self.warn_value[b'slow_leak_counter'] = 0


        self.warn_index = {}
        self.warn_index[b'pressure_difference'] = 0
        self.warn_index[b'pump_stroke_counter'] = 0
        self.warn_index[b'pressure_drop'] = 0
        self.warn_index[b'slow_leak_counter'] = 0


        self.fault_description = {}
        self.fault_description['None'] = 'None'
        self.fault_description['pressure_difference'] = 'pressure_difference'
        self.fault_description['pump_stroke_counter'] = 'pump_stroke_counter'
        self.fault_description['pressure_drop'] = 'pressure_drop'
        self.fault_description['slow_leak_counter'] = 'slow_leak_counter'


        self.warning_description = {}
        self.warning_description['None'] = 'None'

        self.warning_status = {}
        self.fault_status = {}

    def acknowledge_faults(self):
        #from icarus_SL import icarus_SL
        self.fault_status = {}
        self.warn_value[b'pump_stroke_counter'] = 0
        #icarus_SL.inds.faults = self.fault_status
        self.emergency_shutdown_flag = False

    def check_for_faults(self,names = [b'pressure_drop',b'pressure_difference',b'pump_stroke_counter','slow_leak_counter']):
        """
        possible fault checks should be passed as a list.

        e.g.
            - name = [b'pressure_difference','pump_stroke_period','pump_stroke_counter']
        """
        flag_emergency_stop = False
        fault_lst = []
        for name in names:
            debug('--checking for ... %r : counters: %r' %  (name, self.warn_value))
            if name == b'pressure_drop':
                if  self.warn_value[b'pressure_drop'] <= 0.5:
                    ### if there are more than 2 difference_pressure warning in a row or more than 2 pump strokes per period
                    ###raise the flag_emergency_stop
                    flag_emergency_stop = True
                    dic = {}
                    dic[b'fault'] = b'pressure_drop'
                    dic[b'counter'] = self.warn_value[b'pressure_drop']
                    dic[b'index'] = self.warn_index[b'pressure_drop']
                    dic[b'period_index'] = self.counters_current[b'period']
                    fault_lst.append(dic)

            elif name == b'pressure_difference':
                if self.warn_value[b'pressure_difference'] >= 0.1:
                    ### if there are more than 2 difference_pressure warning in a row or more than 2 pump strokes per period
                    ###raise the flag_emergency_stop
                    flag_emergency_stop = True
                    dic = {}
                    dic[b'fault'] = b'pressure_difference'
                    dic[b'counter'] = self.warn_value[b'pressure_difference']
                    dic[b'index'] = self.warn_index[b'pressure_difference']
                    dic[b'period_index'] = self.counters_current[b'period']
                    fault_lst.append(dic)

            elif name == b'pump_stroke_counter':
                if self.warn_value[b'pump_stroke_counter'] >= 5:
                    flag_emergency_stop = True
                    dic = {}
                    dic[b'fault'] = b'pump_stroke_counter'
                    dic[b'counter'] = self.warn_value[b'pump_stroke_counter']
                    dic[b'index'] = self.warn_index[b'pump_stroke_counter']
                    dic[b'period_index'] = self.counters_current[b'period']
                    fault_lst.append(dic)

            elif name == b'slow_leak_counter':
                if self.warn_value[b'slow_leak_counter'] >= self.slow_leak_threshold_counter:
                    flag_emergency_stop = True
                    dic = {}
                    dic[b'fault'] = b'slow_leak'
                    dic[b'counter'] = self.warn_value[b'slow_leak_counter']
                    dic[b'index'] = self.warn_index[b'slow_leak_counter']
                    dic[b'period_index'] = self.counters_current[b'period']
                    fault_lst.append(dic)

            return fault_lst


    def evaluate_faults(self,fault_lst = [], warning_lst = []):
        #from icarus_SL import icarus_SL
        if len(fault_lst) != 0:
            self.fault_status = fault_lst
            self.warning_status = warning_lst
            self.emergency_shutdown_flag = True
            #icarus_SL.inds.faults = fault_lst
            #icarus_SL.ctrls.safe_state = 1
            msg = ''
            for element in fault_lst:
                msg += 'The fault %r is detected. The warning \
                        counters are %r at index %r. \n' %(element[b'fault'],element[b'counter'],element[b'index'] )
            msg += 'The high pressure pump air flow was shut down'

            debug(msg)
            #self.logging_permanent_log_append(message = msg)
            #self.SentEmail(event = 'fault')
            #info(msg)

        else:
            pass


    def reset_warn_counters(self):
        for key in list(self.warn_counter.keys()):
            self.warn_counter[key] = 0

    def fault_pressure_drop(self,pressure_vector = asarray([100,100,100]),new_value = 0):
        """
        compares the trend in the pressure_vector with the new value (new_value).
        If the ration of the ratio of the new_value and mean value of the pressure_vector is smaller than threshold return True.
        The pin hole leak has been detected.
        the input pressuse_vector

        reports ratio only
        """
        from numpy import nanmean
        previous = nanmean(pressure_vector)
        next = new_value
        ratio = next/previous
        if previous <= 1000:
            ratio = 1
        elif next < 0:
            ratio = abs(ratio)
        return ratio

    def fault_pump_stroke_frequency(self, distance = 3):
        """
        """
        if self.last_event_width[b'pump_stroke'] <= distance:
            flag = True
        else:
            flag = False
        return flag

    def fault_difference_pressure(self):
        """
        creates a fault if pStart - pEnd becomes large negative number than pEnd*criterium
        threshold defines below what values of pStart and pEnd do not do any calculations
        """
        return 0

    def import_history_data(self,keys = [b''], plot = False):
        from numpy import loadtxt, transpose
        import os
        folder = 'data_for_testing/'
        dataset = ''
        dic = {}
        for key in keys:
            filename = folder + dataset+ key + '.log'
            data = transpose(loadtxt(filename,comments='#',delimiter=',',skiprows=2))
            dic[key] = data
        return dic



    def test_fault_difference_pressure(self, data_pStart, data_pEnd, plot = True, criterium = 0.05, threshold = 0.2):
        """
        return the position of the first faults and positions of warnings.
        if the plot parameter is True.
        it will plot the graph with the warning positions in yellow and
        the fault position in red.
        """
        from numpy import abs
        import matplotlib.pyplot as plt
        length = len(data_pStart[0,:10000])
        pStart = data_pStart[1,1:10000]
        x_pStart = data_pStart[0,1:10000]
        pEnd = data_pEnd[1,:9999]
        x_pEnd = data_pEnd[0,:9999]
        warnings = []
        for i in range(length-1):
            flag = self.fault_difference_pressure(pStart = pStart[i], pEnd = pEnd[i], criterium = criterium, threshold = threshold)
            if flag:
                #print i,pStart[i],pEnd[i], abs(pStart[i]-pEnd[i]), pEnd[i]*criterium
                warnings.append(data_pStart[0,i])

        if plot:
            plt.plot(x_pStart,pStart)# - pEnd)
            plt.plot(x_pEnd,pEnd)
            for i in warnings:
                plt.axvline(x=i, color = 'r')
            plt.pause(0.1)
            plt.show()




##########################################################################################
###  Wrappers to interact with DAQ DI-4108 section
##########################################################################################

    def get_daq_packet_ij(self,packet_pointer_i = 0,packet_pointer_j = 0):
        """
        grabs one packet at packet_pointer
        """
        try:
            data = self.daq.get_packet_ij(packet_pointer_i,packet_pointer_j)
        except:
            error(traceback.format_exc())
            data = None
        return data

    def getPeriodHistory(self, pointer):
        """
        This is an older function that will not be here
        in the new client\server implementation
        """
        try:
            data = self.daq.get_packet_ij(pointer,pointer)
        except:
            error(traceback.format_exc())
            data = None
        #self.periodHistory.append(amin(data, axis = 1))

    def get_ring_buffer_N(self, N = 1, pointer = 1):
        """
        wrapper to access the N points prior
        the pointer value in the DAQ circular buffer.
        pointer and N have to be integer.
        if the are not, the function will make them integer
        """

        N = int(N)
        pointer = int(pointer)
        #try:
        res = self.daq.get_ring_buffer_N(N, pointer)
            #res = self.test_ring_buffer()
        # except:
        #     res = None
        #     error(traceback.format_exc())
        return res

    def get_daq_freq(self):
        """returns DAQ frequency"""
        try:
            res = self.daq.freq
        except:
            error(traceback.format_exc())
            res = nan
        return res
    def set_daq_freq(self,value):
        """sets DAQ frequency. cannot be called from this instance.
        the command will be ignored
        """
        pass
    daq_freq = property(get_daq_freq,set_daq_freq)

    def get_daq_packet_length(self):

        """returns the length of a packet of data from DAQ."""

        try:
            res = self.daq.packet_length
        except:
            error(traceback.format_exc())
            res = nan
        return res
    def set_daq_packet_length(self,value):
        """sets DAQ frequency. cannot be called from this instance.
        the command will be ignored
        """
        pass
    daq_packet_length = property(get_daq_packet_length,set_daq_packet_length)



    def get_daq_packet_pointer(self):
        """returns DAQ packet pointer"""
        try:
            res = self.daq.circular_buffer.packet_pointer #
        except:
            error(traceback.format_exc())
            res = nan
        return res
    def set_daq_packet_pointer(self,value):
        """sets DAQ packet pointer. cannot be called from this instance.
        the command will be ignored
        """
        pass
    daq_packet_pointer = property(get_daq_packet_pointer,set_daq_packet_pointer)

    def get_daq_pointer(self):
        """returns DAQ packet pointer"""
        try:
            res = self.daq.circular_buffer.pointer
        except:
            error(traceback.format_exc())
            res = nan
        return res
    daq_pointer = property(get_daq_pointer)

    def get_daq_running(self):
        try:
            flag = self.daq.running
        except:
            error(traceback.format_exc())
            flag = False
        return flag
    daq_running = property(get_daq_running)

    def get_daq_packet_buffer_length(self):
        """
        wrapper: to communication with the circular buffer thread

        returns total length of the circular buffer in packets.
        """
        try:
            res  = self.daq.circular_buffer.shape[0]/self.daq.packet_length
        except:
            error('self_LL.py @ get_daq_packet_buffer_length',traceback.format_exc())
            res = nan
        return res
    daq_packet_buffer_length = property(get_daq_packet_buffer_length)


    def reset_counter(self, pvname = '',value = '', char_val = ''):
        if pvname == socket_server.CAS_prefix+'reset_valve2':
            old_value = str(self.counters[b'pre_valve2'])
            self.counters[b'pre_valve2'] = int(value)
            self.pulsePressureCounter = self.counters[b'pre_valve2']
            msg = 'PVname %r received counter pre_valve2 was reset to %r -> %r' %(pvname,old_value,str(self.counters[b'pre_valve2']))
            self.append_permanent_log(message = msg)
            old_value = self.counters[b'depre_valve1']
        elif pvname == socket_server.CAS_prefix+'reset_valve1':
            old_value = str(self.counters[b'depre_valve1'])
            self.counters[b'depre_valve1'] = int(value)
            self.pulseDepressureCounter = self.counters[b'depre_valve1']
            msg = 'PVname %r received counter depre_valve1 was reset to %r -> %r' %(pvname,old_value,str(self.counters[b'depre_valve1']))
            self.append_permanent_log(message = msg)
        elif pvname == socket_server.CAS_prefix+'reset_HP_pump':
            old_value = str(self.counters[b'pump'])
            self.counters[b'pump'] = int(value)
            self.pumpCounter = self.counters[b'pump']
            msg = 'PVname %r received counter pump was reset to %r -> %r' %(pvname,old_value,str(self.counters[b'pump']))
            self.append_permanent_log(message = msg)

    def get_coeff_target_pressure(self,value = None):
        return self.coeff_target_pressure

    def set_coeff_target_pressure(self,value = None):
        value = float(value)
        self.coeff_target_pressure = value

    def get_timeout_period_time(self, pvname = '',value = '', char_val = ''):
        return self.timeout_period_time

    def set_timeout_period_time(self, pvname = '',value = '', char_val = ''):
        debug('set_timeOutTime executed')
        value = float(value)
        self.timeout_period_time = value



    def get_tube_length(self):
        return self.tube_length

    def set_tube_length(self,value = ''):
        debug('set_tube_length executed')
        value = float(value)
        self.tube_length = value



    def get_medium(self):
        return self.medium

    def set_medium(self,value = ''):
        debug('set_medium executed')
        value = value
        self.medium = value



    def get_logging_state(self, value = None):
        return self.logging_state

    def set_logging_state(self, value = None):
        #from icarus_SL import icarus_SL
        info("def set_logging_state(self, value = None): where value = %r" %value)
        if value == 1:
            info('if value: %r' %value)
            self.exp_start_time = self.last_event_index[b'D40']
            #icarus_SL.inds.exp_start_time = self.last_event_index[b'D40']
            #self.logging_start()
            #self.experiment_parameters_log()
        elif value == 11:
            self.exp_start_time = self.last_event_index[b'A200']
            #icarus_SL.inds.exp_start_time = self.last_event_index[b'A200']
            #self.logging_start()
            #self.experiment_parameters_log()

        if value == 11:
            self.logging_state = 11
        elif value == 10:
            self.logging_state = 10
        elif value == None:
            self.logging_state = None
        else:
            self.logging_state = value

    def get_save_trace_to_a_file(self):
        return self.save_trace_to_a_file

    def set_save_trace_to_a_file(self, value = None):
        if value != None:
            self.save_trace_to_a_file = value

    def calibrate_channels(self):
        from numpy import mean
        from time import sleep
        daq.pressure_sensor_offset = [0,0,0,0,0,0,0,0]
        sleep(3)
        data = self.daq.get_ring_buffer_N(N = self.daq.freq*2, pointer = daq.circular_buffer.pointer)
        daq.pressure_sensor_offset = [mean(data[0,:]), mean(data[1,:]), mean(data[2,:]), mean(data[3,:]), mean(data[4,:]), mean(data[5,:]), mean(data[6,:]), mean(data[7,:])]

    def update_counters_for_persistent_property(self):
        self.counters_pump = self.counters_global[b'pump']
        self.counters_depressurize = self.counters_global[b'depressurize']
        self.counters_pressurize = self.counters_global[b'pressurize']
        self.counters_valve3 = self.counters_global[b'valve3']
        self.counters_logging = self.counters_global[b'logging']
        self.counters_D5 = self.counters_global[b'D5']
        self.counters_D6 = self.counters_global[b'D6']
        self.counters_period = self.counters_global[b'period']
        self.counters_delay = self.counters_global[b'delay']
        self.counters_timeout = self.counters_global[b'timeout']
        self.counters_pump_stroke = self.counters_global[b'pump_stroke']
        self.counters_periodic_update = self.counters_global[b'periodic_update']
        self.counters_periodic_update_cooling = self.counters_global[b'periodic_update_cooling']

        ##########################################################################################
        ###  Auxiliary codes
        ##########################################################################################
    def bin_data(self, data  = None, x_in = None, axis = 1, num_of_bins = 300):
        from ubcs_auxiliary.numerical import bin_data
        return bin_data(data  = data, x = x_in, axis = axis, num_of_bins = num_of_bins, dtype = 'int')

    def history_init(self):
        """
        initializes logging at the very beginning. Creates all necessary variables and objects.
        Has to be run once at the beginning of the server initialization
        """
        from os import makedirs, path
        from time import strftime, localtime, time
        from datetime import datetime
        from circular_buffer_numpy.circular_buffer import CircularBuffer

        self.history_buffers_list = [b'pPre_0',
                                     b'pDepre_0',
                                     b'pPre_after_0',
                                     b'pDiff_0',
                                     b'tSwitchDepressure_0',
                                     b'tSwitchDepressureEst_0',
                                     b'tSwitchPressure_0',
                                     b'tSwitchPressureEst_0',
                                     b'gradientPressure_0',
                                     b'gradientDepressure_0',
                                     b'gradientPressureEst_0',
                                     b'gradientDepressureEst_0',
                                     b'riseTime_0',
                                     b'fallTime_0',
                                     b'pPre_1',
                                     b'pDepre_1',
                                     b'pPre_after_1',
                                     b'pDiff_1',
                                     b'tSwitchDepressure_1',
                                     b'tSwitchPressure_1',
                                     b'gradientPressure_1',
                                     b'gradientDepressure_1',
                                     b'fallTime_1',
                                     b'riseTime_1',
                                     b'period',
                                     b'delay',
                                     b'pressure_pulse_width',
                                     b'depressure_pulse_width',
                                     b'pump_stroke',
                                     b'depressure_valve_counter',
                                     b'pressure_valve_counter',
                                     b'leak_value',
                                     b'meanbit3'
                                     ]
        self.history_buffers = {}
        for key in self.history_buffers_list:
            self.history_buffers[key] = CircularBuffer(shape = (4,self.history_buffer_size), dtype = 'float64')
        #                 arr[0,0] = period_idx
        #                 arr[1,0] = event_code
        #                 arr[2,0] = global_pointer
        #                 arr[3,0] = value

    def history_append(self, dic = {},event_code = 0, global_pointer = 0, period_idx = 0):
        """
        appends values to circular buffers with keys according to the input dictionary(dic)
        """
        from numpy import zeros
        arr = zeros((4,1))
        t = time()
        for key, value in dic.items():
            if key in self.history_buffers_list:
                arr[0,0] = period_idx
                arr[1,0] = event_code #value[b'evt_code']
                arr[2,0] = global_pointer# value[b'global_pointer']
                arr[3,0] = value
                self.history_buffers[key].append(arr)

    def history_reset(self, pvname = '',value = '', char_val = ''):
        from os import makedirs, path
        from time import strftime, localtime, time
        from datetime import datetime
        ###reset counters by grabbing local parameters from global
        self.counters_current = {b'pump':0,
            b'depressurize':0,
            b'pressurize':0,
            b'valve3':0,
            b'logging':0,
            b'D5':0,
            b'D6':0,
            b'period':0,
            b'delay':0,
            b'timeout':0,
            b'pump_stroke':0,
            b'periodic_update':0,
            b'periodic_update_cooling':0,
            b'emergency': 0} #emergency counter for leak detection
        #clear history buffers
        for key, values in self.history_buffers.items():
            self.history_buffers[key].clear()



##########################################################################################
###  test functions
##########################################################################################
    def test_find_DIO_events(self,N = 0):
        self.find_dio_events(self.test_ring_buffer(N = N))
        return self.event_buffer.buffer

    def test_ring_buffer(self,N = 0):
        from numpy import genfromtxt, transpose
        import os
        folder = './data_for_testing/traces/'
        lst = os.listdir(folder)
        my_data = transpose(genfromtxt(folder + lst[N], delimiter=','))
        return my_data

    def test_event_analysis(self, N = 0):
        import matplotlib.pyplot as plt
        from numpy import arange,gradient, ones
        data = self.test_ring_buffer(N = N)
        sample = data[5,:]
        x = arange(0,len(sample),1)
        sample_grad = gradient(data[5,:])
        debug('depressure')
        idx90,idx50,idx10,midpoint,grad_min_idx,grad_left_zero_idx,grad_right_zero_idx,pDepre,t1Depressure=self.analyse_depressure_event(data = data, freq = 2000, test = True)
        debug('pressure')

        plt.plot(x,data[5,:],'-o',markersize = 2)
        plt.plot(x,((data[9,:]-min(data[9,:]))/max(data[9,:]-min(data[9,:])))*max(data[5,:]))

        plt.axvline(x=idx90,color = 'r')
        plt.axvline(x=idx50,color = 'r')
        plt.axvline(x=idx10,color = 'r')
        plt.axvline(x=t1Depressure,color = 'k')
        plt.axhline(y = pDepre)

        idx90,idx50,idx10,midpoint,grad_max_idx,grad_left_zero_idx,grad_right_zero_idx,pPre,t1 = self.analyse_pressure_event(data = data, freq = 2000, test = True)
        plt.axvline(x=idx90,color = 'r')
        plt.axvline(x=idx50,color = 'r')
        plt.axvline(x=idx10,color = 'r')
        plt.axvline(x=t1,color = 'k')
        plt.axhline(y = pPre)
        plt.show()



    def test_pump_analysis(self, N = 0):
        import matplotlib.pyplot as plt
        from numpy import arange,gradient, transpose
        from numpy import genfromtxt
        import os
        folder = './data_for_testing/pump_traces/'
        lst = os.listdir(folder)
        filename = folder + lst[N]
        if os.path.isfile(filename):
            my_data = genfromtxt(filename, delimiter=',')
            data =  transpose(my_data)
            sample = data[0,:]
            x = arange(0,len(sample),1)
            sample_grad = gradient(data[0,:])
            info(self.analyse_pump_event(data))
            plt.figure()
            plt.plot(x,sample,'o',
                     x,data[1,:],'-',
                     x,data[2,:],'-',
                     x,data[3,:],'-',
                     x,data[4,:],'-',
                     x,data[9,:]*50,'-',
                     x,sample_grad);plt.pause(0.01);plt.show();


    def fit_analysis(self,N = 0):
        import matplotlib.pyplot as plt
        from numpy import arange,gradient
        data = self.test_ring_buffer(N = N)




if __name__ == "__main__":
    from importlib import reload
    from tempfile import gettempdir
    import logging
    import matplotlib
    matplotlib.use('WxAgg')
    import socket
    SERVER_NAME = socket.gethostname()

    from icarus_nmr.event_handler import Handler
    from icarus_nmr.event_daq import DAQ
    from icarus_nmr.event_client import Client
    from icarus_nmr.event_server import Server

    client = Client(device_ca_server_prefix = f'device_{SERVER_NAME}:',dio_ca_server_prefix = f'dio_{SERVER_NAME}:')
    daq = DAQ(client)
    daq.init()
    daq.start()

    handler = Handler(daq, client)
    handler.init()
    handler.fault_detection_init()
    handler.start()

    logging.basicConfig(filename=gettempdir()+'/icarus_event_handler.log',
                        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    from numpy import array

    temp_lst = {b'tSwitchPressure_0':1,b'tSwitchPressure_1':2,b'tSwitchPressureEst_0':3,b'gradientPressure_0':4,b'gradientPressure_1':5,b'gradientPressureEst_0':6}
