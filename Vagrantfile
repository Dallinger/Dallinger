# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/xenial64"

  config.vm.provider "virtualbox" do |vb|
      vb.customize ["modifyvm", :id, "--natdnsproxy1", "on"]
      vb.customize ["modifyvm", :id, "--natdnshostresolver1", "on"]
  end

  config.vm.network "forwarded_port", guest: 5000, host: 5000, auto_correct: true

  config.vm.provision "shell", privileged: false, inline: <<-SHELL
    sudo apt-get update
    sudo apt-get install -y python2.7 python-pip
    
    # Postgres setup
    sudo apt-get install -y postgresql-9.5 postgresql-server-dev-9.5 
    sudo -u postgres createuser -ds ubuntu
    createdb dallinger
    # trust all connections
    sudo sed /etc/postgresql/9.5/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sudo service postgresql reload
    
    sudo apt-get install -y enchant
    sudo pip install pyenchant
    cd /vagrant
    sudo pip install -r dev-requirements.txt
    sudo python setup.py develop

    dallinger setup
    

  SHELL
end
