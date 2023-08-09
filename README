# Ansible Script for Installing Kivitendo

This repo provides an ansible playbook for a convenient way to install [kivitendo-erp](https://github.com/kivitendo/kivitendo-erp).

To run the playbook simply enter the IP of your machine into the inventory file.

The default will install kivitendo without SSL encryption.

## SSL

For SSL encryption to work you *first* need to have the necessary files in place before running the playbook.
Then you need to configure the vars.yml file.

## Running the Playbook

To run the playbook type the following command:
```
ansible-playbook --ask-become main.yml
```

## Vagrant

The included Vagrantfile allows for quick installation on a local VM.
For this to work you first have to install vagrant and virtualbox.
Then type ` vagrant up` and wait for the VM to spin up.
Your kivitendo instance is now reachable over http://localhost:8080/ .

**note:** if you just want to quickly test kivitendo without needing to print anything, it is advisable to comment out texlive-full, for a speedier install.
