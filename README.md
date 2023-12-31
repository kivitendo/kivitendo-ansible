# Ansible Script for Installing kivitendo on Ubuntu 22.04

This repo provides an ansible playbook for a convenient way to install
[kivitendo-erp](https://github.com/kivitendo/kivitendo-erp) on Ubuntu 22.04.

This playbook needs ansible version >=2.10 to work, it also relies on a few dependencies from ansible community.

So if you are using ubuntu, make sure you install `ansible` instead of `ansible-core`.

(It was developed on a control node running Ubuntu 22.04)

For more information on ansible visit their [official documentation](https://docs.ansible.com/).

## Usage

First clone this repo with: 
```
git clone https://github.com/kivitendo/kivitendo-ansible.git
cd kivitendo-ansible
```

To run the playbook simply enter the IP of your machine into the inventory file (see comments for examples).

Then run the following command:
```
ansible-playbook --ask-become main.yml
```

After the Playbook has finished, you need to manually create the database,
client, and user table in the admin interface.

## SSL

The default will install kivitendo **without** SSL encryption.

For SSL encryption to work you **first** need to have the necessary files (e.g.
the certificates) in place before running the playbook.
Now you have to adjust the settings in the vars.yml file.

## Basic Auth

To secure the access to the web interface you can enable basic auth in vars.yml.

Set `use_basic_auth` to true to enable it. User and password can be entered below the option.

## Vagrant

The included Vagrantfile allows for quick installation on a local VM.
For this to work you first have to install vagrant and virtualbox.
Then type ` vagrant up` and wait for the VM to spin up.
Your kivitendo instance is now reachable over http://localhost:8080/ .

**note:** if you just want to quickly test kivitendo without needing to print
anything, it is advisable to comment out texlive-full, for a speedier install.
