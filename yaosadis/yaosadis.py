#!/usr/bin/env python3
################################################################################
# Copyright (c) 2017 Genome Research Ltd.
#
# Author: Joshua C. Randall <jcrandall@alum.mit.edu>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <http://www.gnu.org/licenses/>.
################################################################################

import argparse
import ast
import json
import os
import re
import sys
import types

from jinja2 import Template
from jinja2 import exceptions as jinja_exc

from jinjath import TemplateWithSource, JinjaTemplateAction, set_template_kwargs

###############################################################################
# Default inventory name template:
# names the ansible `inventory_name` after the (guaranteed unique) Terraform
# `resource_uuid`
###############################################################################
DEFAULT_ANSIBLE_INVENTORY_NAME_TEMPLATE='{{ uuid }}'

###############################################################################
# Default groups template:
# assign all resources to the `all` group
###############################################################################
DEFAULT_ANSIBLE_GROUPS_TEMPLATE='all'

###############################################################################
# Default resource filter:
# include all supported Terraform providers of compute instance/machines
###############################################################################
# List of providers with link to documentation:
# alicloud_instance: https://www.terraform.io/docs/providers/alicloud/r/instance.html
# aws_instance: https://www.terraform.io/docs/providers/aws/r/instance.html
# clc_server: https://www.terraform.io/docs/providers/clc/r/server.html
# cloudstack_instance: https://www.terraform.io/docs/providers/cloudstack/r/instance.html
# digitalocean_droplet: https://www.terraform.io/docs/providers/do/r/droplet.html
# docker_container: https://www.terraform.io/docs/providers/docker/r/container.html
# google_compute_instance: https://www.terraform.io/docs/providers/google/r/compute_instance.html
# azurem_virtual_machine: https://www.terraform.io/docs/providers/azurerm/r/virtual_machine.html
# azure_instance: https://www.terraform.io/docs/providers/azure/r/instance.html
# openstack_compute_instance_v2: https://www.terraform.io/docs/providers/openstack/r/compute_instance_v2.html
# profitbricks_server: https://www.terraform.io/docs/providers/profitbricks/r/profitbricks_server.html
# scaleway_server: https://www.terraform.io/docs/providers/scaleway/r/server.html
# softlayer_virtual_guest: https://www.terraform.io/docs/providers/softlayer/r/virtual_guest.html
# triton_machine: https://www.terraform.io/docs/providers/triton/r/triton_machine.html
# vsphere_virtual_machine: https://www.terraform.io/docs/providers/vsphere/r/virtual_machine.html
###############################################################################
DEFAULT_ANSIBLE_RESOURCE_FILTER_TEMPLATE='{{ resource.type == "instance" }}'

###############################################################################
# Default host vars template:
# set all primary attributes as host_vars prefixed by 'tf_' and set `host_name`
# based on IP (v6 if available, otherwise v4; public if available, otherwise
# private/other).
###############################################################################
# IP address attributes for each provider, according to terraform docs:
# alicloud_instance: public_ip, private_ip
# aws_instance: public_ip, private_ip
# clc_server: (attribute undocumented, so this is based on arguments) private_ip_address
# cloudstack_instance: (attribute undocumented, so this is based on arguments) ip_address
# digitalocean_droplet: ipv4_address, ipv6_address, ipv6_address_private, ipv4_address_private
# docker_container: ip_address
# google_compute_instance: network_interface.0.access_config.0.assigned_nat_ip, network_interface.0.address
# azurem_virtual_machine: UNDOCUMENTED
# azure_instance: vip_address, ip_address
# openstack_compute_instance_v2: access_ip_v6, access_ip_v4, network/floating_ip, network/fixed_ip_v6, network/fixed_ip_v4
# profitbricks_server: UNDOCUMENTED
# scaleway_server: public_ip, private_ip
# softlayer_virtual_guest: (attribute undocumented, so this is based on arguments) ipv4_address, ipv4_address_private
# triton_machine: primaryip
# vsphere_virtual_machine: network_interface/ipv6_address, network_interface/ipv4_address
###############################################################################
DEFAULT_ANSIBLE_HOST_VARS_TEMPLATE="""ansible_host={{ accessIPv6
                                                | default(accessIPv4, true)
                                                | default(interface_ip, true)}}
                                      {% set newline = joiner("\n") -%}
                                      {% for attr, value in resource.items() -%}
                                        {{ newline() }}os_{{ attr }}={{ value }}
                                      {%- endfor -%}
                                      """

