1. Install Wallace and its dependencies using pip (`pip install wallace`).
2. Install the [Heroku toolbelt](https://toolbelt.heroku.com/).
3. Sign up for accounts with the following services, which will make it possible for you to deploy Wallace experiments on the web: [psiTurk](https://psiturk.org/register), [Amazon Web Services](http://aws.amazon.com/), [Amazon Mechanical Turk](https://requester.mturk.com/) and [Heroku](https://www.heroku.com/).
4. Place your psiTurk and Amazon Web Services credentials in `~/.psiturkconfig`. 
5. Create a new Wallace experiment. Look through the existing experiments in the `/examples` folder, select one, and then create it, e.g. `wallace create --experiment bartlett1932`.
6. `cd` into the newly-created experiment directory.
7. Deploy your app for debugging `wallace debug`.


