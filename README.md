# Ansible Script for Installing kivitendo on Debian 13

This repo provides an ansible playbook for a convenient way to install
[kivitendo-erp](https://github.com/kivitendo/kivitendo-erp).

For more information on ansible visit their [official documentation](https://docs.ansible.com/).

## Usage

First clone this repo with: 
```
git clone https://github.com/kivitendo/kivitendo-ansible.git
cd kivitendo-ansible
```

To run the playbook simply enter the IP of your machine into the inventory.yaml file (see comments for examples).

Then run the following command:
```
ansible-playbook --inventory inventory.yaml main.yml
```

After the Playbook has finished, you need to manually create the database,
client, and user table in the admin interface.

## SSL

The default will install kivitendo **with** SSL encryption.

For SSL encryption to work you **first** need to have the necessary files (e.g.
the certificates) in place before running the playbook.
Now you have to adjust the settings in the vars.yml file.

## Basic Auth

To secure the access to the web interface you can enable basic auth in vars.yml.

Set `use_basic_auth` to true to enable it. User and password can be entered below the option.

