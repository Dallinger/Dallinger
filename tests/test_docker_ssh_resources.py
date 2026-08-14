import importlib
import warnings

docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")


def test_docker_ssh_resource_warnings_are_muted():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("default")
        docker_ssh._ignore_docker_ssh_resource_warnings()
        warnings.warn("subprocess 123 is still running", ResourceWarning)
        warnings.warn(
            "unclosed <docker.transport.sshconn.SSHSocket fd=5>", ResourceWarning
        )
        warnings.warn(
            "unclosed file <_io.FileIO name=10 mode='wb' closefd=True>",
            ResourceWarning,
        )
        warnings.warn(
            "unclosed file <_io.FileIO name=11 mode='rb' closefd=True>",
            ResourceWarning,
        )
        # Unrelated leaks, including plain sockets and named files, must not be muted.
        warnings.warn("unclosed <socket.socket fd=6>", ResourceWarning)
        warnings.warn(
            "unclosed file <_io.TextIOWrapper name='foo.txt' mode='w'>",
            ResourceWarning,
        )
        warnings.warn("some unrelated warning", ResourceWarning)

    assert [str(w.message) for w in caught] == [
        "unclosed <socket.socket fd=6>",
        "unclosed file <_io.TextIOWrapper name='foo.txt' mode='w'>",
        "some unrelated warning",
    ]


def test_docker_ssh_resource_warnings_stay_muted_after_warning_hooks():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("default")
        docker_ssh._ignore_docker_ssh_resource_warnings()
        # setup_warning_hooks() re-enables all Warning subclasses.
        warnings.simplefilter("default", Warning)
        docker_ssh._ignore_docker_ssh_resource_warnings()
        warnings.warn("subprocess 123 is still running", ResourceWarning)
        warnings.warn(
            "unclosed <docker.transport.sshconn.SSHSocket fd=5>", ResourceWarning
        )
        warnings.warn(
            "unclosed file <_io.FileIO name=10 mode='wb' closefd=True>",
            ResourceWarning,
        )
        warnings.warn("unclosed <socket.socket fd=6>", ResourceWarning)

    assert [str(w.message) for w in caught] == [
        "unclosed <socket.socket fd=6>",
    ]
