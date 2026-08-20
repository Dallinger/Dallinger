import configparser
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid
import warnings
from pathlib import Path
from unittest import mock

import pexpect
import pytest
import requests
from pytest import raises

from dallinger import recruiters
from dallinger.config import get_config
from tests.helpers import write_deployment_policy


def found_in(name, path):
    return os.path.exists(os.path.join(path, name))


@pytest.fixture
def output():
    from dallinger.command_line import Output

    return Output(log=mock.Mock(), error=mock.Mock(), blather=mock.Mock())


@pytest.fixture
def browser():
    with mock.patch("dallinger.deployment.open_browser") as open_browser:
        yield open_browser


@pytest.fixture
def faster(tempdir, active_config):
    with mock.patch.multiple(
        "dallinger.deployment", time=mock.DEFAULT, setup_experiment=mock.DEFAULT
    ) as mocks:
        mocks["setup_experiment"].return_value = ("fake-uid", tempdir)
        # setup_experiment normally sets the dashboard credentials if unset
        active_config.extend(
            {
                "dashboard_user": "admin",
                "dashboard_password": "DUMBPASSWORD",
            }
        )
        yield mocks


@pytest.fixture
def launch():
    with mock.patch("dallinger.deployment.handle_launch_data") as hld:
        hld.return_value = {"recruitment_msg": "fake\nrecruitment\nlist"}
        yield hld


@pytest.fixture
def fake_git():
    with mock.patch("dallinger.deployment.GitClient") as git:
        yield git


@pytest.fixture
def fake_redis():
    mock_connection = mock.Mock(name="fake redis connection")
    with mock.patch("dallinger.deployment.connect_to_redis") as connect:
        connect.return_value = mock_connection
        yield mock_connection


@pytest.fixture
def herokuapp():
    # Patch addon since we're using a free app which doesn't support them:
    from dallinger.heroku.tools import HerokuApp

    instance = HerokuApp("fake-uid", output=None, team=None)
    instance.addon = mock.Mock()
    with mock.patch("dallinger.deployment.HerokuApp") as mock_app_class:
        mock_app_class.return_value = instance
        yield instance
        instance.destroy()


@pytest.fixture
def heroku_mock():
    # Patch addon since we're using a free app which doesn't support them:
    from dallinger.heroku.tools import HerokuApp

    instance = mock.Mock(spec=HerokuApp)
    instance.redis_url = "\n"
    instance.name = "dlgr-fake-uid"
    instance.url = "fake-web-url"
    instance.db_url = "fake-db-url"
    instance.addon_parameters.return_value = {}
    with mock.patch("dallinger.deployment.heroku") as heroku_module:
        heroku_module.auth_token.return_value = "fake token"
        with mock.patch("dallinger.deployment.HerokuApp") as mock_app_class:
            mock_app_class.return_value = instance
            yield instance


