# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/xenial64"
  config.vm.box_version = "= 20190204.3.0"
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
    # Apt setup
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
    sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -sc)-pgdg main" > /etc/apt/sources.list.d/PostgreSQL.list'
    sudo apt-get update

    # Python dependencies
    sudo apt-get install -y python3.6 python3.6-dev python2.7 python2.7-dev python-pip python-virtualenv

    # Postgres setup
    sudo apt-get install -y postgresql-10 postgresql-server-dev-10
    sudo -u postgres createuser -ds vagrant
    echo dallinger | sudo -u postgres createuser -ds dallinger -h localhost
    sudo -u postgres createdb dallinger --owner dallinger
    # trust all connections
    sudo sed /etc/postgresql/10/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sudo sed /etc/postgresql/10/main/pg_hba.conf -e 's/peer/trust/g' --in-place
    sudo service postgresql reload

    # Virtual environment
    echo 'source ~/venv/bin/activate' >> ~/.bashrc
    echo 'cd /vagrant' >> ~/.bashrc
    echo 'export HOST=`ifconfig | grep Ethernet -A1 | grep addr: | tail -n1 | cut -d: -f2 | cut -d " " -f1`' >> ~/.bashrc
    echo 'export TOX_WORK_DIR=/tmp' >> ~/.bashrc
    /usr/bin/virtualenv --python python3.6 ~/venv
    source ~/venv/bin/activate
    cd /vagrant

    # Documentation building dependencies
    sudo apt-get install -y enchant pandoc zip
    pip install pyenchant
    pip install -r dev-requirements.txt

    # Dallinger install
    python setup.py develop
    dallinger setup
    echo '[vm]' >> ~/.dallingerconfig
    echo 'base_port = 5000' >> ~/.dallingerconfig

    # Heroku CLI installation
    sudo apt-get install software-properties-common
    sudo add-apt-repository "deb https://cli-assets.heroku.com/branches/stable/apt ./"
    curl -L https://cli-assets.heroku.com/apt/release.key | sudo apt-key add -
    sudo apt-get update
    sudo apt-get install heroku

    # Redis server
    sudo apt-get install redis-server -y

    # Test runner
    pip install --upgrade tox
    ln -s /vagrant/.tox /tmp


  SHELL
end
