# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/bionic64"
  config.vm.box_version = "= 20190225.0.0"
  config.vbguest.auto_update = true

  config.vm.provider "virtualbox" do |vb|
      vb.customize ["modifyvm", :id, "--natdnsproxy1", "on"]
      vb.customize ["modifyvm", :id, "--natdnshostresolver1", "on"]
      vb.cpus = 2
      vb.memory = 4096
  end

  config.vm.network "public_network",
    use_dhcp_assigned_default_route: true

  config.vm.provision "shell", privileged: false, inline: <<-SHELL
    export DEBIAN_FRONTEND=noninteractive
    export LANG=en_US.UTF-8
    sudo -E apt-get update

    # Python, git and dev dependencies
    sudo -E apt-get install -y python3-dev python3-pip python3-virtualenv python-pip python-virtualenv enchant pandoc git zip

    # Postgres setup
    sudo -E apt-get install -y postgresql-10 postgresql-server-dev-all

    # trust all connections
    sudo sed /etc/postgresql/10/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sudo sed /etc/postgresql/10/main/pg_hba.conf -e 's/peer/trust/g' --in-place
    sudo service postgresql reload
    sudo -u postgres createuser -ds vagrant
    sudo -u postgres createuser -ds dallinger -h localhost
    sudo -u postgres createdb dallinger --owner dallinger

    # Virtual environment
    echo 'source ~/venv/bin/activate' >> ~/.bashrc
    echo 'cd /vagrant' >> ~/.bashrc
    echo 'export HOST=`ifconfig | grep Ethernet -A1 | grep addr: | tail -n1 | cut -d: -f2 | cut -d " " -f1`' >> ~/.bashrc
    echo 'export TOX_WORK_DIR=/tmp' >> ~/.bashrc
    /usr/bin/virtualenv --python $(which python3) --no-site-packages ~/venv
    source ~/venv/bin/activate
    cd /vagrant

    # Documentation building dependencies
    pip install pyenchant
    pip install -r dev-requirements.txt

    # Dallinger install
    python setup.py develop
    dallinger setup
    echo '[vm]' >> ~/.dallingerconfig
    echo 'base_port = 5000' >> ~/.dallingerconfig

    # Heroku CLI installation
    sudo -E apt-get install software-properties-common
    sudo -E add-apt-repository "deb https://cli-assets.heroku.com/branches/stable/apt ./"
    curl -L https://cli-assets.heroku.com/apt/release.key | sudo apt-key add -
    sudo -E apt-get update
    sudo -E apt-get install heroku

    # Redis server
    sudo -E apt-get install redis-server -y

    # Test runner
    pip install --upgrade tox
    ln -s /vagrant/.tox /tmp

  SHELL
end
