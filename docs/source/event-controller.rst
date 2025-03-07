================
Event Controller
================

*****************
Overview
*****************


Events:
*****************

Digital events:

* D00 (0) - bit 0 goes low
* D01 (1) - bit 0 goes high
* D10 (10) - bit 1 goes low
* D11 (11) - bit 1 goes high
* D20 (20) - bit 2 goes low
* D21 (21) - bit 2 goes high
* D30 (30) - bit 3 goes low
* D31 (31) - bit 3 goes high
* D40 (40) - bit 4 goes low
* D41 (41) - bit 4 goes high
* D50 (50) - bit 5 goes low
* D51 (51) - bit 5 goes high
* D60 (60) - bit 6 goes low
* D61 (61) - bit 6 goes high

Analog events:

* A100 (100) - pump stroke

Time based events:

* T200 (200) - period
* T300 (300) - 3 Hz periodic update
* T301 (301) - 10 Hz periodic update
* T999 (999) - timeout event

Data channels:
**********************************

* channel 0 - target pressure
* channel 1 - depressurization valve lower sensor
* channel 2 - depressurization valve upper sensor
* channel 3 - pressurization valve lower sensor
* channel 4 - pressurization valve upper sensor
* channel 5 - high pressure transducer at the origin
* channel 6 - high pressure transducer at the sample*
* channel 7 - target pressure
* channel 8 - auxiliary digital line (no in use)
* channel 9 - digital line represented as 7bit number