@pytest.mark.usefixtures("in_tempdir")
class TestExperimentFilesSource:
    @pytest.fixture
    def git(self):
        from dallinger.utils import GitClient

        return GitClient()

    @pytest.fixture
    def subject(self):
        from dallinger.utils import ExperimentFileSource

        return ExperimentFileSource

    def test_lists_files_valid_for_copying_as_absolute_paths(self, subject):
        legit_file = "./some/subdir/John Doe's file.txt"
        os.makedirs(os.path.dirname(legit_file))
        with open(legit_file, "w") as f:
            f.write("12345")

        source = subject()

        assert os.path.abspath(legit_file) in source.files

    def test_excludes_files_that_should_not_be_copied(self, subject):
        with open("illegit.db", "w") as f:
            f.write("12345")

        source = subject()

        assert len(source.files) == 0

    def test_excludes_otherwise_valid_files_if_in_gitignore_simple(self, subject, git):
        legit_file = "./some/subdir/legit.txt"
        os.makedirs(os.path.dirname(legit_file))
        with open(legit_file, "w") as f:
            f.write("12345")
        with open(".gitignore", "w") as f:
            f.write("*.txt")
        git.init()

        source = subject()

        assert source.files == {os.path.abspath(".gitignore")}

    def test_excludes_otherwise_valid_files_if_in_gitignore_complex(self, subject, git):
        legit_file = "./some/subdir/legit.txt"
        os.makedirs(os.path.dirname(legit_file))
        with open(legit_file, "w") as f:
            f.write("12345")
        with open(".gitignore", "w") as f:
            f.write("**/subdir/*")
        git.init()

        source = subject()

        assert source.files == {os.path.abspath(".gitignore")}

    def test_normalizes_unicode_for_merging_git_inclusions(self, subject, git):
        legit_file = "".join(
            [".", "/", "a", "̊", " ", "f", "i", "l", "e", ".", "t", "x", "t"]
        )
        with open(legit_file, "w") as f:
            f.write("12345")
        git.init()

        source = subject()

        assert source.files == {os.path.abspath(legit_file)}

    def test_size_includes_files_that_would_be_copied(self, subject):
        with open("legit.txt", "w") as f:
            f.write("12345")

        source = subject()

        assert source.size == 5

    def test_size_excludes_files_that_would_not_be_copied(self, subject):
        with open("illegit.db", "w") as f:
            f.write("12345")

        source = subject()

        assert source.size == 0

    def test_size_excludes_directories_that_would_not_be_copied(self, subject):
        os.mkdir("snapshots")
        with open("snapshots/legit.txt", "w") as f:
            f.write("12345")

        source = subject()

        assert source.size == 0

    def test_size_excludes_bad_files_when_in_subdirectories(self, subject):
        os.mkdir("legit_dir")
        with open("legit_dir/illegit.db", "w") as f:
            f.write("12345")

        source = subject()

        assert source.size == 0

    def test_recipe_for_copy_defaults_to_cwd(self, subject):
        legit_file = "./some/subdir/John Doe's file.txt"
        os.makedirs(os.path.dirname(legit_file))
        with open(legit_file, "w") as f:
            f.write("12345")
        destination = tempfile.mkdtemp()
        source = subject()

        source.apply_to(destination)

        assert (Path(destination) / "some/subdir/John Doe's file.txt").is_file()

    def test_recipe_for_copy_accepts_explicit_root(self, subject):
        legit_file = "./some/subdir/legit.txt"
        os.makedirs(os.path.dirname(legit_file))
        with open(legit_file, "w") as f:
            f.write("12345")
        destination = tempfile.mkdtemp()
        source = subject(os.getcwd())

        source.apply_to(destination)

        assert (Path(destination) / legit_file).is_file()

    def test_recipe_for_copy_resolves_nonascii_filenames_with_git(self, subject):
        legit_file = "".join(["a", "̊", " ", "f", "i", "l", "e"])
        with open(legit_file, "w") as f:
            f.write("12345")
        destination = tempfile.mkdtemp()
        source = subject()

        source.apply_to(destination)

        assert (Path(destination) / legit_file).is_file()

    def test_recipe_for_copy_resolves_nonascii_filenames_with_git2(self, subject):
        legit_file = "".join(["å", " ", "f", "i", "l", "e"])
        with open(legit_file, "w") as f:
            f.write("12345")
        destination = tempfile.mkdtemp()
        source = subject()

        source.apply_to(destination)

        assert (Path(destination) / legit_file).is_file()

    def test_apply_to_resolves_nonascii_filenames_with_git2(self, subject):
        legit_file = "".join(["å", " ", "f", "i", "l", "e"])
        with open(legit_file, "w") as f:
            f.write("12345")
        destination = tempfile.mkdtemp()
        source = subject()

        source.apply_to(destination)

        assert (Path(destination) / legit_file).is_file()

    def test_policy_selects_plan_files_for_an_arbitrary_root(
        self, subject, tmp_path, monkeypatch
    ):
        root = tmp_path / "experiment"
        root.mkdir()
        (root / ".gitignore").write_text("ignored.txt\n")
        (root / "ignored.txt").write_text("included by policy")
        (root / "excluded.txt").write_text("excluded by policy")
        (root / "config.txt").write_text("raw configuration")
        write_deployment_policy(root, exclude=["excluded.txt"])
        monkeypatch.chdir(tmp_path)

        source = subject(root)
        destination = tmp_path / "destination"
        locations = list(source.map_locations_to(destination))

        assert locations == [
            (
                str(root / ".gitignore"),
                str(destination / ".gitignore"),
            ),
            (
                str(root / "deploy.toml"),
                str(destination / "deploy.toml"),
            ),
            (
                str(root / "ignored.txt"),
                str(destination / "ignored.txt"),
            ),
        ]
        assert source.deployment_plan is not None

    def test_policy_plan_is_built_once_and_supplies_size_without_restatting(
        self, subject, tmp_path, monkeypatch
    ):
        from dallinger.deployment_plan import build_deployment_plan

        root = tmp_path / "experiment"
        root.mkdir()
        (root / "asset.txt").write_text("asset")
        write_deployment_policy(root)
        expected_size = build_deployment_plan(root).total_size

        with mock.patch(
            "dallinger.utils.build_deployment_plan", wraps=build_deployment_plan
        ) as builder:
            source = subject(root)
            list(source.map_locations_to(tmp_path / "first"))
            list(source.map_locations_to(tmp_path / "second"))
            source.files
            with mock.patch(
                "dallinger.utils.os.path.getsize",
                side_effect=AssertionError("policy size must not restat files"),
            ):
                assert source.size == expected_size

        assert builder.call_count == 1

    @pytest.mark.parametrize(
        "copy_mode, output_is_symlink",
        [
            ("copy", False),
            ("symlink", True),
        ],
    )
    def test_policy_drives_copied_and_symlink_collation(
        self, tmp_path, copy_mode, output_is_symlink
    ):
        from dallinger.utils import (
            DallingerFileSource,
            ExplicitFileSource,
            collate_experiment_files,
            copy_file,
            symlink_file,
        )

        copy_func = copy_file if copy_mode == "copy" else symlink_file
        root = tmp_path / "experiment"
        root.mkdir()
        (root / ".gitignore").write_text("ignored.txt\n")
        (root / "ignored.txt").write_text("selected")
        (root / "local.txt").write_text("not selected")
        write_deployment_policy(root, exclude=["local.txt"])
        destination = tmp_path / "destination"

        with (
            mock.patch.object(ExplicitFileSource, "apply_to"),
            mock.patch.object(DallingerFileSource, "apply_to"),
            mock.patch.object(ExplicitFileSource, "map_locations_to", return_value=[]),
            mock.patch.object(DallingerFileSource, "map_locations_to", return_value=[]),
            mock.patch("dallinger.config.initialize_experiment_package"),
        ):
            collate_experiment_files(
                {},
                experiment_path=root,
                destination=destination,
                copy_func=copy_func,
            )

        assert (destination / "ignored.txt").read_text() == "selected"
        assert (destination / "ignored.txt").is_symlink() is output_is_symlink
        assert (destination / "deploy.toml").exists()
        assert not (destination / "local.txt").exists()

    def test_policy_development_bulk_link_uses_constant_materialization_operations(
        self, subject, tmp_path
    ):
        import dallinger.utils as utils

        root = tmp_path / "experiment"
        root.mkdir()
        static = root / "static"
        static.mkdir()
        for number in range(500):
            (static / f"asset-{number:04}.txt").write_text("x")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write_deployment_policy(root)
        source = subject(root)
        destination = tmp_path / "destination"

        with mock.patch(
            "dallinger.utils.symlink_file", wraps=utils.symlink_file
        ) as link:
            source.apply_development_to(destination)

        assert (destination / "static").is_symlink()
        assert link.call_count == 2  # one directory and deploy.toml
        assert not any(
            Path(call.args[1]).parent == destination / "static"
            for call in link.call_args_list
        )
        visible = set()
        for directory, _, filenames in os.walk(destination, followlinks=True):
            for filename in filenames:
                visible.add(
                    (Path(directory) / filename).relative_to(destination).as_posix()
                )
        assert visible == source.deployment_plan.destinations

    def test_excluded_descendant_prevents_parent_link_but_allows_safe_siblings(
        self, subject, tmp_path
    ):
        root = tmp_path / "experiment"
        root.mkdir()
        write_deployment_policy(root, exclude=["static/private"])
        (root / "static/private").mkdir(parents=True)
        (root / "static/private/secret.txt").write_text("secret")
        (root / "static/public").mkdir()
        (root / "static/public/asset.txt").write_text("public")
        (root / "static/other").mkdir()
        (root / "static/other/asset.txt").write_text("other")
        source = subject(root)
        destination = tmp_path / "destination"

        source.apply_development_to(destination)

        assert not (destination / "static").is_symlink()
        assert (destination / "static/public").is_symlink()
        assert (destination / "static/other").is_symlink()
        assert not (destination / "static/private").exists()

    def test_absent_exclusion_prevents_future_descendant_from_leaking_through_link(
        self, subject, tmp_path
    ):
        root = tmp_path / "experiment"
        root.mkdir()
        write_deployment_policy(root, exclude=["static/nested/private"])
        (root / "static/nested/public").mkdir(parents=True)
        (root / "static/nested/public/asset.txt").write_text("public")
        (root / "static/safe").mkdir()
        (root / "static/safe/asset.txt").write_text("safe")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        source = subject(root)
        destination = tmp_path / "destination"

        source.apply_development_to(destination)

        assert not (destination / "static").is_symlink()
        assert not (destination / "static/nested").is_symlink()
        assert (destination / "static/nested/public").is_symlink()
        assert (destination / "static/safe").is_symlink()

        private = root / "static/nested/private"
        private.mkdir()
        (private / "secret.txt").write_text("secret")

        assert not (destination / "static/nested/private").exists()

    @pytest.mark.parametrize("provider", ["explicit", "framework"])
    def test_later_provider_collision_forces_fallback_without_source_writes(
        self, tmp_path, provider
    ):
        from dallinger.utils import (
            DallingerFileSource,
            ExplicitFileSource,
            collate_experiment_files,
            symlink_file,
        )

        root = tmp_path / "experiment"
        root.mkdir()
        (root / "assets").mkdir()
        experiment_collision = root / "assets/collision.txt"
        experiment_collision.write_text("experiment")
        (root / "assets/experiment-only.txt").write_text("experiment-only")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write_deployment_policy(root)
        provider_collision = tmp_path / f"{provider}-collision.txt"
        provider_collision.write_text("provider")
        provider_addition = tmp_path / f"{provider}-addition.txt"
        provider_addition.write_text("addition")
        destination = tmp_path / "destination"
        mappings = [
            (str(provider_collision), str(destination / "assets/collision.txt")),
            (str(provider_addition), str(destination / "assets/provider.txt")),
        ]
        explicit_mappings = mappings if provider == "explicit" else []
        framework_mappings = mappings if provider == "framework" else []

        with (
            mock.patch("dallinger.config.initialize_experiment_package"),
            mock.patch.object(
                ExplicitFileSource,
                "map_locations_to",
                return_value=explicit_mappings,
            ) as explicit_map,
            mock.patch.object(
                DallingerFileSource,
                "map_locations_to",
                return_value=framework_mappings,
            ) as framework_map,
        ):
            collate_experiment_files(
                {},
                experiment_path=root,
                destination=destination,
                copy_func=symlink_file,
            )

        assert explicit_map.call_count == 1
        assert framework_map.call_count == 1
        assert not (destination / "assets").is_symlink()
        assert (destination / "assets/collision.txt").read_text() == "experiment"
        assert (destination / "assets/collision.txt").is_symlink()
        assert (destination / "assets/provider.txt").read_text() == "addition"
        assert (destination / "assets/provider.txt").is_symlink()
        assert not (root / "assets/provider.txt").exists()
        assert experiment_collision.read_text() == "experiment"
        assert provider_collision.read_text() == "provider"

    def test_framework_collision_does_not_block_unrelated_bulk_link_sibling(
        self, tmp_path
    ):
        from dallinger.utils import (
            DallingerFileSource,
            ExplicitFileSource,
            collate_experiment_files,
            symlink_file,
        )

        root = tmp_path / "experiment"
        root.mkdir()
        stimuli = root / "static/stimuli"
        stimuli.mkdir(parents=True)
        for number in range(250):
            (stimuli / f"stimulus-{number:04}.txt").write_text("stimulus")
        css = root / "static/css"
        css.mkdir()
        experiment_collision = css / "file.css"
        experiment_collision.write_text("experiment")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write_deployment_policy(root)
        framework_source = tmp_path / "framework.css"
        framework_source.write_text("framework")
        destination = tmp_path / "destination"

        with (
            mock.patch("dallinger.config.initialize_experiment_package"),
            mock.patch.object(ExplicitFileSource, "map_locations_to", return_value=[]),
            mock.patch.object(
                DallingerFileSource,
                "map_locations_to",
                return_value=[
                    (
                        str(framework_source),
                        str(destination / "static/css/file.css"),
                    )
                ],
            ) as framework_map,
        ):
            collate_experiment_files(
                {},
                experiment_path=root,
                destination=destination,
                copy_func=symlink_file,
            )

        assert framework_map.call_count == 1
        assert (destination / "static/stimuli").is_symlink()
        assert not (destination / "static/css").is_symlink()
        assert (destination / "static/css/file.css").is_symlink()
        assert (destination / "static/css/file.css").read_text() == "experiment"
        assert experiment_collision.read_text() == "experiment"
        assert framework_source.read_text() == "framework"

    def test_later_provider_destination_ancestor_protects_nested_plan_entries(
        self, tmp_path
    ):
        from dallinger.utils import (
            DallingerFileSource,
            ExplicitFileSource,
            collate_experiment_files,
            symlink_file,
        )

        root = tmp_path / "experiment"
        root.mkdir()
        (root / "assets/nested").mkdir(parents=True)
        (root / "assets/nested/asset.txt").write_text("experiment")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write_deployment_policy(root)
        provider_source = tmp_path / "provider-assets"
        provider_source.write_text("provider")
        destination = tmp_path / "destination"

        with (
            mock.patch("dallinger.config.initialize_experiment_package"),
            mock.patch.object(
                ExplicitFileSource,
                "map_locations_to",
                return_value=[(str(provider_source), str(destination / "assets"))],
            ),
            mock.patch.object(DallingerFileSource, "map_locations_to", return_value=[]),
        ):
            collate_experiment_files(
                {},
                experiment_path=root,
                destination=destination,
                copy_func=symlink_file,
            )

        assert not (destination / "assets").is_symlink()
        assert not (destination / "assets/nested").is_symlink()
        assert (destination / "assets/nested/asset.txt").is_symlink()
        assert (destination / "assets/nested/asset.txt").read_text() == "experiment"

    @pytest.mark.parametrize("replacement", ["directory", "symlink"])
    def test_policy_bulk_link_follows_current_source_path(
        self, subject, tmp_path, replacement
    ):
        """Development links the planned path as-is; mid-flight replacement is trusted."""
        root = tmp_path / "experiment"
        root.mkdir()
        assets = root / "assets"
        assets.mkdir()
        (assets / "asset.txt").write_text("planned")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write_deployment_policy(root)
        source = subject(root)
        original = root / "original-assets"
        assets.rename(original)
        if replacement == "directory":
            assets.mkdir()
            (assets / "asset.txt").write_text("replacement")
        else:
            outside = tmp_path / "outside"
            outside.mkdir()
            (outside / "asset.txt").write_text("outside")
            assets.symlink_to(outside, target_is_directory=True)

        destination = tmp_path / "destination"
        source.apply_development_to(destination)

        assert (destination / "assets").is_symlink()
        assert (destination / "assets").resolve() == assets.resolve()
        assert (destination / "assets/asset.txt").read_text() == (
            "replacement" if replacement == "directory" else "outside"
        )

    def test_expunge_unlinks_bulk_directory_link_without_touching_source(
        self, subject, tmp_path
    ):
        from dallinger.utils import expunge_directory

        root = tmp_path / "experiment"
        root.mkdir()
        (root / "assets").mkdir()
        (root / "assets/asset.txt").write_text("source")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write_deployment_policy(root)
        destination = tmp_path / "destination"
        source = subject(root)
        source.apply_development_to(destination)
        assert (destination / "assets").is_symlink()

        expunge_directory(destination)

        assert list(destination.iterdir()) == []
        assert (root / "assets/asset.txt").read_text() == "source"

    def test_plan_copy_keeps_candidate_directory_as_regular_files(
        self, subject, tmp_path
    ):
        root = tmp_path / "experiment"
        root.mkdir()
        (root / "assets/nested").mkdir(parents=True)
        (root / "assets/nested/asset.txt").write_text("frozen")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write_deployment_policy(root)
        destination = tmp_path / "destination"

        subject(root).apply_to(destination)

        assert not (destination / "assets").is_symlink()
        assert not (destination / "assets/nested").is_symlink()
        assert not (destination / "assets/nested/asset.txt").is_symlink()
        assert (destination / "assets/nested/asset.txt").read_text() == "frozen"

    def test_no_policy_symlink_collation_prevalidates_provider_mappings(
        self, subject, tmp_path
    ):
        from dallinger.utils import (
            DallingerFileSource,
            ExplicitFileSource,
            collate_experiment_files,
            symlink_file,
        )

        root = tmp_path / "experiment"
        root.mkdir()
        (root / "asset.txt").write_text("legacy")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        source = subject(root)
        destination = tmp_path / "destination"

        with (
            mock.patch.object(ExplicitFileSource, "apply_to") as explicit_apply,
            mock.patch.object(DallingerFileSource, "apply_to") as framework_apply,
            mock.patch.object(
                ExplicitFileSource,
                "map_locations_to",
                return_value=iter(()),
            ) as explicit_mappings,
            mock.patch.object(
                DallingerFileSource,
                "map_locations_to",
                return_value=iter(()),
            ),
        ):
            collate_experiment_files(
                {},
                experiment_path=root,
                destination=destination,
                copy_func=symlink_file,
                experiment_files=source,
            )

        explicit_mappings.assert_called_once_with(destination)
        explicit_apply.assert_not_called()
        framework_apply.assert_not_called()
        assert (destination / "asset.txt").is_symlink()

    def test_no_policy_auto_selection_matches_explicit_legacy_without_warnings(
        self, subject, tmp_path, monkeypatch
    ):
        root = tmp_path / "experiment"
        root.mkdir()
        (root / ".gitignore").write_text("ignored.txt\n")
        (root / "included.txt").write_text("included")
        (root / "ignored.txt").write_text("ignored")
        monkeypatch.chdir(root)
        subprocess.run(["git", "init", "-q"], check=True)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            automatic = list(
                subject(root).map_locations_to(tmp_path / "automatic-destination")
            )
            legacy = list(
                subject(root, selection="legacy").map_locations_to(
                    tmp_path / "legacy-destination"
                )
            )

        automatic_membership = [
            (source, os.path.relpath(destination, tmp_path / "automatic-destination"))
            for source, destination in automatic
        ]
        legacy_membership = [
            (source, os.path.relpath(destination, tmp_path / "legacy-destination"))
            for source, destination in legacy
        ]
        assert automatic_membership == legacy_membership
        assert str(root / "ignored.txt") not in {source for source, _ in automatic}

    def test_no_policy_retains_legacy_git_failure_fallback(
        self, subject, tmp_path, monkeypatch
    ):
        root = tmp_path / "experiment"
        root.mkdir()
        (root / ".gitignore").write_text("ignored.txt\n")
        (root / "ignored.txt").write_text("legacy fallback")
        monkeypatch.chdir(root)
        monkeypatch.setattr(
            "dallinger.utils.check_output",
            mock.Mock(side_effect=OSError("git unavailable")),
        )

        source = subject(root)

        assert str(root / "ignored.txt") in source.files

    def test_policy_omits_backend_ignore_controls_without_gating(
        self, subject, tmp_path
    ):
        root = tmp_path / "experiment"
        root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write_deployment_policy(root)
        (root / ".dockerignore").write_text("*")
        (root / "asset.txt").write_text("kept")

        source = subject(root)

        assert str(root / "asset.txt") in source.files
        assert str(root / ".dockerignore") not in source.files

    def test_plan_copy_rejects_external_symlink_replacement(self, subject, tmp_path):
        from dallinger.deployment_plan import DeploymentPlanError

        root = tmp_path / "experiment"
        root.mkdir()
        source_path = root / "asset.txt"
        source_path.write_text("planned")
        write_deployment_policy(root)
        source = subject(root)
        outside = tmp_path / "outside.txt"
        outside.write_text("external")
        source_path.unlink()
        source_path.symlink_to(outside)
        destination = tmp_path / "destination"

        with pytest.raises(DeploymentPlanError, match="not a regular file"):
            source.apply_to(destination)

        assert not (destination / "asset.txt").exists()

    def test_plan_copy_preserves_mode(self, subject, tmp_path):
        root = tmp_path / "experiment"
        root.mkdir()
        source_path = root / "run.sh"
        source_path.write_text("#!/bin/sh\n")
        source_path.chmod(0o751)
        write_deployment_policy(root)
        source = subject(root)
        destination = tmp_path / "destination"

        source.apply_to(destination)

        assert (destination / "run.sh").stat().st_mode & 0o777 == 0o751

    def test_plan_copy_allows_trusted_destination_symlink_ancestors(
        self, subject, tmp_path
    ):
        root = tmp_path / "experiment"
        root.mkdir()
        (root / "asset.txt").write_text("planned")
        write_deployment_policy(root)
        source = subject(root)
        canonical_parent = tmp_path / "private-var"
        canonical_parent.mkdir()
        alias = tmp_path / "var"
        alias.symlink_to(canonical_parent, target_is_directory=True)

        source.apply_to(alias / "staging")

        assert (canonical_parent / "staging" / "asset.txt").read_text() == "planned"

    def test_plan_copy_does_not_follow_or_replace_final_destination_symlink(
        self, subject, tmp_path
    ):
        from dallinger.deployment_plan import (
            DeploymentPlanError,
            materialize_deployment_plan_entry,
        )

        root = tmp_path / "experiment"
        root.mkdir()
        (root / "asset.txt").write_text("planned")
        write_deployment_policy(root)
        source = subject(root)
        plan = source.deployment_plan
        entry = next(item for item in plan.entries if item.destination == "asset.txt")
        destination = tmp_path / "destination"
        destination.mkdir()
        external = tmp_path / "external.txt"
        external.write_text("external")
        target = destination / "asset.txt"
        target.symlink_to(external)

        with pytest.raises(DeploymentPlanError, match="already exists"):
            materialize_deployment_plan_entry(plan, entry, target)

        assert target.is_symlink()
        assert target.read_text() == "external"
        assert external.read_text() == "external"

    def test_plan_rejects_custom_copy_functions(self, subject, tmp_path):
        root = tmp_path / "experiment"
        root.mkdir()
        (root / "asset.txt").write_text("planned")
        write_deployment_policy(root)
        source = subject(root)

        with pytest.raises(ValueError, match="copy_file or symlink_file"):
            source.apply_to(tmp_path / "destination", copy_func=shutil.copyfile)

    def test_plan_copy_raises_when_destination_already_exists(self, subject, tmp_path):
        from dallinger.deployment_plan import DeploymentPlanError

        root = tmp_path / "experiment"
        root.mkdir()
        (root / "asset.txt").write_text("planned")
        write_deployment_policy(root)
        destination = tmp_path / "destination"
        destination.mkdir()
        (destination / "asset.txt").write_text("existing")

        with pytest.raises(DeploymentPlanError, match="already exists"):
            subject(root).apply_to(destination)

    def test_policy_source_does_not_construct_git_client(self, subject, tmp_path):
        write_deployment_policy(tmp_path)
        (tmp_path / "asset.txt").write_text("a")
        with mock.patch("dallinger.utils.GitClient") as git:
            source = subject(tmp_path)
            list(source.map_locations_to(tmp_path / "dst"))
            assert source.size == source.deployment_plan.total_size
            git.assert_not_called()


