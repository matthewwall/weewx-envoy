#!/usr/bin/env python
# Copyright 2017 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)
"""
Driver to collect data from the Enphase Envoy.

The Envoy comes in at least two flavors: the ovular Envoy and the hard-cornered
Envoy-S.  There are multiple firmware versions for each type of hardware.

This driver is known to work with the Envoy-S with the following:

  software_version: D4.5.82 (b97ae7)

The official local API is really sparse:

  http://www2.enphase.com/global/files/Envoy-API-Technical-Brief.pdf

It is a single endpoint:

  http://hostname/api/v1/production

This provides the following information:

  {'wattHoursLifetime': 619629, 'wattHoursToday': 3850,
   'wattsNow': 0, 'wattHoursSevenDays': 80440}

Enphase says that the inverters report every 5 minutes, so they suggest that
there is no point in querying more often.  Sandeen reports that querying the
envoy too frequently will prevent it from uploading data to the Enphase
servers.

As of mid-2017, Enphase discourages the use of the local v1 API and encourages
everyone to use the v2 web-based API.

FWIW, there are other local endpoints with more information.  However, given
the Enphase stance above, these might go away with a firmware update.  Beware.

  /api/v1/production/inverters
  /home.json
  /inventory.json
  /production.json
  /info
  /inv

  /home?classic=1
  /home?classic=2
  /home?locale=en

  /production.json?details=1
  /production.json?details=2

  /ivp/meters
  /ivp/tpm/tpmstatus

Authentication:

Some of the endpoints require authorization as username/password using digest
authentication.  The username:password are envoy:nnnnnn where nnnnnn are last
6 digits of serial.

If you are using curl to explore/verify the endpoints, use the following:

  curl --user envoy:nnnnnn --digest http://hostname/api/v1/production/inverters

The envoy:nnnnnn credentials do not work for all of the endpoints that require
authentication.

Credits:

Thanks to the following for publishing what they learned:

eric sandeen (2010):

https://sandeen.net/wordpress/energy/solar-monitoring/

nika (2014):

https://github.com/nikagl/GetEnvoyData

thecomputerperson (2016):

https://thecomputerperson.wordpress.com/2016/08/03/enphase-envoy-s-data-scraping/

ghawken (2017):

https://github.com/Ghawken/IndigoEnphaseEnvoy
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

schema = [('dateTime', 'INTEGER NOT NULL UNIQUE PRIMARY KEY'),
          ('usUnits', 'INTEGER NOT NULL'),
          ('interval', 'INTEGER NOT NULL'),
          ('energy_total', 'REAL'), # kWh
          ('power', 'REAL'), # Watt - instantaneious
          ('energy', 'REAL')] # kWh - delta since last
# power and energy from each panel
for x in range(1, MAX_PANELS + 1):
    schema.extend(('power_%d' % x, 'REAL'))
    schema.extend(('energy_%d' % x, 'REAL'))

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
        serial = self._prompt('serial', '00000000')
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
        self.host = host
        self.url = "http://%s/api/v1/production" % host

    def get_info(self):
        data = []
        for u in ['/home.json', '/inventory.json', '/production.json',
                  '/inv', '/info']:
            url = "http://%s%s" % (self.host, u)
            resp = urllib.urlopen(url)
            data.append(resp.read())
        return '\n'.join(data)

    def get_data(self):
        resp = urllib.urlopen(self.url)
        data = json.loads(resp.read())
        return data


if __name__ == '__main__':
    import optparse

    usage = """%prog [--debug] [--help] [--version]
                     --host=HOSTNAME"""

    syslog.openlog('envoy', syslog.LOG_PID | syslog.LOG_CONS)
    syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_INFO))
    parser = optparse.OptionParser(usage=usage)
    parser.add_option('--version', action='store_true',
                      help='display driver version')
    parser.add_option('--debug', action='store_true',
                      help='display diagnostic information while running')
    parser.add_option('--info', action='store_true',
                      help='display device and firmware details')
    parser.add_option('--host', default='localhost',
                      help='hostname or IP address of the envoy')
    (options, args) = parser.parse_args()

    if options.version:
        print "%s driver version %s" % (DRIVER_NAME, DRIVER_VERSION)
        exit(1)

    if options.debug:
        syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_DEBUG))

    envoy = Envoy(options.host)
    if options.info:
        info = envoy.get_info()
        print info
        exit(0)

    print "query: %s" % envoy.url
    while True:
        data = envoy.get_data()
        print "%s: %s" % (int(time.time()), data)
        time.sleep(30)
