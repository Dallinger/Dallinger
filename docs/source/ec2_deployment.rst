Using EC2 for Docker Based Deployments
======================================

The ``dallinger`` commandline tool has some helpers for managing EC2 instances
to help facilitate using docker to deploy experiments on those instances (see
:doc:`docker_support`).


Initial Setup
-------------

Route53 DNS
~~~~~~~~~~~


If your lab is doing this for the first time, you probably need to acquire a
domain name for your experiment server. This is the parent URL that will be used
to host your experiments. If your lab already has a domain name, you can skip
this step. On the AWS online console, navigate to the Route 53 service. On the
Dashboard you can register a domain name. Note that different domain names come
with different costs, and that registering a domain name can take from a few
minutes to several hours. Before proceeding with the next steps, please wait
until the AWS console tells you that the registration is complete.

The examples below assume that you have setup a domain ``my-experiments.org`` in
Route53.

EC2 Security Group
~~~~~~~~~~~~~~~~~~

By default the ``dallinger ec2`` commands will provision instances with the
security group ``dallinger``. If that group does not exist, one will be created
with appropriate ingress rules. You can use an existing security group by
specifying the ``--security_group_name`` option on the commandline, or by
setting the ``ec2_default_security_group`` value in your `~/.dallingerconfig`
file.

EC2 SSH Key Pair (PEM File)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default the ``dallinger ec2`` commands will use an SSH key pair named
``dallinger`` to create instances. If that key pair does not exist, one will be
created and added to your SSH keychain. You can use an existing SSH key pair by
specifying the ``--pem`` option on the commandline, or by setting the
``ec2_default_pem`` value in your `~/.dallingerconfig` file.
For more information about creating PEM files in AWS, see
https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/create-key-pairs.html.

AWS Region
----------

Except where noted, when ``--region`` is not specified then the
config value set in ``aws_region`` in e.g. ``~/.dallingerconfig`` will be used.


Provisioning an EC2 server instance
-----------------------------------

**Note**: If you decide to deploy to an EC2 instance, you need to "hire" the server
(Provisioning). Once you do that -- the clock is ticking and you will be charged
hourly until you release it (Teardown).

To provision an on-demand EC2 instance::

    dallinger ec2 provision --name <server_name> --region <region> --dns-host <subdomain>.my-experiments.org --type <type> --pem <pem> --security_group_name <security_group>

Pick an instance name which is easy to recognize, for example
‘tapping_deployment_batch_2’ is good but ‘melody123’ would be bad::

    dallinger ec2 provision --name tapping_deployment_batch_2 --region <region> --dns-host <subdomain>.my-experiments.org --type <type>

For example, if you want to collect data in Paris your command will include the
region name for Paris, like this::

    dallinger ec2 provision --name tapping_deployment_batch_2 --region eu-west-3 --dns-host <subdomain>.my-experiments.org --type <type>

Subdomain name should target your identity so it could be your own name. For
example::

    dallinger ec2 provision --name tapping_deployment_batch_2 --region eu-west-3 --dns-host elif.my-experiments.org --type <type>

You should use a different instance type according to your need. m7i.large is
recommended for debugging and m7i.xlarge is for deploying. For example::

    dallinger ec2 provision --name tapping_deployment_batch_2 --region eu-west-3 --dns-host elif.my-experiments.org -

You can configure different amounts of storage or different instance types::

    dallinger ec2 provision --name <server_name> --region <region> --storage 100 --type m5.2xlarge


Increasing Storage on An Instance
---------------------------------

You can increase the storage on a running instance by server name::

    dallinger ec2 increase-storage --name <server_name> --region <region> --storage 200

Or by DNS name::

    dallinger ec2 increase-storage --dns <subdomain>.my-experiments.org --region <region> --storage 200


Stopping and Starting
---------------------

You can temporarily stop a running instance to prevent it from incurring hourly
costs (while retaining its stored data)::

    dallinger ec2 stop --name <server_name> --region <region>
    dallinger ec2 stop --dns <subdomain>.my-experiments.org --region <region>

Similarly you can start a stopped instance::

    dallinger ec2 start --name <server_name> --region <region>
    dallinger ec2 start --dns <subdomain>.my-experiments.org --region <region>

Or restart a running instance::

    dallinger ec2 restart --name <server_name> --region <region>
    dallinger ec2 restart --dns <subdomain>.my-experiments.org --region <region>


Teardown an EC2 Instance
------------------------

**Important**: don't forget to export your data before you tear down the server.
If you don't all data is lost and there is NO way to retrieve them. Before you
teardown the instance make sure:

    * The experiment is stopped on the recruiter, e.g. in Prolific the experiment should be STOPPED and thus not active
    * Make sure you exported your data and run export.py to make sure your data is not faulty

To teardown an on-demand EC2 instance ny server name::

    dallinger ec2 teardown --name <server_name> --region <region>

Or by DNS name::

    dallinger ec2 teardown --dns <subdomain>.my-experiments.org --region <region>


Listing Available Regions and Instance Types
--------------------------------------------

You can list the available EC2 regions using::

    dallinger ec2 list regions

Different instance types may be available in different regions, you can list the
available instance types for a region using::

    dallinger ec2 list instance_types --region <region>


Listing Existing Instances
--------------------------

Dallinger provides some tools for introspecting your current EC2 resources. You can list all instances::

    dallinger ec2 list instances --region <region>

Or filter based on instance state::

    dallinger ec2 list instances --region <region> --running
    dallinger ec2 list instances --region <region> --stopped --terminated

Additionally you can filter based on instance PEM key name::

    dallinger ec2 list instances --region <region> --running --pem my-pem

**Note**: If ``--region`` is not explicitly specified instances in all regions will be listed.


Connecting to a Container Running an Experiment
-----------------------------------------------

You can make an SSH connection to the docker container running the a specific
experiment using the server DNS name and the experiment app name with the
following command::

    dallinger ssh web --dns <subdomain>.my-experiments.org --app <subdomain>.my-experiments.org
