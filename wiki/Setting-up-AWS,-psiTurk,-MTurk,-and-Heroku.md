Before you can use Wallace you will need accounts with the following services, which will make it possible for you to deploy Wallace experiments on the web: [psiTurk](https://psiturk.org/register), [Amazon Web Services](http://aws.amazon.com/), [Amazon Mechanical Turk](https://requester.mturk.com/), & [Heroku](https://signup.heroku.com/identity).

In addition to signing up for the relevant accounts you will need to set up your environment such that Wallace is able to access your accounts. 

This involves first creating an API Key access file so that it can connect to your psiTurk and Amazon Web Services accounts. Wallace interfaces with Amazon Mechanical Turk via your Amazon Web Services Account. 

You then will need to set up your command line installation of the Heroku toolset to be able to log in to your Heroku account. 

# Creating your API Key access file

## psiTurk 

When you create your psiTurk account this will require a valid email address, and once you confirm your account you can then click on [**API Keys**](https://psiturk.org/dashboard/api_credentials) which will allow you to access your API keys as seen in the image below:

![Don't even try to use these API Keys, they've been reissued!](http://note.io/145nfz4)

## AWS API Keys
One feature of the AWS API keys is that they are only displayed once, and while they can be regenerated that will render invalid previously generated keys. If you are running experiments using a laboratory account (or any other kind of group-owned account) if you regenerate keys that will stop other users who have previously generated keys from being able to use the AWS account. Unless you are sure that you will not be interrupting others' workflows, it is advised that you do **not** generate new API keys. 

A corollary is that when you create your AWS account be sure to record your values for the following keys:

    aws_access_key_id = 
    aws_secret_access_key = 

If you are not the primary user of the account, see if you can obtain these keys from others who have successfully been able to use AWS.

## Making the `.wallaceconfig` file

Place your psiTurk and Amazon Web Services credentials in `~/.wallaceconfig` (you may need to create this file:  `touch ~/.wallaceconfig`); it should live in your home directory). 

In your preferred text editor, edit the file to include the following text(filling in the ALL_CAPS with your relevant values):

    $ cat ~/.wallaceconfig
    [AWS Access]
    aws_access_key_id = YOUR_AWS_ACCESS_KEY_ID
    aws_secret_access_key = YOUR_AWS_SECRET_ACCESS_KEY

    [psiTurk Access]
    psiturk_access_key_id = YOUR_PSITURK_ACCESS_KEY_ID
    psiturk_secret_access_id = YOUR_PSITURK_SECRET_ACCESS_ID

## Heroku

Sign up for [Heroku](https://www.heroku.com/), and install the [Heroku toolbelt](https://toolbelt.heroku.com/). 

You should be able to see an interface that looks like the following

![This is the interface with the Heroku app](http://note.io/11c7tkL)

Then, log in from the command line:


    heroku login


You won't need to interact with Heroku directly from here on out --- the Wallace command line tool handles that for you.

## Ready to Wallace your first experiment‽

Now you're all set up with the tools you need to work with Wallace. 

Now it's time to test Wallace to make sure it's working on your system. [click here to see the next steps and demos](https://github.com/berkeley-cocosci/Wallace/wiki#testing-wallace).
