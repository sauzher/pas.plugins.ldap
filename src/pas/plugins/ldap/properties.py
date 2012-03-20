import ldap
import logging
from odict import odict
from node.ext.ldap.scope import (
    BASE,
    ONELEVEL,
    SUBTREE,
)
from node.ext.ldap.interfaces import (
    ILDAPProps,
    ILDAPUsersConfig,
    ILDAPGroupsConfig,
)
from node.ext.ldap.ugm import Ugm
from node.ext.ldap.properties import (
     MULTIVALUED_DEFAULTS,
     BINARY_DEFAULTS,
)
from zope.interface import implements
from zope.component import (
    adapts,
    queryUtility,
)
import transaction
import yafowil.zope2
import yafowil.widget.array
from yafowil.base import UNSET
from yafowil.controller import Controller
from yafowil.yaml import parse_from_YAML
from zope.i18nmessageid import MessageFactory
from persistent.dict import PersistentDict
from Products.Five import BrowserView
from pas.plugins.ldap.interfaces import (
    ILDAPPlugin,
    ICacheSettingsRecordProvider,
)
from pas.plugins.ldap.defaults import DEFAULTS

logger = logging.getLogger('pas.plugins.ldap')

_ = MessageFactory('pas.plugins.ldap')


class BasePropertiesForm(BrowserView):
    
    scope_vocab = [
        (str(BASE), 'BASE'),
        (str(ONELEVEL), 'ONELEVEL'),
        (str(SUBTREE), 'SUBTREE'),
    ]
    
    static_attrs_users  = ['rdn', 'id', 'login']
    static_attrs_groups = ['rdn', 'id']

    @property
    def plugin(self):
        raise NotImplementedError()

    def next(self, request):
        raise NotImplementedError()

    @property
    def action(self):
        return self.next({}) 

    def form(self):
        # make configuration data available on form context
        self.props =  ILDAPProps(self.plugin)
        self.users =  ILDAPUsersConfig(self.plugin)
        self.groups = ILDAPGroupsConfig(self.plugin)

        # prepare users data on form context
        self.users_attrmap = odict()
        for key in self.static_attrs_users:
            self.users_attrmap[key] = self.users.attrmap.get(key)
        
        self.users_propsheet_attrmap = odict()
        for key, value in self.users.attrmap.items():
            if key in self.static_attrs_users:
                continue
            self.users_propsheet_attrmap[key] = value

        # prepare groups data on form context
        self.groups_attrmap = odict()
        for key in self.static_attrs_groups:
            self.groups_attrmap[key] = self.groups.attrmap.get(key)
        self.groups_propsheet_attrmap = odict()
        for key, value in self.groups.attrmap.items():
            if key in self.static_attrs_groups:
                continue
            self.groups_propsheet_attrmap[key] = value

        # handle form
        form = parse_from_YAML('pas.plugins.ldap:properties.yaml', self,  _)
        controller = Controller(form, self.request)
        if not controller.next:
            return controller.rendered
        self.request.RESPONSE.redirect(controller.next)
        return u''
    
    def save(self, widget, data):
        props =  ILDAPProps(self.plugin)
        users =  ILDAPUsersConfig(self.plugin)
        groups = ILDAPGroupsConfig(self.plugin)
        def fetch(name):
            name = 'ldapsettings.%s' % name
            __traceback_info__ = name
            return data.fetch(name).extracted
        props.uri = fetch('server.uri')
        props.user = fetch('server.user')
        password = fetch('server.password')
        if password is not UNSET:
            props.password = password
        
        # XXX: probably not needed
        #props.escape_queries = fetch('server.escape_queries')
        
        # XXX: later
        #props.start_tls = fetch('server.start_tls')
        #props.tls_cacertfile = fetch('server.tls_cacertfile')
        #props.tls_cacertdir = fetch('server.tls_cacertdir')
        #props.tls_clcertfile = fetch('server.tls_clcertfile')
        #props.tls_clkeyfile = fetch('server.tls_clkeyfile')
        #props.retry_max = fetch(at('server.retry_max')
        #props.retry_delay = fetch('server.retry_delay')
        props.cache = fetch('cache.cache')
        props.memcached = fetch('cache.memcached')
        props.timeout = fetch('cache.timeout')
        users.baseDN = fetch('users.dn')
        map = odict()
        map.update(fetch('users.aliases_attrmap'))
        users_propsheet_attrmap = fetch('users.propsheet_attrmap')
        if users_propsheet_attrmap is not UNSET:
            map.update(users_propsheet_attrmap)
        users.attrmap = map
        users.scope = fetch('users.scope')
        if users.scope is not UNSET:
            users.scope = int(users.scope.strip('"'))
        users.queryFilter = fetch('users.query')
        objectClasses = fetch('users.object_classes')
        users.objectClasses = objectClasses
        users.memberOfSupport = fetch('users.memberOfSupport')
        users.account_expiration = fetch('users.account_expiration')
        users.expires_attr = fetch('users.expires_attr')
        users.expires_unit = int(fetch('users.expires_unit'))
        groups = self.groups
        groups.baseDN = fetch('groups.dn')
        map = odict()
        map.update(fetch('groups.aliases_attrmap'))
        groups_propsheet_attrmap = fetch('groups.propsheet_attrmap')
        if groups_propsheet_attrmap is not UNSET:
            map.update(groups_propsheet_attrmap)
        groups.attrmap = map
        groups.scope = fetch('groups.scope')
        if groups.scope is not UNSET:
            groups.scope = int(groups.scope.strip('"'))
        groups.queryFilter = fetch('groups.query')
        objectClasses = fetch('groups.object_classes')
        groups.objectClasses = objectClasses
        groups.memberOfSupport = fetch('groups.memberOfSupport')
        
    def connection_test(self):
        props =  ILDAPProps(self.plugin)
        users =  ILDAPUsersConfig(self.plugin)
        groups = ILDAPGroupsConfig(self.plugin)
        ugm = Ugm('test', props=props, ucfg=users, gcfg=groups)
        try:
            ugm.users
        except ldap.SERVER_DOWN, e:
            return False, _("Server Down")
        except ldap.LDAPError, e:
            return False, _('LDAP users; ') + str(e)
        except Exception, e:
            logger.exception('Non-LDAP error while connection test!')
            return False, _('Other; ') + str(e)
        try:
            ugm.groups
        except ldap.LDAPError, e:
            return False, _('LDAP Users ok, but groups not; ') + \
                   e.message['desc']
        except Exception, e:
            logger.exception('Non-LDAP error while connection test!')
            return False, _('Other; ') + str(e)
        return True, 'Connection, users- and groups-access tested successfully.'                             