set_template_kwargs({'trim_blocks': True, 'lstrip_blocks': True, 'autoescape': False})

def process_openstack_info(args, openstack_info):
    openstack_info_data = {}
    groups = {}
    hosts = {}
    for resource_uuid in openstack_info:
        args.debug and print("Processing resource name %s" % (resource_uuid), file=sys.stderr)
        host_vars = {}
        resource = Resource(resource_uuid, openstack_info[resource_uuid])
        try:
            filter_value = args.ansible_resource_filter_template.render(resource)
        except jinja_exc.UndefinedError as e:
            sys.exit("Error rendering resource filter template: %s (template was '%s')" % (e, args.ansible_resource_filter_template.source()))
        if filter_value == "False":
            continue
        elif filter_value != "True":
            raise ValueError("Unexpected value returned from ansible_resource_filter_template: %s (template was [%s])" % (filter_value, args.ansible_resource_filter_template.source()))
        try:
            inventory_name = args.ansible_inventory_name_template.render(resource)
        except jinja_exc.UndefinedError as e:
            sys.exit("Error rendering inventory name template: %s (template was '%s')" % (e, args.ansible_inventory_name_template.source()))
        args.debug and print("Rendered ansible_inventory_name_template as '%s' for %s" % (inventory_name, resource_uuid), file=sys.stderr)
        try:
            group_names = re.split('\s*\n\s*', args.ansible_groups_template.render(resource))
        except jinja_exc.UndefinedError as e:
            sys.exit("Error rendering groups template: %s (template was '%s')" % (e, args.ansible_groups_template.source()))
        args.debug and print("Rendered ansible_groups_template as '%s' for %s" % (group_names, resource_uuid), file=sys.stderr)
        for group_name in group_names:
            if group_name not in groups:
                groups[group_name] = {}
                groups[group_name]['hosts'] = []
            args.debug and print("'%s' added to group '%s' for %s" % (inventory_name, group_name, resource_uuid), file=sys.stderr)
            groups[group_name]['hosts'].append(inventory_name)
        try:
            host_var_key_values = re.split('\s*\n\s*', args.ansible_host_vars_template.render(resource))
        except jinja_exc.UndefinedError as e:
            sys.exit("Error rendering host_vars template: %s (template was '%s')" % (e, args.ansible_host_vars_template.source()))
        args.debug and print("Rendered ansible_host_vars_template as '%s' for %s" % (host_var_key_values, resource_uuid), file=sys.stderr)
        for key_value in host_var_key_values:
            key_value = key_value.strip()
            if key_value == "":
                continue
            key_value = key_value.split('=', 1)
            key = key_value[0].strip()
            if len(key_value) < 2:
                print("WARNING: no '=' in assignment '%s' rendered from ansible_host_vars_template [%s]" % (key_value, args.ansible_host_vars_template.source()), file=sys.stderr)
                value = ""
            else:
                value = key_value[1].strip()
                if value.startswith('['):
                    value = ast.literal_eval(value)
                elif value.startswith('{'):
                    value = ast.literal_eval(value)
            host_vars[key] = value
            args.debug and print("host_var '%s' set to '%s' for %s" % (key, value, resource_uuid), file=sys.stderr)
        if inventory_name not in hosts:
            hosts[inventory_name] = host_vars
        else:
            sys.exit("inventory_name was not unique across OpenStack resources: '%s' was a duplicate" % (inventory_name))
    openstack_info_data['groups'] = groups
    openstack_info_data['hosts'] = hosts
    return openstack_info_data


def list_groups(openstack_info_data):
    meta = {"hostvars": openstack_info_data['hosts']}
    list_with_meta = openstack_info_data['groups']
    list_with_meta['_meta'] = meta
    return list_with_meta