@pytest.mark.parametrize(
    "reserved_destination",
    [
        ".dockerignore",
        "Dockerfile.production.dockerignore",
        "nested/.slugignore",
        "config.txt",
        "deploy.toml",
        "experiment_id.txt",
        "requirements.txt",
        "constraints.txt",
        "runtime.txt",
    ],
)
def test_explicit_provider_rejects_reserved_destinations_before_materialization(
    tmp_path, monkeypatch, reserved_destination
):
    from dallinger.deployment_plan import DeploymentPlanError
    from dallinger.utils import (
        DallingerFileSource,
        ExplicitFileSource,
        collate_experiment_files,
        copy_file,
    )

    destination = tmp_path / "assembly"
    provider_source = tmp_path / "provider.txt"
    provider_source.write_text("provider")
    experiment_source = mock.Mock()
    experiment_source.deployment_plan = object()
    monkeypatch.setattr(
        ExplicitFileSource,
        "map_locations_to",
        lambda self, root: iter([(provider_source, Path(root) / reserved_destination)]),
    )
    monkeypatch.setattr(
        DallingerFileSource,
        "map_locations_to",
        lambda self, root: iter(()),
    )

    with pytest.raises(DeploymentPlanError, match="reserved"):
        collate_experiment_files(
            config=mock.Mock(),
            experiment_path=tmp_path,
            destination=destination,
            copy_func=copy_file,
            experiment_files=experiment_source,
        )

    experiment_source.apply_to.assert_not_called()
    assert not destination.exists()


