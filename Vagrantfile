# -*- mode: ruby -*-
# vi: set ft=ruby :

required_secrets = {
  "KIVITENDO_ADMIN_PASSWORD" => "kivitendo_admin_password",
  "KIVITENDO_DB_PASSWORD" => "kivitendo_db_password",
  "KIVITENDO_MASTER_KEY" => "kivitendo_master_key"
}

missing = required_secrets.keys.reject { |name| ENV.key?(name) && !ENV[name].empty? }
unless missing.empty?
  abort "Missing required environment variables: #{missing.join(', ')}"
end

Vagrant.configure("2") do |config|
  config.vm.box = "generic/debian13"
  config.vm.network "forwarded_port", guest: 80, host: 8080, host_ip: "127.0.0.1"
  config.vm.network "forwarded_port", guest: 443, host: 8443, host_ip: "127.0.0.1"

  config.vm.provision "ansible" do |ansible|
    ansible.playbook = "main.yml"
    ansible.extra_vars = required_secrets.to_h { |environment_name, variable_name|
      [variable_name, ENV.fetch(environment_name)]
    }
  end
end
