#!/usr/bin/env python3

"""
Copyright (c) 2020 Ian Santopietro
Copyright (c) 2020 System76, Inc.
All rights reserved.

This file is part of Pop-Transition.

    Pop-Transition is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    Pop-Transition is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with Pop-Transition.  If not, see <https://www.gnu.org/licenses/>.

pop-transition - High-permission service
"""

import dbus
import dbus.service
import dbus.mainloop.glib
import sys
import time
import os

from apt.cache import Cache
from gi.repository import GLib, GObject

class TransitionException(dbus.DBusException):
    _dbus_error_name = 'org.pop_os.transition_system.TransitionException'

class PermissionDeniedByPolicy(dbus.DBusException):
    _dbus_error_name = 'org.pop_os.transition_system.PermissionDeniedByPolicy'

class Transition(dbus.service.Object):
    def __init__(self, conn=None, object_path=None, bus_name=None):
        super().__init__(conn, object_path, bus_name)

        self.dbus_info = None
        self.polkit = None
        self.enforce_polkit = True
        self.cache = Cache()

    @dbus.service.method(
        'org.pop_os.transition_system.Interface', 
        in_signature='as', out_signature='as',
        sender_keyword='sender', connection_keyword='conn'
    )
    def remove_packages(self, pkg_list, sender=None, conn=None):
        self._check_polkit_privilege(
            sender, conn, 'org.pop_os.transition_system.removedebs'
        )

        self.cache.update()
        self.cache.open()
        removed_pkgs = []

        for package in pkg_list:
            try:
                pkg = self.cache[package]
                pkg.mark_delete()
                removed_pkgs.append(package)
            except:
                print(f'Could not mark {package} for removal')

        self.cache.commit()
        self.cache.close()

        return removed_pkgs
    
    @dbus.service.method(
        'org.pop_os.transition_system.Interface', 
        in_signature='', out_signature='',
        sender_keyword='sender', connection_keyword='conn'
    )
    def exit(self, sender=None, conn=None):
        self.cache.close()
        mainloop.quit()

    def _check_polkit_privilege(self, sender, conn, privilege):
        '''Verify that sender has a given PolicyKit privilege.
        sender is the sender's (private) D-BUS name, such as ":1:42"
        (sender_keyword in @dbus.service.methods). conn is
        the dbus.Connection object (connection_keyword in
        @dbus.service.methods). privilege is the PolicyKit privilege string.
        This method returns if the caller is privileged, and otherwise throws a
        PermissionDeniedByPolicy exception.
        '''

        if sender is None and conn is None:
            # Called locally, not through D-Bus
            return
        
        if not self.enforce_polkit:
            # For testing
            return
        
        if self.dbus_info is None:
            self.dbus_info = dbus.Interface(conn.get_object('org.freedesktop.DBus',
                '/org/freedesktop/DBus/Bus', False), 'org.freedesktop.DBus')
        pid = self.dbus_info.GetConnectionUnixProcessID(sender)
        
        if self.polkit is None:
            self.polkit = dbus.Interface(dbus.SystemBus().get_object(
                'org.freedesktop.PolicyKit1',
                '/org/freedesktop/PolicyKit1/Authority', False),
                'org.freedesktop.PolicyKit1.Authority'
            )
        
        try:
            (is_auth, _, details) = self.polkit.CheckAuthorization(
                ('unix-process', {'pid': dbus.UInt32(pid, variant_level=1),
                'start-time': dbus.UInt64(0, variant_level=1)}), 
                privilege, {'': ''}, dbus.UInt32(1), '', timeout=600
            )

        except dbus.DBusException as e:
            if e._dbus_error_name == 'org.freedesktop.DBus.Error.ServiceUnknown':
                # polkitd timed out, connect again
                self.polkit = None
                return self._check_polkit_privilege(sender, conn, privilege)
            else:
                raise
        
        if not is_auth:
            raise PermissionDeniedByPolicy(privilege)

if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()
    name = dbus.service.BusName('org.pop_os.transition_system', bus)
    object = Transition(bus, '/PopTransition')
    mainloop = GObject.MainLoop()

    mainloop.run()