@pytest.mark.usefixtures("bartlett_dir", "active_config", "reset_sys_modules")
class TestSetupExperiment:
    @pytest.fixture
    def setup_experiment(self, env):
        from dallinger.deployment import setup_experiment as subject

        return subject

    def test_generates_exp_and_app_uid_if_none_provided(self, setup_experiment):
        exp_id, dst = setup_experiment(log=mock.Mock())

        assert isinstance(uuid.UUID(exp_id, version=4), uuid.UUID)

    def test_generated_uid_saved_to_config(self, active_config, setup_experiment):
        exp_id, dst = setup_experiment(log=mock.Mock())

        assert active_config.get("id") == exp_id

    def test_uses_provided_app_uid(self, setup_experiment):
        exp_id, dst = setup_experiment(log=mock.Mock(), app="my-custom-app-id")

        assert exp_id == "my-custom-app-id"

    def test_saves_provided_app_uid_to_config(self, active_config, setup_experiment):
        exp_id, dst = setup_experiment(log=mock.Mock(), app="my-custom-app-id")

        assert "my-custom-app-id" == active_config.get("heroku_app_id_root")

    def test_still_saves_uuid_in_addition_to_custom_app_id(
        self, active_config, setup_experiment
    ):
        exp_id, dst = setup_experiment(log=mock.Mock(), app="my-custom-app-id")

        assert isinstance(uuid.UUID(active_config.get("id"), version=4), uuid.UUID)

    def test_dashboard_credentials_saved_to_config(
        self, active_config, setup_experiment
    ):
        exp_id, dst = setup_experiment(log=mock.Mock())

        assert active_config.get("dashboard_user") == "admin"
        assert active_config.get("dashboard_password") == mock.ANY

    def test_setup_reuses_policy_source_without_mutating_constraints(
        self, setup_experiment, tmp_path
    ):
        source = mock.Mock(deployment_plan=object())
        with (
            mock.patch(
                "dallinger.utils.ensure_constraints_file_presence"
            ) as ensure_constraints,
            mock.patch(
                "dallinger.utils.assemble_experiment_temp_dir",
                return_value=tmp_path,
            ) as assemble,
        ):
            setup_experiment(
                log=mock.Mock(),
                local_checks=False,
                experiment_files=source,
            )

        ensure_constraints.assert_not_called()
        assert assemble.call_args.kwargs["experiment_files"] is source

    def test_setup_compiles_constraints_in_staging_when_policy_present(
        self, setup_experiment, tmp_path, monkeypatch
    ):
        source_root = Path.cwd()
        experiment_root = tmp_path / "experiment"
        shutil.copytree(source_root, experiment_root)
        (experiment_root / "constraints.txt").unlink(missing_ok=True)
        write_deployment_policy(experiment_root)
        monkeypatch.chdir(experiment_root)
        generated = "# staged constraints\ndallinger==0.0.0\n"

        def fake_ensure(directory, extras=None):
            Path(directory).joinpath("constraints.txt").write_text(generated)

        with mock.patch(
            "dallinger.utils.ensure_constraints_file_presence",
            side_effect=fake_ensure,
        ) as ensure:
            _, destination = setup_experiment(log=mock.Mock(), local_checks=False)

        ensure.assert_called()
        assert not (experiment_root / "constraints.txt").exists()
        assembled = Path(destination)
        assert assembled.joinpath("requirements.txt").read_text() == generated
        assert not assembled.joinpath("constraints.txt").exists()

    def test_setup_errors_when_staging_omits_constraints(
        self, setup_experiment, tmp_path, monkeypatch
    ):
        from dallinger.deployment_plan import DeploymentPlanError

        source_root = Path.cwd()
        experiment_root = tmp_path / "experiment"
        shutil.copytree(source_root, experiment_root)
        (experiment_root / "constraints.txt").unlink(missing_ok=True)
        write_deployment_policy(experiment_root)
        monkeypatch.chdir(experiment_root)

        with mock.patch("dallinger.utils.ensure_constraints_file_presence"):
            with pytest.raises(DeploymentPlanError, match="constraints.txt"):
                setup_experiment(log=mock.Mock(), local_checks=False)

    def test_setup_refreshes_stale_constraints_in_staging_only(
        self, setup_experiment, tmp_path, monkeypatch
    ):
        source_root = Path.cwd()
        experiment_root = tmp_path / "experiment"
        shutil.copytree(source_root, experiment_root)
        stale = "# automatically generated\nold==1.0.0\n"
        (experiment_root / "constraints.txt").write_text(stale)
        write_deployment_policy(experiment_root)
        monkeypatch.chdir(experiment_root)
        refreshed = "# automatically generated\nnew==2.0.0\n"

        def fake_ensure(directory, extras=None):
            Path(directory).joinpath("constraints.txt").write_text(refreshed)

        with mock.patch(
            "dallinger.utils.ensure_constraints_file_presence",
            side_effect=fake_ensure,
        ):
            _, destination = setup_experiment(log=mock.Mock(), local_checks=False)

        assert (experiment_root / "constraints.txt").read_text() == stale
        assert Path(destination).joinpath("requirements.txt").read_text() == refreshed

    def test_setup_merges_frontend_files_from_core_and_experiment(
        self, setup_experiment
    ):
        # Baseline
        exp_dir = os.getcwd()
        assert found_in("experiment.py", exp_dir)
        assert not found_in("experiment_id.txt", exp_dir)
        assert not found_in("Procfile", exp_dir)
        assert not found_in("runtime.txt", exp_dir)

        exp_id, dst = setup_experiment(log=mock.Mock())

        # dst should be a temp dir with a cloned experiment for deployment
        assert exp_dir != dst
        assert "/tmp" in dst

        assert found_in("experiment_id.txt", dst)
        assert found_in("experiment.py", dst)
        assert found_in("models.py", dst)
        assert found_in("Procfile", dst)
        assert found_in("runtime.txt", dst)

        assert found_in(os.path.join("static", "css", "dallinger.css"), dst)
        assert found_in(os.path.join("static", "scripts", "dallinger2.js"), dst)
        assert found_in(
            os.path.join("static", "scripts", "reconnecting-websocket.js"), dst
        )
        assert found_in(os.path.join("static", "scripts", "reqwest.min.js"), dst)
        assert found_in(os.path.join("static", "scripts", "spin.min.js"), dst)
        assert found_in(os.path.join("static", "scripts", "store+json2.min.js"), dst)
        assert found_in(os.path.join("static", "robots.txt"), dst)
        assert found_in(os.path.join("templates", "error.html"), dst)
        assert found_in(os.path.join("templates", "error-complete.html"), dst)
        assert found_in(os.path.join("templates", "exit_recruiter.html"), dst)
        assert found_in(os.path.join("templates", "exit_recruiter_mturk.html"), dst)
        assert found_in(os.path.join("templates", "launch.html"), dst)

        assert found_in(os.path.join("templates", "dashboard_lifecycle.html"), dst)
        assert found_in(os.path.join("templates", "dashboard_database.html"), dst)
        assert found_in(os.path.join("templates", "dashboard_heroku.html"), dst)
        assert found_in(os.path.join("templates", "dashboard_home.html"), dst)
        assert found_in(os.path.join("templates", "dashboard_monitor.html"), dst)
        assert found_in(os.path.join("templates", "dashboard_mturk.html"), dst)

        assert found_in(os.path.join("templates", "base", "ad.html"), dst)
        assert found_in(os.path.join("templates", "base", "consent.html"), dst)
        assert found_in(os.path.join("templates", "base", "dashboard.html"), dst)
        assert found_in(os.path.join("templates", "base", "layout.html"), dst)
        assert found_in(os.path.join("templates", "base", "questionnaire.html"), dst)

        with open(os.path.join(dst, "templates/layout.html"), "r") as copy_f:
            with open(os.path.join(exp_dir, "templates/layout.html"), "r") as orig_f:
                orig = orig_f.read()
                copy = copy_f.read()

        assert copy == orig

    def test_setup_uses_specified_python_version(self, active_config, setup_experiment):
        active_config.extend({"heroku_python_version": "3.13.1"})

        exp_id, dst = setup_experiment(log=mock.Mock())

        with open(os.path.join(dst, "runtime.txt"), "r") as file:
            version = file.read()

        assert version == "python-3.13.1"

    def test_setup_copies_docker_script(self, setup_experiment):
        exp_id, dst = setup_experiment(log=mock.Mock())

        assert found_in(os.path.join("prepare_docker_image.sh"), dst)

    def test_setup_assembles_policy_membership_and_existing_outputs(
        self, setup_experiment, tmp_path, monkeypatch
    ):
        source_root = Path.cwd()
        experiment_root = tmp_path / "experiment"
        shutil.copytree(source_root, experiment_root)
        (experiment_root / ".gitignore").write_text("ignored.txt\n")
        (experiment_root / "ignored.txt").write_text("included")
        (experiment_root / "excluded.txt").write_text("excluded")
        raw_config_marker = "# raw source configuration marker\n"
        config_path = experiment_root / "config.txt"
        config_path.write_text(raw_config_marker + config_path.read_text())
        write_deployment_policy(
            experiment_root,
            exclude=["excluded.txt"],
        )
        monkeypatch.chdir(experiment_root)

        def fake_ensure(directory, extras=None):
            dest = Path(directory) / "constraints.txt"
            source = experiment_root / "constraints.txt"
            if dest.exists():
                return
            if source.is_file():
                shutil.copyfile(source, dest)
            else:
                dest.write_text((Path(directory) / "requirements.txt").read_text())

        with mock.patch(
            "dallinger.utils.ensure_constraints_file_presence",
            side_effect=fake_ensure,
        ):
            _, destination = setup_experiment(log=mock.Mock())
        assembled = Path(destination)

        assert (assembled / "ignored.txt").read_text() == "included"
        assert (assembled / "deploy.toml").is_file()
        assert not (assembled / "excluded.txt").exists()
        assert raw_config_marker.strip() not in (assembled / "config.txt").read_text()
        assert (assembled / "experiment.py").is_file()
        assert (assembled / "Procfile").is_file()
        assert (assembled / "prepare_docker_image.sh").is_file()
        assert (assembled / "static" / "css" / "dallinger.css").is_file()

        from dallinger.deployment import _stage_heroku_assembly
        from dallinger.utils import ExperimentFileSource, GitClient

        subprocess.run(["git", "init", "-q"], cwd=assembled, check=True)
        monkeypatch.chdir(assembled)
        _stage_heroku_assembly(
            GitClient(),
            ExperimentFileSource(experiment_root),
        )
        indexed = subprocess.check_output(
            ["git", "ls-files"],
            cwd=assembled,
            text=True,
        ).splitlines()
        assert "ignored.txt" in indexed

    def test_setup_procfile_no_clock(self, setup_experiment):
        config = get_config()
        config.set("clock_on", False)
        assert config.get("clock_on") is False
        exp_dir = os.getcwd()
        assert not found_in("Procfile", exp_dir)

        exp_id, dst = setup_experiment(log=mock.Mock())

        assert found_in("Procfile", dst)
        with open(os.path.join(dst, "Procfile")) as proc:
            assert "clock: dallinger_heroku_clock" not in [p.strip() for p in proc]

    def test_setup_procfile_with_clock(self, setup_experiment):
        config = get_config()
        config.set("clock_on", True)
        assert config.get("clock_on") is True
        exp_dir = os.getcwd()
        assert not found_in("Procfile", exp_dir)

        exp_id, dst = setup_experiment(log=mock.Mock())

        assert found_in("Procfile", dst)
        with open(os.path.join(dst, "Procfile")) as proc:
            assert "clock: dallinger_heroku_clock" in [p.strip() for p in proc]

    def test_setup_with_custom_dict_config(self, setup_experiment):
        config = get_config()
        assert config.get("num_dynos_web") == 1

        exp_id, dst = setup_experiment(log=mock.Mock(), exp_config={"num_dynos_web": 2})
        # Config is updated
        assert config.get("num_dynos_web") == 2

        # Code snapshot is saved
        os.path.exists(os.path.join("snapshots", exp_id + "-code.zip"))

        # There should be a modified configuration in the temp dir
        deploy_config = configparser.ConfigParser()
        deploy_config.read(os.path.join(dst, "config.txt"))
        assert int(deploy_config.get("Parameters", "num_dynos_web")) == 2

    def test_setup_excludes_sensitive_config(self, setup_experiment):
        config = get_config()
        # Auto detected as sensitive
        config.register("a_password", str)
        # Manually registered as sensitive
        config.register("something_sensitive", str, sensitive=True)
        # Not sensitive at all
        config.register("something_normal", str)

        config.extend(
            {
                "a_password": "secret thing",
                "something_sensitive": "hide this",
                "something_normal": "show this",
            }
        )

        exp_id, dst = setup_experiment(log=mock.Mock())

        # The temp dir should have a config with the sensitive variables missing
        deploy_config = configparser.ConfigParser()
        deploy_config.read(os.path.join(dst, "config.txt"))
        assert deploy_config.get("Parameters", "something_normal") == "show this"
        with raises(configparser.NoOptionError):
            deploy_config.get("Parameters", "a_password")
        with raises(configparser.NoOptionError):
            deploy_config.get("Parameters", "something_sensitive")

    def test_reraises_db_connection_error(self, setup_experiment):
        from psycopg2 import OperationalError

        with mock.patch("dallinger.deployment.db.check_connection") as checker:
            checker.side_effect = OperationalError("Boom!")
            with pytest.raises(Exception) as ex_info:
                setup_experiment(log=mock.Mock())
                assert ex_info.match("Boom!")

    def test_setup_experiment_includes_dallinger_dependency(
        self, active_config, setup_experiment
    ):
        with mock.patch(
            "dallinger.utils.get_editable_dallinger_path"
        ) as get_editable_dallinger_path:
            # When dallinger is not installed as editable egg the requirements
            # file sent to heroku will include a version pin
            get_editable_dallinger_path.return_value = None
            _, dst = setup_experiment(log=mock.Mock())
        requirements = (Path(dst) / "requirements.txt").read_text()
        assert re.search("^dallinger", requirements, re.MULTILINE)

    def test_dont_build_egg_if_not_in_development(self, active_config):
        from dallinger.utils import assemble_experiment_temp_dir

        with mock.patch(
            "dallinger.utils.get_editable_dallinger_path"
        ) as get_editable_dallinger_path:
            # When dallinger is not installed as editable egg the requirements
            # file sent to heroku will include a version pin
            get_editable_dallinger_path.return_value = None
            log = mock.Mock()
            tmp_dir = assemble_experiment_temp_dir(log, active_config)

        assert "dallinger" in (Path(tmp_dir) / "requirements.txt").read_text()

    def test_assembly_failure_removes_private_temporary_tree(
        self, active_config, tmp_path, monkeypatch
    ):
        from dallinger.utils import assemble_experiment_temp_dir

        private_tree = tmp_path / "private-assembly"
        private_tree.mkdir()

        def fail_during_collation(*args, destination, **kwargs):
            Path(destination).mkdir(parents=True)
            (Path(destination) / "partial.txt").write_text("partial")
            raise RuntimeError("provider failed")

        monkeypatch.setattr("dallinger.utils.tempfile.mkdtemp", lambda: private_tree)
        monkeypatch.setattr(
            "dallinger.utils.collate_experiment_files", fail_during_collation
        )

        with pytest.raises(RuntimeError, match="provider failed"):
            assemble_experiment_temp_dir(mock.Mock(), active_config)

        assert not private_tree.exists()

    @pytest.mark.slow
    def test_build_egg_if_in_development(self, active_config):
        from dallinger.utils import assemble_experiment_temp_dir

        tmp_egg = tempfile.mkdtemp()
        (Path(tmp_egg) / "funniest").mkdir()
        (Path(tmp_egg) / "funniest" / "__init__.py").write_text("")
        (Path(tmp_egg) / "README").write_text("Foobar")
        (Path(tmp_egg) / "setup.py").write_text(
            textwrap.dedent("""\
        from setuptools import setup

        setup(name='funniest',
            version='0.1',
            description='The funniest joke in the world',
            url='http://github.com/storborg/funniest',
            author='Flying Circus',
            author_email='flyingcircus@example.com',
            license='MIT',
            packages=['funniest'],
            zip_safe=False)
        """)
        )
        with mock.patch(
            "dallinger.utils.get_editable_dallinger_path"
        ) as get_editable_dallinger_path:
            get_editable_dallinger_path.return_value = tmp_egg
            log = mock.Mock()
            tmp_dir = assemble_experiment_temp_dir(log, active_config, for_remote=True)

        assert "Dallinger is installed as an editable package" in log.call_args[0][0]
        assert "dallinger==" not in (Path(tmp_dir) / "requirements.txt").read_text()
        shutil.rmtree(tmp_dir)


