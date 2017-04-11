# -*- coding: utf-8 -*-
from __future__ import absolute_import

import copy
import os
import re
import shlex

from abc import ABCMeta, abstractmethod

from six import string_types, add_metaclass
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from container.utils.visibility import getLogger
logger = getLogger(__name__)

"""
Translate the container.yml derived config into an Ansible playbook/role
to deploy the services.
"""


@add_metaclass(ABCMeta)
class K8sBaseDeploy(object):

    DEFAULT_API_VERSION = 'v1'
    CONFIG_KEY = 'k8s'

    def __init__(self, services=None, project_name=None, volumes=None, auth=None, namespace_name=None, 
                 namespace_description=None, namespace_display_name=None):
        self._services = services
        self._project_name = project_name
        self._namespace_name = namespace_name
        self._namespace_description = namespace_description
        self._namespace_display_name = namespace_display_name
        self._volumes = volumes
        self._auth = auth

    @property
    def auth(self):
        return self._auth

    @auth.setter
    def auth(self, auth):
        self._auth = auth

    @property
    def namespace_name(self):
        return self._namespace_name

    @namespace_name.setter
    def namespace_name(self, namespace_name):
        self._namespace_name = namespace_name

    @property
    def namespace_description(self):
        return self._namespace_description

    @namespace_description.setter
    def namespace_description(self, namespace_description):
        self._namespace_description = namespace_description

    @property
    def namespace_display_name(self):
        return self._namespace_display_name

    @namespace_display_name.setter
    def namespace_display_name(self, namespace_display_name):
        self._namespace_display_name = namespace_display_name

    @abstractmethod
    def get_namespace_task(self, state='present'):
        pass

    def get_services_templates(self):
        """ Generate a service configuration """
        def _create_service(name, service):
            template = CommentedMap()
            state = 'present'
            if service.get(self.CONFIG_KEY, {}).get('state'):
                state = service[self.CONFIG_KEY]['state']
            if state == 'present':
                ports = self.get_service_ports(service)
                if ports:
                    template['apiVersion'] = self.DEFAULT_API_VERSION
                    template['kind'] = 'Service'
                    labels = CommentedMap([
                        ('app', self._namespace_name),
                        ('service', name)
                    ])
                    template['metadata'] = CommentedMap([
                        ('name', name),
                        ('namespace', self._namespace_name),
                        ('labels', copy.deepcopy(labels))
                    ])
                    template['spec'] = CommentedMap([
                        ('selector', copy.deepcopy(labels)),
                        ('ports', ports)
                    ])
                    #TODO: should the type always be LoadBalancer?
                    for port in template['spec']['ports']:
                        if port['port'] != port['targetPort']:
                            template['spec']['type'] = 'LoadBalancer'
                            break
            return template

        templates = CommentedSeq()
        if self._services:
            for name, service in self._services.items():
                template = _create_service(name, service)
                if template:
                    templates.append(template)

                if service.get('links'):
                    # create services for aliased links
                    for link in service['links']:
                        if ':' in link:
                            service_name, alias = link.split(':')
                            alias_config = self._services.get(service_name)
                            if alias_config:
                                new_service = _create_service(alias, alias_config)
                                if new_service:
                                    templates.append(new_service)
        return templates

    def get_service_tasks(self):
        # TODO Support state 'absent'
        module_name='k8s_v1_service'
        tasks = CommentedSeq()
        for template in self.get_services_templates():
            task = CommentedMap()
            task['name'] = 'Create service'
            task[module_name] = CommentedMap()
            task[module_name]['state'] = 'present'
            if self._auth:
                for key in self._auth:
                    task[module_name][key] = self._auth[key]
            task[module_name]['resource_definition'] = template
            tasks.append(task)
        return tasks

    IGNORE_DIRECTIVES = [
        'build',
        'expose',
        'labels',
        'links',
        'cgroup_parent',
        'dev_options',
        'devices',
        'depends_on',
        'dns',
        'dns_search',
        'env_file',        # TODO: build support for this?
        'user',            # TODO: needs to map to securityContext.runAsUser, which requires a UID
        'extends',
        'extrenal_links',
        'extra_hosts',
        'ipv4_address',
        'ipv6_address'
        'labels',
        'links',           # TODO: Add env vars?
        'logging',
        'log_driver',
        'lop_opt',
        'net',
        'network_mode',
        'networks',
        'restart',         # TODO: for replication controller, should be Always
        'pid',             # TODO: could map to pod.hostPID
        'security_opt',
        'stop_signal',
        'ulimits',
        'cpu_shares',
        'cpu_quota',
        'cpuset',
        'domainname',
        'hostname',
        'ipc',
        'mac_address',
        'mem_limit',
        'memswap_limit',
        'shm_size',
        'tmpfs',
        'options',
        'volume_driver',
        'volumes_from',   # TODO: figure out how to map?
        'roles',
        'k8s',
        'openshift',
    ]

    DOCKER_TO_KUBE_CAPABILITY_MAPPING = dict(
        SETPCAP='CAP_SETPCAP',
        SYS_MODULE='CAP_SYS_MODULE',
        SYS_RAWIO='CAP_SYS_RAWIO',
        SYS_PACCT='CAP_SYS_PACCT',
        SYS_ADMIN='CAP_SYS_ADMIN',
        SYS_NICE='CAP_SYS_NICE',
        SYS_RESOURCE='CAP_SYS_RESOURCE',
        SYS_TIME='CAP_SYS_TIME',
        SYS_TTY_CONFIG='CAP_SYS_TTY_CONFIG',
        MKNOD='CAP_MKNOD',
        AUDIT_WRITE='CAP_AUDIT_WRITE',
        AUDIT_CONTROL='CAP_AUDIT_CONTROL',
        MAC_OVERRIDE='CAP_MAC_OVERRIDE',
        MAC_ADMIN='CAP_MAC_ADMIN',
        NET_ADMIN='CAP_NET_ADMIN',
        SYSLOG='CAP_SYSLOG',
        CHOWN='CAP_CHOWN',
        NET_RAW='CAP_NET_RAW',
        DAC_OVERRIDE='CAP_DAC_OVERRIDE',
        FOWNER='CAP_FOWNER',
        DAC_READ_SEARCH='CAP_DAC_READ_SEARCH',
        FSETID='CAP_FSETID',
        KILL='CAP_KILL',
        SETGID='CAP_SETGID',
        SETUID='CAP_SETUID',
        LINUX_IMMUTABLE='CAP_LINUX_IMMUTABLE',
        NET_BIND_SERVICE='CAP_NET_BIND_SERVICE',
        NET_BROADCAST='CAP_NET_BROADCAST',
        IPC_LOCK='CAP_IPC_LOCK',
        IPC_OWNER='CAP_IPC_OWNER',
        SYS_CHROOT='CAP_SYS_CHROOT',
        SYS_PTRACE='CAP_SYS_PTRACE',
        SYS_BOOT='CAP_SYS_BOOT',
        LEASE='CAP_LEASE',
        SETFCAP='CAP_SETFCAP',
        WAKE_ALARM='CAP_WAKE_ALARM',
        BLOCK_SUSPEND='CAP_BLOCK_SUSPEND'
    )

    @abstractmethod
    def get_deployment_templates(self, default_api=None, default_kind=None, default_strategy=None):

        def _service_to_container(name, service):
            container = CommentedMap()
            container['name'] = name
            container['securityContext'] = CommentedMap()
            container['state'] = 'present'

            volumes = []
            pod = {}
            for key, value in service.items():
                if key in self.IGNORE_DIRECTIVES:
                    pass
                elif key == 'cap_add':
                    if not container['securityContext'].get('Capabilities'):
                        container['securityContext']['Capabilities'] = dict(add=[], drop=[])
                    for cap in value:
                        if self.DOCKER_TO_KUBE_CAPABILITY_MAPPING[cap]:
                            container['securityContext']['Capabilities']['add'].append(
                                self.DOCKER_TO_KUBE_CAPABILITY_MAPPING[cap])
                elif key == 'cap_drop':
                    if not container['securityContext'].get('Capabilities'):
                        container['securityContext']['Capabilities'] = dict(add=[], drop=[])
                    for cap in value:
                        if self.DOCKER_TO_KUBE_CAPABILITY_MAPPING[cap]:
                            container['securityContext']['Capabilities']['drop'].append(
                                self.DOCKER_TO_KUBE_CAPABILITY_MAPPING[cap])
                elif key == 'command':
                    if isinstance(value, string_types):
                        container['args'] = shlex.split(value)
                    else:
                        container['args'] = value
                elif key == 'container_name':
                        container['name'] = value
                elif key == 'entrypoint':
                    if isinstance(value, string_types):
                        container['command'] = shlex.split(value)
                    else:
                        container['command'] = value
                elif key == 'environment':
                    expanded_vars = self.expand_env_vars(value)
                    if expanded_vars:
                        container['env'] = expanded_vars
                elif key in ('ports', 'expose'):
                    if not container.get('ports'):
                        container['ports'] = []
                    self.add_container_ports(value, container['ports'])
                elif key == 'privileged':
                    container['securityContext']['privileged'] = value
                elif key == 'read_only':
                    container['securityContext']['readOnlyRootFileSystem'] = value
                elif key == 'stdin_open':
                    container['stdin'] = value
                elif key == 'volumes':
                    vols, vol_mounts = self.get_k8s_volumes(value)
                    if vol_mounts:
                        container['volumeMounts'] = vol_mounts
                    if vols:
                        volumes += vols
                elif key == 'working_dir':
                    container['workingDir'] = value
                else:
                    container[key] = value

            # Translate options:
            if service.get(self.CONFIG_KEY):
                for key, value in service[self.CONFIG_KEY].items():
                    if key == 'seLinuxOptions':
                        container['securityContext']['seLinuxOptions'] = value
                    elif key == 'runAsNonRoot':
                        container['securityContext']['runAsNonRoot'] = value
                    elif key == 'runAsUser':
                        container['securityContext']['runAsUser'] = value
                    elif key == 'replicas':
                        pod['replicas'] = value
                    elif key == 'state':
                        pod['state'] = value

            return container, volumes, pod

        templates = CommentedSeq()
        for name, service_config in self._services.items():

            container, volumes, pod = _service_to_container(name, service_config)

            labels = CommentedMap([
                ('app', self._namespace_name),
                ('service', name)
            ])

            state = 'present'
            if pod.get('state'):
                state = pod.pop('state')

            if state == 'present':
                template = CommentedMap()
                template['apiVersion'] = default_api
                template['kind'] = default_kind
                template['metadata'] = CommentedMap([
                    ('name', name),
                    ('labels', copy.deepcopy(labels)),
                    ('namespace', self._namespace_name)
                ])
                template['spec'] = CommentedMap()
                template['spec']['template'] = CommentedMap()
                template['spec']['template']['metadata'] = CommentedMap([('labels', copy.deepcopy(labels))])
                template['spec']['template']['spec'] = CommentedMap([
                    ('containers', [container])    # TODO: allow multiple pods in a container
                ])
                template['spec']['replicas'] = 1
                template['spec']['strategy'] = CommentedMap([('type', default_strategy)])

                if volumes:
                    template['spec']['template']['spec']['volumes'] = volumes

                if pod:
                    for key, value in pod.items():
                        if key == 'replicas':
                            template['spec'][key] = value
                        elif key == 'strategy_type':
                            template['spec']['strategy']['type'] = value

                templates.append(template)
        return templates

    @abstractmethod
    def get_deployment_tasks(self, module_name=None):
        tasks = CommentedSeq()
        for template in self.get_deployment_templates():
            task = CommentedMap()
            task['name'] = 'Create deployment'
            task[module_name] = CommentedMap()
            task[module_name]['state'] = 'present'
            if self._auth:
                for key in self._auth:
                    task[module_name][key] = self._auth[key]
            task[module_name]['resource_definition'] = template
            tasks.append(task)
        for name, service_config in self._services.items():
            # Include any services where k8s.state is 'absent'
            if service_config.get(self.CONFIG_KEY, {}).get('state', 'present') == 'absent':
                task['name'] = 'Remove deployment'
                task[module_name] = CommentedMap()
                task[module_name]['state'] = 'absent'
                if self._auth:
                    for key in self._auth:
                        task[module_name][key] = self._auth[key]
                task[module_name]['name'] = name
                task[module_name]['namespace'] = self._namespace_name
                tasks.append(task)
        return tasks

    def get_pvc_templates(self):
        def _volume_to_pvc(claim):
            template = None
            if claim.get('type') == 'persistent':
                template = CommentedMap()
                template['apiVersion'] = 'v1'
                template = CommentedMap()
                template['apiVersion'] = self.DEFAULT_API_VERSION
                template['kind'] = "PersistentVolumeClaim"
                template['metadata'] = {'name': claim['claim_name']}
                template['spec'] = CommentedMap()
                template['spec']['requested']['storage'] = '1Gi'
                if claim.get('access_modes'):
                    template['spec']['accessModes'] = claim['access_modes']
                if claim.get('storage'):
                    template['spec']['requested']['storage'] = claim['storage']
                if claim.get('storage_class'):
                    if not template['metadata'].get('annotations'):
                        template['metadata']['annotations'] = {}
                    template['metadata']['annotations']['storageClass'] = claim['storage_class']  #TODO verify this syntax
                if claim.get('selector'):
                    if claim['selector'].get('match_labels'):
                        if not template['spec'].get('selector'):
                            template['spec']['selector'] = dict()
                        template['spec']['selector']['matchLabels'] = claim['match_labels']
                    if claim['selector'].get('match_expressions'):
                        if not template['spec'].get('selector'):
                            template['spec']['selector'] = dict()
                        template['spec']['selector']['matchExpressions'] = claim['match_expressions']
            elif claim.get('type') == 'volatile':
                pass
                #TODO figure out volatile storage

            return template

        templates = CommentedSeq()
        if self.volumes:
            for volname, vol_config in self._volumes.items():
                if self.CONFIG_KEY in vol_config:
                    volume = _volume_to_pvc(vol_config[self.CONFIG_KEY])
                    templates.append(volume)

        return templates

    @staticmethod
    def get_service_ports(service):
        ports = []

        def _port_in_list(port, protocol):
            found = [p for p in ports if p['port'] == int(port) and p['protocol'] == protocol]
            return len(found) > 0

        def _append_port(port, protocol):
            if not _port_in_list(port, protocol):
                ports.append(dict(
                    port=int(port),
                    targetPort=int(port),
                    protocol=protocol,
                    name='port-%s-%s' % (port, protocol.lower())
                ))

        for port in service.get('ports', []):
            protocol = 'TCP'
            if isinstance(port, string_types) and '/' in port:
                port, protocol = port.split('/')
            if isinstance(port, string_types) and ':' in port:
                _, port = port.split(':')
            _append_port(port, protocol)

        for port in service.get('expose', []):
            protocol = 'TCP'
            if isinstance(port, string_types) and '/' in port:
                port, protocol = port.split('/')
            _append_port(port, protocol)

        return ports

    @staticmethod
    def expand_env_vars(env_variables):
        """ Convert service environment attribute into dictionary of name/value pairs. """
        results = []
        if isinstance(env_variables, dict):
            results = [{'name': x, 'value': env_variables[x]} for x in list(env_variables.keys())]
        elif isinstance(env_variables, list):
            for evar in env_variables:
                parts = evar.split('=', 1)
                if len(parts) == 1:
                    results.append({'name': parts[0], 'value': None})
                elif len(parts) == 2:
                    results.append({'name': parts[0], 'value': parts[1]})
        return results

    @staticmethod
    def add_container_ports(ports, existing_ports):
        """ Determine list of ports to expose at the container level, and add to existing_ports """
        def _port_exists(port, protocol):
            found = [p for p in existing_ports if p['containerPort'] == int(port) and p['protocol'] == protocol]
            return len(found) > 0

        for port in ports:
            protocol = 'TCP'
            if isinstance(port, string_types) and '/' in port:
                port, protocol = port.split('/')
            if isinstance(port, string_types) and ':' in port:
                _, port = port.split(':')
            if not _port_exists(port, protocol):
                existing_ports.append({'containerPort': int(port), 'protocol': protocol.upper()})

    DOCKER_VOL_PERMISSIONS = ['rw', 'ro', 'z', 'Z']

    @classmethod
    def get_k8s_volumes(cls, docker_volumes):
        """ Given an array of Docker volumes return a set of volumes and a set of volumeMounts """
        volumes = []
        volume_mounts = []
        for vol in docker_volumes:
            source = None
            destination = None
            permissions = None
            if ':' in vol:
                pieces = vol.split(':')
                if len(pieces) == 3:
                    source, destination, permissions = vol.split(':')
                elif len(pieces) == 2:
                    if pieces[1] in cls.DOCKER_VOL_PERMISSIONS:
                        destination, permissions = vol.split(':')
                    else:
                        source, destination = vol.split(':')
            else:
                destination = vol

            named = False
            if destination:
                # slugify the destination to create a name
                name = re.sub(r'\/', '-', destination)
                name = re.sub(r'-', '', name, 1)

            if source:
                if re.match(r'\$', source):
                    # Source is an environment var. Skip for now.
                    continue
                elif re.match(r'[~./]', source):
                    # Source is a host path. We'll assume it exists on the host machine?
                    source = os.path.abspath(os.path.normpath(os.path.expanduser(source)))
                    volumes.append(dict(
                        name=name,
                        hostPath=dict(
                            path=source
                        )
                    ))
                else:
                    # Named volume. The volume should be defined elsewhere.
                    name = source
                    named = True
            else:
                # Volume with no source, a.k.a emptyDir
                volumes.append(dict(
                    name=name,
                    emptyDir=dict(
                        medium=""
                    ),
                ))

            if not named:
                volume_mounts.append(dict(
                    mountPath=destination,
                    name=name,
                    readOnly=(True if permissions == 'ro' else False)
                ))

        return volumes, volume_mounts
