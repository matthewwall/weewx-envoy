weewx-envoy
Copyright 2017 Matthew Wall
Distributed under terms of the GPLv3

This is a driver for weewx that collects data from the Enphase Envoy.
The Envoy is a network interface to inverters on a photovoltaic system.

Installation

0) install weewx (see the weewx user guide)

1) download the driver

wget -O weewx-envoy.zip https://github.com/matthewwall/weewx-envoy/archive/master.zip

2) install the driver

wee_extension --install weewx-envoy.zip

3) configure the driver

wee_config --reconfigure

4) start weewx

sudo /etc/init.d/weewx start