@pytest.mark.usefixtures("experiment_dir", "active_config", "reset_sys_modules")
class TestSetupExperimentAdditional:
    @pytest.fixture
    def setup_experiment(self):
        from dallinger.deployment import setup_experiment as subject

        return subject

    def test_additional_files_can_be_included_by_module_function(
        self, setup_experiment
    ):
        # Baseline
        exp_dir = os.getcwd()
        assert found_in("dallinger_experiment.py", exp_dir)
        assert not found_in("experiment_id.txt", exp_dir)
        assert not found_in("Procfile", exp_dir)
        assert not found_in("runtime.txt", exp_dir)

        exp_id, dst = setup_experiment(log=mock.Mock())

        # dst should be a temp dir with a cloned experiment for deployment
        assert exp_dir != dst
        assert "/tmp" in dst

        assert found_in("experiment_id.txt", dst)
        assert found_in("dallinger_experiment.py", dst)

        # Files specified individually are copied
        assert found_in(os.path.join("static", "expfile.txt"), dst)
        # As are ones specified as part of a directory
        assert found_in(os.path.join("static", "copied_templates", "ad.html"), dst)

    def test_warning_if_multiple_experiments_found(
        self, active_config, setup_experiment
    ):
        with mock.patch("warnings.warn") as warn:
            _, _ = setup_experiment(log=mock.Mock())

        assert len(warn.mock_calls) >= 1
        e = warn.mock_calls[0][1][0]
        assert "EXPERIMENT_CLASS_NAME" in str(e)
        assert (
            "Picking TestExperiment from ['TestExperiment', 'ZSubclassThatSortsLower']"
            in str(e)
        )

        # No warning raised if we set the variable
        try:
            os.environ["EXPERIMENT_CLASS_NAME"] = "ZSubclassThatSortsLower"
            with mock.patch("warnings.warn") as warn:
                exp_id, dst = setup_experiment(log=mock.Mock())
            assert len(warn.mock_calls) == 0
        finally:
            del os.environ["EXPERIMENT_CLASS_NAME"]

    def test_additional_files_can_be_included_by_exp_classmethod(
        self, active_config, setup_experiment
    ):
        # Baseline
        exp_dir = os.getcwd()
        assert found_in("dallinger_experiment.py", exp_dir)
        assert not found_in("experiment_id.txt", exp_dir)
        assert not found_in("Procfile", exp_dir)
        assert not found_in("runtime.txt", exp_dir)

        try:
            os.environ["EXPERIMENT_CLASS_NAME"] = "ZSubclassThatSortsLower"
            exp_id, dst = setup_experiment(log=mock.Mock())
        finally:
            del os.environ["EXPERIMENT_CLASS_NAME"]

        # dst should be a temp dir with a cloned experiment for deployment
        assert exp_dir != dst
        assert "/tmp" in dst

        assert found_in("experiment_id.txt", dst)
        assert found_in("dallinger_experiment.py", dst)

        # Files specified individually are copied
        assert found_in(os.path.join("static", "different.txt"), dst)
        # As are ones specified as part of a directory
        assert found_in(os.path.join("static", "different", "ad.html"), dst)


