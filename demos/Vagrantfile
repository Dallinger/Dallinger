# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|

  class Name
      def to_s
          print "Dallinger needs a name and email for making git commits and running experiments\n"
          print "Full Name: "
          STDIN.gets.chomp
      end
  end

  class Email
      def to_s
          print "Email: "
          STDIN.gets.chomp
      end
  end

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

  config_env = {}
  ['~/.dallingerconfig', '~/.gitconfig'].each do |f|
    full_f = File.expand_path(f)
    if File.exist?(full_f) then
      config.vm.provision "file", source: full_f, destination: f

      config_env[File.basename(f).sub(/^./,'')] = 'TRUE'
    end
  end

  # Only ask for name and email if we didn't find a .gitconfig
  if !config_env.has_key?('gitconfig') then
    config_env["NAME"] = Name.new
    config_env["EMAIL"] = Email.new
  end

  config.vm.provision "shell", env: config_env, privileged: false, inline: <<-SHELL
    if [ $dallingerconfig ]; then
      echo 'Copied ~/.dallingerconfig from host machine'
    fi
    if [ $gitconfig ]; then
      echo 'Copied ~/.gitconfig from host machine'
    fi
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
    sudo service postgresql reload

    # Redis server
    sudo -E apt-get install redis-server -y

    # Virtual environment
    if [ ! $(grep -q 'heroku login' ~/.bashrc) ]; then
      echo 'source ~/venv/bin/activate' >> ~/.bashrc
      echo 'cd /vagrant' >> ~/.bashrc
      echo "export HOST=$(ifconfig enp0s8 | grep 'inet\s' | head -n1 | awk '{print $2;}')" >> ~/.bashrc
      echo 'if [ ! -f ~/.cache/heroku/lastrun ]; then heroku login -i; fi' >> ~/.bashrc
    fi
    virtualenv --python $(which python3) --no-site-packages ~/venv
    source ~/venv/bin/activate
    cd /vagrant

    # Dallinger install
    if [ ! -f ~/.dallingerconfig ]; then
      echo '[vm]' > ~/.dallingerconfig
      echo 'base_port = 5000' >> ~/.dallingerconfig
      echo "dallinger_email_address = $EMAIL" >> ~/.dallingerconfig
      echo "contact_email_on_error = $EMAIL" >> ~/.dallingerconfig
    fi
    if [ ! $(grep -q "^base_port" ~/.dallingerconfig) ]; then
      echo 'base_port = 5000' >> ~/.dallingerconfig
    fi
    pip install -U dallinger[data]

    # Git configuration
    if [ ! -f ~/.gitconfig ]; then
      echo '[user]' > ~/.gitconfig
      echo "name = $NAME" >> ~/.gitconfig
      echo "email = $EMAIL" >> ~/.gitconfig
    fi

    # Try to install the current package and deps
    if [ -f dev-requirements.txt ]; then
      pip install -U -r dev-requirements.txt || echo "Failed to install dev-requirements.txt"
    elif [ -f requirements.txt ]; then
      pip install -U -r requirements.txt || echo "Failed to install requirements.txt"
    fi

    if [ -f setup.py ]; then
      pip install -e . || echo "Failed to install experiment"
    fi

    # Heroku CLI installation
    sudo -E apt-get install software-properties-common
    sudo add-apt-repository "deb https://cli-assets.heroku.com/branches/stable/apt ./"
    curl -L https://cli-assets.heroku.com/apt/release.key | sudo apt-key add -
    sudo -E apt-get update
    sudo -E apt-get install heroku

    if [ ! -n $dallingerconfig ]; then
      echo "Don't forget to customize your ~/.dallingerconfig to include AWS keys, etc."
    fi

  SHELL
end