def propproxy(ckey):
    def _getter(context):
        value = context.plugin.settings.get(ckey, DEFAULTS[ckey])
        return value
    def _setter(context, value):
        context.plugin.settings[ckey] = value
    return property(_getter, _setter)


class LDAPProps(object):

    implements(ILDAPProps)
    adapts(ILDAPPlugin)
    
    def __init__(self, plugin):
        self.plugin = plugin

    uri = propproxy('server.uri')
    user = propproxy('server.user')
    password = propproxy('server.password')
    
    # XXX: propably not needed
    #escape_queries = propproxy('server.escape_queries')
    
    # XXX: Later
    start_tls = propproxy('server.start_tls')
    tls_cacertfile = ''
    tls_cacertdir = ''
    tls_clcertfile = ''
    tls_clkeyfile = ''
    retry_max = 3
    retry_delay = 5

    cache = propproxy('cache.cache')
    
    def _memcached_get(self):
        recordProvider = queryUtility(ICacheSettingsRecordProvider)
        if recordProvider is not None:
            record = recordProvider()
            return record.value
        return u'feature not available'
    
    def _memcached_set(self, value):
        recordProvider = queryUtility(ICacheSettingsRecordProvider)
        if recordProvider is not None:
            record = recordProvider()
            record.value = value.decode('utf8')
        else:
            return u'feature not available'
    
    memcached = property(_memcached_get, _memcached_set)    
    
    timeout = propproxy('cache.timeout')
    
    binary_attributes = BINARY_DEFAULTS
    multivalued_attributes = MULTIVALUED_DEFAULTS
    

class UsersConfig(object):

    implements(ILDAPUsersConfig)
    adapts(ILDAPPlugin)
    
    def __init__(self, plugin):
        self.plugin = plugin
        
    strict = False

    baseDN = propproxy('users.baseDN')
    attrmap = propproxy('users.attrmap')
    scope = propproxy('users.scope')
    queryFilter = propproxy('users.queryFilter') 
    objectClasses = propproxy('users.objectClasses')
    memberOfSupport = propproxy('users.memberOfSupport')
    
    account_expiration = propproxy('users.account_expiration')
    expires_attr = propproxy('users.expires_attr')
    expires_unit = propproxy('users.expires_unit')
    
    @property
    def expiresAttr(self):
        return self.account_expiration and self.expires_attr or None
    
    @property
    def expiresUnit(self):
        return self.account_expiration and self.expires_unit or 0


class GroupsConfig(object):

    implements(ILDAPGroupsConfig)
    adapts(ILDAPPlugin)
    
    def __init__(self, plugin):
        self.plugin = plugin

    strict = False

    baseDN = propproxy('groups.baseDN')
    attrmap = propproxy('groups.attrmap')
    scope = propproxy('groups.scope')
    queryFilter = propproxy('groups.queryFilter') 
    objectClasses = propproxy('groups.objectClasses')
    memberOfSupport = propproxy('groups.memberOfSupport')
