"""Register experiments through the Open Science Framework."""

import logging
import os

import requests

from dallinger.config import get_config

logger = logging.getLogger(__file__)
config = get_config()
root = "https://api.osf.io/v2"


def register(dlgr_id, snapshot=None):
    """Register the experiment using configured services."""
    try:
        config.get("osf_access_token")
    except KeyError:
        pass
    else:
        osf_id = _create_osf_project(dlgr_id)
        _upload_assets_to_OSF(dlgr_id, osf_id)


def _create_osf_project(dlgr_id, description=None):
    """Create a project on the OSF."""

    if not description:
        description = "Experiment {} registered by Dallinger.".format(
            dlgr_id
        )

    r = requests.post(
        "{}/nodes/".format(root),
        data={
            "type": "nodes",
            "category": "project",
            "title": "Experiment dlgr-{}".format(dlgr_id[0:8]),
            "description": description,
        },
        headers={
            "Authorization": "Bearer {}".format(config.get("osf_access_token"))
        }
    )
    r.raise_for_status()
    osf_id = r.json()['data']['id']

    logger.info("Project registered on OSF at http://osf.io/{}".format(osf_id))

    return osf_id


def _upload_assets_to_OSF(dlgr_id, osf_id, provider="osfstorage"):
    """Upload experimental assets to the OSF."""
    root = "https://files.osf.io/v1"
    snapshot_filename = "{}-code.zip".format(dlgr_id)
    snapshot_path = os.path.join("snapshots", snapshot_filename)
    r = requests.put(
        "{}/resources/{}/providers/{}/".format(
            root,
            osf_id,
            provider,
        ),
        params={
            "kind": "file",
            "name": snapshot_filename,
        },
        headers={
            "Authorization": "Bearer {}".format(
                config.get("osf_access_token")),
            "Content-Type": "text/plain",
        },
        data=open(snapshot_path, 'rb'),
    )
    r.raise_for_status()
