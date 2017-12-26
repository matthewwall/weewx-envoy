# installer for the weewx-envoy driver
# Copyright 2017 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)

from setup import ExtensionInstaller

def loader():
    return SWBInstaller()

class SWBInstaller(ExtensionInstaller):
    def __init__(self):
        super(SWBInstaller, self).__init__(
            version="0.1",
            name='envoy',
            description='Capture data from Enphase Envoy',
            author="Matthew Wall",
            author_email="mwall@users.sourceforge.net",
            config={
                'Accumulator': {
                    'grid_energy': {
                        'extractor': 'sum'}}},
            files=[('bin/user', ['bin/user/envoy.py'])]
            )
