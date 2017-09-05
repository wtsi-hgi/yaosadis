[![PyPI version](https://badge.fury.io/py/yaosadis.svg)](https://badge.fury.io/py/yaosadis)

Yet Another OpenStack Ansible Dynamic Inventory Script (yaosadis)
=================================================================

An [ansible dynamic inventory](https://docs.ansible.com/ansible/intro_dynamic_inventory.html) script which takes [openstack-info](https://github.com/wtsi-hgi/openstack-info) JSON files as input.

In contrast with other OpenStack ansible dynamic inventory scripts, this one aims to be configurable to match your environment. It implements this using [Jinja2][jinja2] templates to specify how OpenStack resource attributes should be mapped onto ansible inventory name, group, and host_vars.

This is a sister project to [yatadis](https://github.com/wtsi-hgi/yatadis) which does the same thing but using Terraform state files as input.

Basic usage
-----------

Ansible calls dynamic inventory scripts with either the `--list` or `--host` option, but no additional arguments. For that reason, yaosadis accepts all of its options from environment variables:
* OS_STATE: a path to a local openstack-info.json file (default: openstack-info.json in the current direct§ory)
* OS_ANSIBLE_INVENTORY_NAME_TEMPLATE: a [Jinja2][jinja2] template string that is applied to each OpenStack resource to generate the ansible inventory name (default: `{{ uuid }}` which is the OpenStack UUID).
* OS_ANSIBLE_GROUPS_TEMPLATE: a [Jinja2][jinja2] template string that is applied to each OpenStack resource to generate a newline-delimited list of ansible groups to which the resource should belong (default: `all` which simply assigns all hosts to the `all` group)
* OS_ANSIBLE_RESOURCE_FILTER_TEMPLATE: a [Jinja2][jinja2] template string that is applied to each OpenStack resource and should produce either `True` (to include the resource) or `False` (to exclude the resource). (default: `{{ type == "instance" }}` which is suitable to limit to only OpenStack instances and not other resource types.
* OS_ANSIBLE_HOST_VARS_TEMPLATE: a [Jinja2][jinja2] template string that is applied to each OpenStack resource and should generate a newline-delimited list of host_var settings in the format `<host_var>=<value>`. (default: a template that will set `ansible_host` to the IP of the instance as well as setting all resource attributes prefixed with `os_` - see source code for details).

If you are happy with the defaults, and can arrange for the OS_STATE environment variable to be set to the path to the openstack-info.json file, then you can just install the yaosadis.py script in the ansible inventory directory, make sure it is executable, and that all of the python modules it depends on are installed on the machine on which you run ansible.

In practice, you will most likely want to call yaosadis.py from a wrapper script (such as a bash script) that you install into the inventory directory in place of yaosadis.py itself and which sets those variables appropriately. For example, here is a simple shell script that simply invokes yaosadis.py after setting the path to the openstack-info.json file:
```
#!/bin/bash

export OS_STATE=/path/to/openstack-info.json
/path/to/yaosadis.py $@
```

You can also specify any of these options on the command line (for testing purposes) - the command line argument is simply the environment variable name without the "OS" prefix:
```
./yaosadis.py --list --state /path/to/openstack-info.json
```

Adding OpenStack resources to ansible groups
--------------------------------------------

The defaults may be all you need, as all of the primary attributes of each OpenStack instance will be available in ansible as host_vars with the prefix "os_", and you can use ansible dynamic groups (using the [group_by module](https://docs.ansible.com/ansible/group_by_module.html) to add hosts to groups based on those host_vars values).

For example, in your site playbook you might add the following:
```
- hosts: all
  tasks:
    - group_by: key=os_image_{{ os_image.name }}
```

If you had a resource with a OpenStack image of `ubuntu_16.04` then it should now be a member of the ansible group `os_image_ubuntu_16.04`

Alternatively, yaosadis can assign hosts to ansible groups for you without the need for ansible's dynamic group functionality.

To do this you will need to set the `OS_ANSIBLE_GROUPS_TEMPLATE` [Jinja2][jinja2] template such that it returns a newline-delimited list of groups to which a host should belong.

For example, to add all instances to a group named after the value of a metadata key called `ansible_group`, you could use the following wrapper script:

```
#!/bin/bash
export OS_ANSIBLE_GROUPS_TEMPLATE='{{ ["all", metadata.ansible_group] | join("\n") }}'
export OS_STATE=/path/to/openstack-info.json
/path/to/yaosadis.py $@
```

Template context
----------------

The context provided to the Jinja2 templates is a dict-like Resource object containing the same fields as the openstack-info resource fields. There is also an additional top-level entry called 'uuid' which contains the resource uuid (i.e. the key value of the openstack-info top-level dict).

Advanced host_vars templating
-----------------------------

As a special case, since ansible host_vars can contain complex data structures, if the values output by the host_vars template are a dict or a list, they will be evaluated as such rather than as a string, so that the resulting ansible host_vars entry can contain complex data structures.

For example, the following (uninteresting) example would assign the foo_dict and abc123_list host_vars to every resource:

```
#!/bin/bash
export OS_ANSIBLE_HOST_VARS_TEMPLATE=$(cat <<EOF
foo_dict={'foo': 1, 'bar': 2, 'baz': 3}
abc123_list=['a', 'b', 'c', 1, 2, 3]
EOF
)
export OS_STATE=/path/to/openstack-info.json
/path/to/yaosadis.py $@
```

[jinja2]: <http://jinja.pocoo.org/>