@pytest.mark.usefixtures("active_config", "launch", "fake_git", "fake_redis", "faster")
class TestDeploySandboxSharedSetupNoExternalCalls:
    @pytest.fixture
    def dsss(self):
        from dallinger.deployment import deploy_sandbox_shared_setup

        return deploy_sandbox_shared_setup

    def test_result(self, dsss, heroku_mock):
        log = mock.Mock()
        result = dsss(log=log)
        assert result == {
            "app_home": "fake-web-url",
            "app_name": "dlgr-fake-uid",
            "dashboard_password": "DUMBPASSWORD",
            "dashboard_url": "fake-web-url/dashboard/",
            "dashboard_user": "admin",
            "recruitment_msg": "fake\nrecruitment\nlist",
        }

    def test_bootstraps_heroku(self, dsss, heroku_mock):
        dsss(log=mock.Mock())
        heroku_mock.bootstrap.assert_called_once()

    def test_legacy_assembly_uses_exact_legacy_git_add(
        self, dsss, heroku_mock, fake_git
    ):
        dsss(log=mock.Mock())

        assert fake_git.return_value.add.call_args_list[0] == mock.call("--all")

    def test_policy_assembly_force_adds_all_files(self, dsss, heroku_mock, fake_git):
        source = mock.Mock(deployment_plan=object())
        with mock.patch(
            "dallinger.deployment.ExperimentFileSource", return_value=source
        ):
            dsss(log=mock.Mock())

        assert fake_git.return_value.add.call_args_list[0] == mock.call(
            "--force", "--all"
        )

    def test_installs_phantomjs(self, dsss, heroku_mock):
        dsss(log=mock.Mock())
        heroku_mock.buildpack.assert_called_once_with(
            "https://github.com/stomita/heroku-buildpack-phantomjs"
        )

    def test_installs_addons(self, dsss, heroku_mock):
        dsss(log=mock.Mock())
        heroku_mock.addon.assert_has_calls(
            [
                mock.call("heroku-postgresql:standard-0"),
                mock.call("heroku-redis:premium-0"),
                mock.call("papertrail"),
                mock.call("sentry"),
            ]
        )

    def test_sets_app_properties(self, dsss, heroku_mock):
        dsss(log=mock.Mock())
        heroku_mock.set_multiple.assert_called_once_with(
            auto_recruit=True,
            AWS_ACCESS_KEY_ID="fake aws key",
            AWS_DEFAULT_REGION="us-east-1",
            AWS_SECRET_ACCESS_KEY="fake aws secret",
            FLASK_SECRET_KEY=mock.ANY,  # password is random
            smtp_password="fake email password",
            smtp_username="fake email username",
            whimsical=True,
        )

    def test_adds_db_url_to_config(self, dsss, heroku_mock, active_config):
        dsss(log=mock.Mock())
        assert active_config.get("database_url") == heroku_mock.db_url

    def test_verifies_working_redis(self, dsss, heroku_mock, fake_redis):
        dsss(log=mock.Mock())
        fake_redis.set.assert_called_once_with("foo", "bar")

    def test_scales_dynos(self, dsss, heroku_mock, active_config):
        active_config.set("clock_on", True)
        dsss(log=mock.Mock())
        heroku_mock.scale_up_dyno.assert_has_calls(
            [
                mock.call("web", 1, "free"),
                mock.call("worker", 1, "free"),
                mock.call("clock", 1, "free"),
            ]
        )

    def test_scales_different_dynos(self, dsss, heroku_mock, active_config):
        active_config.set("dyno_type", "ignored")
        active_config.set("dyno_type_web", "tiny")
        active_config.set("dyno_type_worker", "massive")
        dsss(log=mock.Mock())
        heroku_mock.scale_up_dyno.assert_has_calls(
            [mock.call("web", 1, "tiny"), mock.call("worker", 1, "massive")]
        )

    def test_calls_launch(self, dsss, heroku_mock, launch):
        log = mock.Mock()
        dsss(log=log)
        launch.assert_called_once_with("fake-web-url/launch", error=log)

    def test_heroku_sanity_check(self, dsss, heroku_mock, active_config):
        log = mock.Mock()
        dsss(log=log)
        # Get the patched heroku module
        from dallinger.deployment import heroku

        heroku.sanity_check.assert_called_once_with(active_config)

    def test_runs_prelaunch_actions(self, dsss, heroku_mock, active_config):
        log = mock.Mock()
        action = mock.Mock()
        dsss(log=log, prelaunch_actions=[action])

        action.assert_called_once_with(heroku_mock, active_config)


