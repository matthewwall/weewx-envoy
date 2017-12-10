#!/usr/bin/env python
# Copyright 2017 Matthew Wall, all rights reserved
"""
Driver to collect data from the Enphase Envoy.

The official local API is pretty poor:
http://hostname/api/v1/production

Luckily there are other endpoints with more information:

http://hostname/home.json
http://hostname/home.json
http://hostname/inventory.json
http://hostname/api/v1/production/inverters

username:password are envoy:nnnnnn where nnnnnn are last 6 digits of serial
uses digest authentication?

/home?locale=en&classic=1
/home?locale=en&classic=2

/production.json?details=1
/production.json?details=2

/info
/ivp/meters



Thanks to thecomputerperson:

https://thecomputerperson.wordpress.com/2016/08/03/enphase-envoy-s-data-scraping/
"""

from __future__ import with_statement
import json
import syslog
import time
import urllib

import weewx.drivers
import weewx.units
import weewx.accum

DRIVER_NAME = 'Envoy'
DRIVER_VERSION = '0.1'


def loader(config_dict, _):
    return EnvoyDriver(**config_dict[DRIVER_NAME])

def confeditor_loader():
    return EnvoyConfigurationEditor()


def logmsg(level, msg):
    syslog.syslog(level, 'envoy: %s' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)


# maximum number of solar panels that we can track
MAX_PANELS = 100

schema = [('dateTime',   'INTEGER NOT NULL UNIQUE PRIMARY KEY'),
          ('usUnits',    'INTEGER NOT NULL'),
          ('interval',   'INTEGER NOT NULL'),
          ('power',  'REAL'),   # Watt - instantaneious
          ('energy', 'REAL')]   # kWh - delta since last
# power and energy from each panel
for x in range(1, MAX_PANELS):
    schema.extend(('power_%d' % x, 'REAL'), ('energy_%d' % x, 'REAL'))

weewx.units.obs_group_dict['power'] = 'group_power' # watt
weewx.units.obs_group_dict['energy'] = 'group_energy' # watt-hour
try:
    # weewx prior to 3.7.0.  for 3.7.0+ this goes in the weewx config file
    weewx.accum.extract_dict['energy'] = weewx.accum.Accum.sum_extract
except AttributeError:
    pass


class EnvoyConfigurationEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[Envoy]
    # This section is for the Enphase Envoy driver.

    # Hostname or IP address of the Envoy
    host = 0.0.0.0

    # Envoy serial number
    serial = 00000000

    # The driver to use:
    driver = user.envoy
"""

    def prompt_for_settings(self):
        print "Specify the hostname or address of the Envoy"
        host = self._prompt('host', '0.0.0.0')
        print "Specify the Envoy serial number"
        serial = self._prompt('serial', '0.0.0.0')
        return {'host': host, 'serial': serial}


class EnvoyDriver(weewx.drivers.AbstractDevice):

    def __init__(self, **stn_dict):
        loginf('driver version is %s' % DRIVER_VERSION)
        host = None
        serial = None
        try:
            host = stn_dict['host']
            serial = stn_dict['serial']
        except KeyError, e:
            raise Exception("unspecified parameter %s" % e)
        self.model = stn_dict.get("model", "Envoy-S")
        self.max_tries = int(stn_dict.get('max_tries', 5))
        self.retry_wait = int(stn_dict.get('retry_wait', 30))
        self.polling_interval = int(stn_dict.get('polling_interval', 300))
        if self.polling_interval < 300:
            raise Exception('polling_interval must be 300 seconds or greater')
        self.last_total = dict()
        self.envoy = Envoy(host)

    def closePort(self):
        self.envoy = None

    @property
    def hardware_name(self):
        return self.model

    def genLoopPackets(self):
        ntries = 0
        while ntries < self.max_tries:
            ntries += 1
            try:
                packet = self.envoy.get_data()
                logdbg('data: %s' % packet)
                packet = self.sensors_to_fields(packet)
                logdbg('mapped to fields: %s' % packet)
                ntries = 0
                yield packet
                time.sleep(self.polling_interval)
            except IOError, e:
                logerr("Failed attempt %d of %d to get LOOP data: %s" %
                       (ntries, self.max_tries, e))
                logdbg("Waiting %d seconds before retry" % self.retry_wait)
                time.sleep(self.retry_wait)
        else:
            msg = "Max retries (%d) exceeded for LOOP data" % self.max_tries
            logerr(msg)
            raise weewx.RetriesExceeded(msg)

    def sensors_to_fields(self, pkt):
        packet = {'dateTime': int(time.time()+0.5), 'usUnits':weewx.US}
        packet['power'] = pkt.get('wattsNow')
        packet['energy_total'] = pkt.get('wattHoursLifetime')
        packet['energy'] = self.calculate_delta(
            'energy', packet['energy_total'], self.last_total.get('energy'))
        self.last_total['energy'] = packet['energy_total']
        return packet

    def calculate_delta(self, label, this_total, last_total):
        delta = None
        if last_total is not None and this_total is not None:
            if this_total >= last_total:
                delta = this_total - last_total
            else:
                logerr("bogus %s: %s < %s" % (label, this_total, last_total))
        elif this_total is None:
            logdbg("no delta for %s: no total" % label)
        else:
            logdbg("no delta for %s: no last total" % label)
        return delta


class Envoy(object):

    def __init__(self, host):
        self.url = "http://%s/api/v1/production" % host

    def get_data(self):
        resp = urllib.urlopen(self.url)
        data = json.loads(resp.read())
        return data


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Envoy data query')
    parser.add_argument('host', help='host name or address')
    args = parser.parse_args()
    envoy = Envoy(args.host)
    print "query: %s" % envoy.url
    data = envoy.get_data()
    print "%s" % data
