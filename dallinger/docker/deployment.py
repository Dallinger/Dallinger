from dallinger.deployment import DebugDeployment, setup_experiment


class DockerDebugDeployment(DebugDeployment):
    """Run the experiment in a local docker compose based environment."""

    DEPLOY_NAME = "Docker"
    WRAPPER_CLASS = None
    DO_INIT_DB = False  # The DockerComposeWrapper will take care of it

    def __init__(self, *args, **kwargs):
        from .tools import DockerComposeWrapper

        super(DockerDebugDeployment, self).__init__(*args, **kwargs)
        self.WRAPPER_CLASS = DockerComposeWrapper

    def setup(self):
        """Override setup to be able to build the experiment directory
        without a working postgresql (it will work inside the docker compose env).
        Maybe the postgres check can be removed altogether?
        """
        self.exp_id, self.tmp_dir = setup_experiment(
            self.out.log,
            exp_config=self.exp_config,
            local_checks=False,
        )
