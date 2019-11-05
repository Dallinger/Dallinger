# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "slavrd/xenial64-python3"

  config.vm.provider "virtualbox" do |vb|
      vb.customize ["modifyvm", :id, "--natdnsproxy1", "on"]
      vb.customize ["modifyvm", :id, "--natdnshostresolver1", "on"]
      vb.cpus = 2
      vb.memory = 4096
  end

#  config.vm.network "public_network",
#    use_dhcp_assigned_default_route: true

  config.vm.provision "shell", privileged: false, inline: <<-SHELL
    sudo apt-get update

    export DEBIAN_FRONTEND=noninteractive

    # Python dependencies
    sudo apt-get install -y build-essential
    sudo apt install software-properties-common
    sudo apt install -y python3-pip
    sudo apt-get -y install python-setuptools
  
    # Make aliases
    alias pip=pip3.7
    alias python=python3.7

    # Postgres setup
    sudo apt-get install -y postgresql-9.5 postgresql-server-dev-9.5
    sudo su - postgres -c createuser vagrant;createdb dallinger
    # trust all connections
    sudo sed /etc/postgresql/9.5/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sudo service postgresql reload

    # Virtual environment
    echo 'source ~/venv/bin/activate' >> ~/.bashrc
    echo 'cd /vagrant' >> ~/.bashrc
    echo 'export HOST=`ifconfig | grep Ethernet -A1 | grep addr: | tail -n1 | cut -d: -f2 | cut -d " " -f1`' >> ~/.bashrc
    pip install virtualenv
    virtualenv -p /usr/local/bin/python3.7 ~/venv
    source ~/venv/bin/activate
    cd /vagrant

    # Documentation building dependencies
    sudo apt-get install -y enchant pandoc zip
    pip install pyenchant
    pip install -r dev-requirements.txt

    # Dallinger install
    #TODO fix this error below which generates:
    #Traceback (most recent call last):
    #File "/home/vagrant/venv/local/lib/python3.7/site-packages/setuptools/command/easy_install.py", line 469, in check_site_dir
    #open(testfile, 'w').close()
    #OSError: [Errno 71] Protocol error: './.eggs/test-easy-install-475.write-test'

    sudo python setup.py develop
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
