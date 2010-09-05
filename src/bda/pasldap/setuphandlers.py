# Copyright (c) 2006-2010 BlueDynamics Alliance, Austria http://bluedynamics.com
# GNU General Public License (GPL)

from StringIO import StringIO

from bda.pasldap._plugin import UsersReadOnly


def isNotThisProfile(context):
    return context.readDataFile("bdapasldap_marker.txt") is None


def setupPlugin(context):
    if isNotThisProfile(context):
        return 
    out = StringIO()
    portal = context.getSite()
    pas = portal.acl_users
    installed = pas.objectIds()
    ID = 'ldap_users_readonly'
    TITLE = 'LDAP users readonly'
    if ID not in installed:
        plugin = UsersReadOnly(ID, title=TITLE)
        pas._setObject(ID, plugin)
        for info in pas.plugins.listPluginTypeInfo():
            interface = info['interface']
            if interface.providedBy(plugin):
                pas.plugins.activatePlugin(interface, plugin.getId())
                pas.plugins.movePluginsDown(
                        interface,
                        [x[0] for x in pas.plugins.listPlugins(interface)[:-1]],
                        )
    else:
        print >> out, TITLE+" already installed."
    print out.getvalue()
