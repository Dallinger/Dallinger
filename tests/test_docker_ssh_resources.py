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
        # Unrelated leaks, including plain sockets, must not be muted.
        warnings.warn("unclosed <socket.socket fd=6>", ResourceWarning)
        warnings.warn("some unrelated warning", ResourceWarning)

    assert [str(w.message) for w in caught] == [
        "unclosed <socket.socket fd=6>",
        "some unrelated warning",
    ]