def get_host(openstack_info_data, inventory_name):
    return openstack_info_data['hosts'].get(inventory_name, {})

def main():
    parser = argparse.ArgumentParser(description='OpenStack Ansible Inventory')
    parser.add_argument('--list', help='List inventory', action='store_true', default=False)
    parser.add_argument('--host', help='Get hostvars for a specific host', default=None)
    parser.add_argument('--debug', help='Print additional debugging information to stderr', action='store_true', default=False)
    parser.add_argument('--info', help="Location of OpenStack .openstack_info file (default: environment variable OPENSTACK_INFO or 'openstack.info' in the current directory)", type=argparse.FileType('r'), default=os.getenv('OPENSTACK_INFO', 'openstack.info'), dest='openstack_info')
    parser.add_argument('--ansible-inventory-name-template', help="A jinja2 template used to generate the ansible `host` (i.e. the inventory name) from a OpenStack resource. (default: environment variable OSI_ANSIBLE_INVENTORY_NAME_TEMPLATE or `%s`)" % (DEFAULT_ANSIBLE_INVENTORY_NAME_TEMPLATE), default=get_template_default('OSI_ANSIBLE_INVENTORY_NAME_TEMPLATE', default=DEFAULT_ANSIBLE_INVENTORY_NAME_TEMPLATE), action=JinjaTemplateAction)
    parser.add_argument('--ansible-host-vars-template', help="A jinja2 template used to generate a newline separated list (with optional whitespace before or after the newline, which will be stripped\
    ) of ansible host_vars settings (as '<key>=<value>' pairs) from a OpenStack resource. (default: environment variable OSI_ANSIBLE_HOST_VARS_TEMPLATE or if not set, a template that maps all OpenStack attributes to ansible host_vars prefixed by 'os_' as well as setting 'ansible_host' to the IP address)", default=get_template_default('OSI_ANSIBLE_HOST_VARS_TEMPLATE', default=DEFAULT_ANSIBLE_HOST_VARS_TEMPLATE), action=JinjaTemplateAction)
    parser.add_argument('--ansible-groups-template', help="A jinja2 template used to generate a newline separated list (with optional whitespace before or after the newline, which will be stripped) of ansible `group` names to which the resource should belong. (default: environment variable OSI_ANSIBLE_GROUPS_TEMPLATE or `%s`])" % (DEFAULT_ANSIBLE_GROUPS_TEMPLATE), default=get_template_default('OSI_ANSIBLE_GROUPS_TEMPLATE', default=DEFAULT_ANSIBLE_GROUPS_TEMPLATE), action=JinjaTemplateAction)
    parser.add_argument('--ansible-resource-filter-template', help="A jinja2 template used to filter OpenStack resources. This template is rendered for each resource and should evaluate to either the string 'True' to include the resource or 'False' to exclude it from the output.", default=get_template_default('OSI_ANSIBLE_RESOURCE_FILTER_TEMPLATE', default=DEFAULT_ANSIBLE_RESOURCE_FILTER_TEMPLATE), action=JinjaTemplateAction)
    args = parser.parse_args()

    args.debug and print("Parsing JSON from %s" % (args.openstack_info), file=sys.stderr)
    openstack_info = json.load(args.openstack_info)
    ansible_data = {}
    args.debug and print("Processing openstack_info data", file=sys.stderr)
    openstack_info_data = process_openstack_info(args, openstack_info)
    if args.list:
        ansible_data = list_groups(openstack_info_data)
    elif args.host is not None:
        ansible_data = get_host(openstack_info_data, args.host)
    else:
        sys.exit("nothing to do (please specify either '--list' or '--host <INVENTORY_NAME>')")
    print(json.dumps(ansible_data))


class Resource(dict):
    def __init__(self, resource_uuid, resource_dict):
        super().__init__({'resource': resource_dict})
        self['uuid'] = resource_uuid

def get_template_default(*env_vars, default=''):
    template_source = None
    for var in env_vars:
        value = os.getenv(var, None)
        if value is not None:
            template_source = value
            break
    if template_source is None:
        template_source = default
    return TemplateWithSource(template_source)

if __name__ == '__main__':
    main()
