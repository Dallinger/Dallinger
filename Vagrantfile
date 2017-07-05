# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/xenial64"

  config.vm.provider "virtualbox" do |vb|
      vb.customize ["modifyvm", :id, "--natdnsproxy1", "on"]
      vb.customize ["modifyvm", :id, "--natdnshostresolver1", "on"]
      vb.cpus = 2
      vb.memory = 4096
  end



  config.vm.network "public_network",
    use_dhcp_assigned_default_route: true

  config.vm.provision "shell", privileged: false, inline: <<-SHELL
    sudo apt-get update

    # Python dependencies
    sudo apt-get install -y python2.7 python-pip

    # Postgres setup
    sudo apt-get install -y postgresql-9.5 postgresql-server-dev-9.5 
    sudo -u postgres createuser -ds ubuntu
    createdb dallinger
    # trust all connections
    sudo sed /etc/postgresql/9.5/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sudo service postgresql reload

    # Virtual environment
    echo 'source ~/venv/bin/activate' >> ~/.bashrc
    echo 'cd /vagrant' >> ~/.bashrc
    echo 'export HOST=`ifconfig | grep Ethernet -A1 | grep addr: | tail -n1 | cut -d: -f2 | cut -d " " -f1`' >> ~/.bashrc
    sudo pip install virtualenv
    virtualenv --no-site-packages ~/venv
    source ~/venv/bin/activate
    cd /vagrant

    # Documentation building dependencies
    sudo apt-get install -y enchant pandoc zip
    pip install pyenchant
    pip install -r dev-requirements.txt

    # Dallinger install
    python setup.py develop
    dallinger setup
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
    sudo apt-get install tox -y


  SHELL
end