@pytest.mark.usefixtures("check_heroku")
@pytest.mark.usefixtures("bartlett_dir", "active_config", "launch", "herokuapp")
class TestDeploySandboxSharedSetupFullSystem:
    @pytest.fixture
    def dsss(self):
        from dallinger.deployment import deploy_sandbox_shared_setup

        return deploy_sandbox_shared_setup

    def test_full_deployment(self, dsss):
        no_clock = {"clock_on": False}  # can't run clock on free dyno
        result = dsss(
            log=mock.Mock(), exp_config=no_clock
        )  # can't run clock on free dyno
        app_name = result.get("app_name")
        assert app_name.startswith("dlgr")


@pytest.mark.usefixtures("bartlett_dir")
class Testhandle_launch_data:
    @pytest.fixture
    def handler(self):
        from dallinger.deployment import handle_launch_data

        return handle_launch_data

    def test_success(self, handler):
        log = mock.Mock()
        with mock.patch("dallinger.deployment.requests.post") as mock_post:
            result = mock.Mock(
                ok=True, json=mock.Mock(return_value={"message": "msg!"})
            )
            mock_post.return_value = result
            assert handler("/some-launch-url", error=log) == {"message": "msg!"}

    def test_failure_mock(self, handler):
        log = mock.Mock()
        with mock.patch("dallinger.deployment.requests.post") as mock_post:
            mock_post.return_value = mock.Mock(
                ok=False,
                json=mock.Mock(return_value={"message": "msg!"}),
                raise_for_status=mock.Mock(side_effect=requests.exceptions.HTTPError),
                status_code=500,
                text="Failure",
            )
            with pytest.raises(requests.exceptions.HTTPError):
                handler("/some-launch-url", error=log, delay=0.05, attempts=3)

        log.assert_has_calls(
            [
                mock.call("Error accessing /some-launch-url (500):\nFailure"),
                mock.call(
                    "Experiment launch failed. Trying again (attempt 2 of 3) in 0.1 seconds ..."
                ),
                mock.call("Error accessing /some-launch-url (500):\nFailure"),
                mock.call(
                    "Experiment launch failed. Trying again (attempt 3 of 3) in 0.2 seconds ..."
                ),
                mock.call("Error accessing /some-launch-url (500):\nFailure"),
                mock.call("Experiment launch failed after multiple attempts."),
                mock.call("msg!"),
            ]
        )

    def test_failure_real(self, handler):
        log = mock.Mock()

        try:
            handler("https://httpbingo.org/status/500", log, attempts=1)
        except requests.exceptions.HTTPError:
            pass
        log.assert_has_calls(
            [
                mock.call(
                    "Error parsing response from https://httpbingo.org/status/500, check server logs for details.\n"
                ),
                mock.call("Experiment launch failed after multiple attempts."),
            ]
        )

        log.reset_mock()
        try:
            handler("https://nonexistent.example.com/", log, attempts=1)
        except requests.exceptions.ConnectionError:
            pass
        assert (
            "Error accessing https://nonexistent.example.com/"
            in log.call_args_list[0][0][0]
        )

    def test_non_json_response_error(self, handler):
        log = mock.Mock()
        with mock.patch("dallinger.deployment.requests.post") as mock_post:
            mock_post.return_value = mock.Mock(
                json=mock.Mock(side_effect=ValueError), text="Big, unexpected problem."
            )
            with pytest.raises(ValueError):
                handler("/some-launch-url", error=log)

        log.assert_called_once_with(
            "Error parsing response from /some-launch-url, check server logs for details.\n\n"
            "Big, unexpected problem."
        )

    def test_error_log_messages(self, handler):
        log = mock.Mock()
        with (
            mock.patch("dallinger.deployment.requests.post") as mock_post,
            mock.patch("dallinger.deployment.print_bold") as mock_print,
            mock.patch("dallinger.deployment.time.sleep"),
        ):
            mock_response = mock.Mock(
                ok=False,
                json=mock.Mock(return_value={"message": "msg!"}),
                status_code=500,
                text="Failure",
            )
            mock_response.raise_for_status = mock.Mock(
                side_effect=requests.exceptions.HTTPError
            )
            mock_post.return_value = mock_response

            # Test Heroku context
            with pytest.raises(requests.exceptions.HTTPError):
                handler(
                    "https://example.com/some-launch-url", error=log, context="heroku"
                )
            mock_print.assert_called_once_with(
                "For detailed server logs, visit the Papertrail add-on in your Heroku dashboard"
            )

            # Test SSH context with Dozzle
            mock_print.reset_mock()
            with pytest.raises(requests.exceptions.HTTPError):
                handler(
                    "https://example.com/some-launch-url",
                    error=log,
                    context="ssh",
                    dns_host="example.com",
                    dozzle_password="secret",
                )
            mock_print.assert_called_once_with(
                "Check the detailed server logs at https://logs.example.com (user = dallinger, password = secret)"
            )

            # Test local context
            mock_print.reset_mock()
            with pytest.raises(requests.exceptions.HTTPError):
                handler("/some-launch-url", error=log, context="local")
            mock_print.assert_not_called()


