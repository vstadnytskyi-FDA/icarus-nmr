#!/usr/bin/env python3
"""

"""

import socket
device_ca_server_prefix = f'{socket.gethostname()}_dio_controller:'

from caproto.threading.client import Context
ctx = Context()
ca_name = device_ca_server_prefix
pv_names = ['dio',
                'bit0_indicator',
                'bit0',
                'bit0_enable',
                'bit1_indicator',
                'bit1',
                'bit1_enable',
                'bit2_indicator',
                'bit2',
                'bit2_enable',
                'bit3_indicator',
                'bit3',
                'bit3_enable']
pvs = {}
for item in pv_names:
    pvs[item], = ctx.get_pvs(f'{ca_name}{item}',)

if __name__ == '__main__':
    pass
