import requests
import json
import logging

logger = logging.getLogger(__file__)


class PulseService:
    api_url = None
    api_key = None
    app_id = None
    project_id = None

    def __init__(self, api_url, api_key, app_id):
        """ Setup Credentials """
        self.api_url = api_url
        self.api_key = api_key
        self.app_id = app_id

    def api_post(self, endpoint, payload):
        """ Post to the Pulse API """
        r = requests.post(self.api_url + "/{}".format(endpoint), json=payload,
                          headers={'applicationId': self.app_id, 'x-api-key': self.api_key})

        resp = json.loads(r.text)

        return resp

    def api_get(self, endpoint, query={}):
        """ Get from the Pulse API """
        r = requests.get(self.api_url + "/{}".format(endpoint), params=query,
                         headers={'applicationId': self.app_id, 'x-api-key': self.api_key})

        resp = json.loads(r.text)

        return resp

    def get_existing_activity(self):
        """ Check activity endpoint to see if this application has an existing project
        associated with it"""
        resp = self.api_get('activity')

        if resp.get('response') is None or not isinstance(resp.get('response'), dict):
            raise ValueError("Invalid response on get activity: {}".format(resp))
        else:
            resp = resp.get('response')

        for activity in resp.get('activities', {}):
            if activity.get('type') == 'Project' and activity.get('id'):
                self.project_id = activity.get('id')
                return activity.get('id')

        return None

    def create_campaign(self, title, description, location, link, image_url, page_id):
        """ Create a facebook campaign and save the campaign and project IDs """
        payload = {
            'name': title,
            'projects': [
                {
                    'name': title,
                    'location': '<{}>'.format(location),
                    'flow': {
                        'components': [
                            {
                                'type': 'FacebookAdvertisement',
                                'name': title,
                                'message': description,
                                'appLink': link,
                                'imageUrl': image_url,
                                'facebookPageId': page_id
                            },
                            {
                                'type': 'FacebookMessengerBot',
                                'name': title
                            }
                        ],
                        'name': title
                    },
                    'status': 'activated',
                    'version': 1
                }
            ],
            'status': 'activated'
        }

        resp = self.api_post('campaign', payload)

        if resp.get('response') is None or not isinstance(resp.get('response'), dict):
            raise ValueError("Invalid response on create campaign: {}".format(resp))
        else:
            resp = resp.get('response')

        if not resp.get('projects', []):
            raise ValueError("Invalid response on create campaign: {}".format(resp))

        self.project_id = resp.get('projects')[0].get('id')

        logger.info("Project created {}".format(self.project_id))

        return True

    def get_agents(self, location):
        resp = self.api_get('agent', {'location': location})

        resp_agents = resp.get('response', {}).get('agents')
        if resp_agents is None:
            raise ValueError("Could not get pulse recruits")

        agents = []

        for agent in resp_agents:
            if agent.get('participatedIn') == self.project_id:
                logger.debug("Agent {} already participated, skipping".format(agent.get('id')))
            else:
                logger.debug("Got agent {}".format(agent.get('id')))
                agents.append(agent.get('id'))

        return agents

    def recruit(self, agent, url):
        """ Send notification to contacts that the experiment is live """
        payload = {
            "type": "ShareURL",
            "agents": [agent],
            "activityId": self.project_id,
            "url": url,
            "message": "The experiment is ready, please click on the URL to begin."
        }

        resp = self.api_post('engage', payload)

        uuid = resp.get('response', {}).get('flow', {}).get('uuid')
        if resp.get('response') is None or uuid is None:
            raise ValueError("Could not trigger flow")

        return True

    def reward(self, hitId, agentId, processor, currency, amount):
        """ Reward participants with airtime"""

        payload = {
            "type": "TransferPayment",
            "agents": [agentId],
            "message": "Thank you for participating, you will be receiving your reward shortly.",
            "netAmount": amount,
            "paymentProcessor": processor,
            "currency": currency,
            'activityId': hitId,
            "agent_properties": {"participatedIn": hitId}
        }

        logger.info("Rewarding {}".format(agentId))

        resp = self.api_post('engage', payload)

        uuid = resp.get('response', {}).get('flow', {}).get('uuid')
        if resp.get('response') is None or uuid is None:
            raise ValueError("Could not trigger flow")

        return True