@pytest.mark.usefixtures("bartlett_dir", "clear_workers", "env")
@pytest.mark.slow
class TestDebugServer:
    @pytest.fixture
    def debugger_unpatched(self, output):
        from dallinger.deployment import DebugDeployment

        debugger = DebugDeployment(
            output, verbose=True, bot=False, proxy_port=None, exp_config={}
        )
        yield debugger
        if debugger.status_thread:
            debugger.status_thread.join()

    @pytest.fixture
    def no_browser_debugger(self, output):
        from dallinger.deployment import DebugDeployment

        debugger = DebugDeployment(
            output,
            verbose=True,
            bot=False,
            proxy_port=None,
            exp_config={},
            no_browsers=True,
        )
        yield debugger
        if debugger.status_thread:
            debugger.status_thread.join()

    @pytest.fixture
    def debugger(self, debugger_unpatched):
        from dallinger.heroku.tools import HerokuLocalWrapper

        debugger = debugger_unpatched
        debugger.notify = mock.Mock(return_value=HerokuLocalWrapper.MONITOR_STOP)
        return debugger

    def test_startup(self, debugger):
        debugger.no_browsers = True
        debugger.run()
        "Server is running" in str(debugger.out.log.call_args_list[0])

    def test_raises_if_heroku_wont_start(self, debugger):
        mock_wrapper = mock.Mock(
            __enter__=mock.Mock(side_effect=OSError),
            __exit__=mock.Mock(return_value=False),
        )
        with mock.patch(
            "dallinger.deployment.HerokuLocalDeployment.WRAPPER_CLASS"
        ) as Wrapper:
            Wrapper.return_value = mock_wrapper
            with pytest.raises(OSError):
                debugger.run()

    def test_new_participant(self, debugger_unpatched):
        debugger = debugger_unpatched
        debugger.new_recruit = mock.Mock(return_value=None)
        assert not debugger.new_recruit.called
        debugger.notify(" New participant requested: http://example.com")
        assert debugger.new_recruit.called

    def test_recruitment_closed(self, debugger_unpatched):
        debugger = debugger_unpatched
        debugger.new_recruit = mock.Mock(return_value=None)
        debugger.heroku = mock.Mock()
        response = mock.Mock(json=mock.Mock(return_value={"completed": True}))
        with mock.patch("dallinger.deployment.requests") as mock_requests:
            mock_requests.get.return_value = response
            debugger.notify(recruiters.CLOSE_RECRUITMENT_LOG_PREFIX)
            debugger.status_thread.join()

        debugger.out.log.assert_called_with("Experiment completed, all nodes filled.")
        debugger.heroku.stop.assert_called_once()

    def test_new_recruit(self, debugger_unpatched, browser):
        debugger_unpatched.notify(
            " {} some-fake-url".format(recruiters.NEW_RECRUIT_LOG_PREFIX)
        )

        browser.assert_called_once_with("some-fake-url")

    def test_new_recruit_no_browser(self, no_browser_debugger, browser):
        no_browser_debugger.notify(
            " {} some-fake-url".format(recruiters.NEW_RECRUIT_LOG_PREFIX)
        )
        browser.assert_not_called()

    def test_new_recruit_opens_browser_on_proxy_port(
        self, active_config, debugger_unpatched, browser
    ):
        debugger_unpatched.proxy_port = "2222"
        debugger_unpatched.notify(
            " {} some-fake-url:{}".format(
                recruiters.NEW_RECRUIT_LOG_PREFIX, active_config.get("base_port")
            )
        )
        browser.assert_called_once_with("some-fake-url:2222")

    def test_new_recruit_not_triggered_if_quoted(self, debugger_unpatched, browser):
        debugger_unpatched.notify(
            ' "{}" some-fake-url'.format(recruiters.NEW_RECRUIT_LOG_PREFIX)
        )

        browser.assert_not_called()

    @pytest.mark.usefixtures("check_runbot")
    def test_debug_bots(self, env):
        # Make sure debug server runs to completion with bots
        p = pexpect.spawn(
            "dallinger", ["debug", "--verbose", "--bot"], env=env, encoding="utf-8"
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact("Server is running", timeout=300)
            p.expect_exact("Recruitment is complete", timeout=600)
            p.expect_exact("Experiment completed", timeout=60)
            p.expect_exact("Local Heroku process terminated", timeout=10)
        finally:
            try:
                p.sendcontrol("c")
                p.read()
            except IOError:
                pass

    def test_failure(self, debugger):
        with mock.patch("dallinger.deployment.HerokuLocalDeployment.WRAPPER_CLASS"):
            with mock.patch("dallinger.deployment.requests.post") as mock_post:
                mock_post.return_value = mock.Mock(
                    ok=False,
                    json=mock.Mock(return_value={"message": "msg!"}),
                    raise_for_status=mock.Mock(
                        side_effect=requests.exceptions.HTTPError
                    ),
                    status_code=500,
                    text="Failure",
                )
                debugger.run()

        # Only one launch attempt should be made in debug mode
        debugger.out.error.assert_has_calls(
            [
                mock.call(
                    "Error accessing http://localhost:5000/launch (500):\nFailure"
                ),
                mock.call("Experiment launch failed after multiple attempts."),
                mock.call("msg!"),
            ]
        )


if os.environ.get("CI"):
    MAX_DOCKER_RERUNS = 5
else:
    MAX_DOCKER_RERUNS = 1


@pytest.mark.usefixtures("bartlett_dir", "clear_workers", "env")
@pytest.mark.slow
@pytest.mark.docker
class TestDockerServer:
    @pytest.fixture(autouse=True)
    def stop_all_docker_containers(self, env):
        import docker

        client = docker.client.from_env()
        for container in client.containers.list():
            if container.name.startswith("bartlett1932"):
                container.stop()

    @pytest.mark.skipif(bool(os.environ.get("CI")), reason="Fails when run in the CI")
    def test_docker_debug_with_bots(self, env):
        # Make sure debug server runs to completion with bots
        p = pexpect.spawn(
            "dallinger",
            ["docker", "debug", "--verbose", "--bot", "--no-browsers"],
            env=env,
            encoding="utf-8",
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact("Server is running", timeout=240)
            p.expect_exact("Recruitment is complete", timeout=180)
            p.expect_exact("'status': 'success'", timeout=120)
            p.expect_exact("Experiment completed", timeout=10)
            p.expect(pexpect.EOF)
        finally:
            try:
                p.sendcontrol("c")
                p.read()
            except IOError:
                pass

    @pytest.mark.flaky(reruns=MAX_DOCKER_RERUNS)
    def test_docker_debug_without_bots(self, env):
        sys.path.append(os.getcwd())
        from experiment import Bot

        # Make sure debug server runs to completion without bots
        p = pexpect.spawn(
            "dallinger",
            ["docker", "debug", "--verbose", "--no-browsers"],
            env=env,
            encoding="utf-8",
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact("Server is running", timeout=180)
            p.expect_exact("Initial recruitment list:", timeout=30)
            p.expect("New participant requested.*", 50)
            Bot(re.search("http://[^ \n\r]+", p.after).group()).run_experiment()
            p.expect("New participant requested.*", 50)
            Bot(re.search("http://[^ \n\r]+", p.after).group()).run_experiment()
            p.expect_exact("Recruitment is complete", timeout=240)
            p.expect_exact("'status': 'success'", timeout=120)
            p.expect_exact("Experiment completed", timeout=20)
            p.expect(pexpect.EOF)
        finally:
            try:
                p.sendcontrol("c")
                p.read()
            except IOError:
                pass


@pytest.mark.usefixtures("bartlett_dir", "clear_workers", "env")
@pytest.mark.slow
class TestLoad:
    exp_id = "some_experiment_id"

    @pytest.fixture
    def export(self):
        # Data export created, then removed after test[s]
        from dallinger.data import export

        path = export(self.exp_id, local=True)
        yield path
        os.remove(path)

    @pytest.fixture
    def loader(self, db_session, output, clear_workers):
        from dallinger.deployment import LoaderDeployment
        from dallinger.heroku.tools import HerokuLocalWrapper

        loader = LoaderDeployment(self.exp_id, output, verbose=True, exp_config={})
        loader.notify = mock.Mock(return_value=HerokuLocalWrapper.MONITOR_STOP)

        yield loader

    @pytest.fixture
    def replay_loader(self, db_session, env, output, clear_workers):
        from dallinger.deployment import LoaderDeployment

        loader = LoaderDeployment(
            self.exp_id, output, verbose=True, exp_config={"replay": True}
        )
        loader.keep_running = mock.Mock(return_value=False)

        def launch_and_finish(self):
            from dallinger.heroku.tools import HerokuLocalWrapper

            loader.out.log("Launching replay browser...")
            return HerokuLocalWrapper.MONITOR_STOP

        loader.start_replay = mock.Mock(
            return_value=None, side_effect=launch_and_finish
        )
        yield loader

    def test_load_runs(self, loader, export):
        loader.keep_running = mock.Mock(return_value=False)
        loader.run()

        loader.out.log.assert_has_calls(
            [
                mock.call("Starting up the Heroku Local server..."),
                mock.call("Ingesting dataset from some_experiment_id-data.zip..."),
                mock.call(
                    "Server is running on http://localhost:{}. Press Ctrl+C to exit.".format(
                        os.environ.get("base_port", 5000)
                    )
                ),
                mock.call("Terminating dataset load for experiment some_experiment_id"),
                mock.call("Cleaning up local Heroku process..."),
                mock.call("Local Heroku process terminated."),
            ]
        )

    def test_load_raises_on_nonexistent_id(self, loader):
        loader.app_id = "nonsense"
        loader.keep_running = mock.Mock(return_value=False)
        with pytest.raises(IOError):
            loader.run()

    def test_load_with_replay(self, replay_loader, export):
        replay_loader.run()

        replay_loader.out.log.assert_has_calls(
            [
                mock.call("Starting up the Heroku Local server..."),
                mock.call("Ingesting dataset from some_experiment_id-data.zip..."),
                mock.call(
                    "Server is running on http://localhost:{}. Press Ctrl+C to exit.".format(
                        os.environ.get("base_port", 5000)
                    )
                ),
                mock.call("Launching the experiment..."),
                mock.call("Launching replay browser..."),
                mock.call("Terminating dataset load for experiment some_experiment_id"),
                mock.call("Cleaning up local Heroku process..."),
                mock.call("Local Heroku process terminated."),
            ]
        )
