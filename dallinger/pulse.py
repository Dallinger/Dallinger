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
        """ Check activity endpoint to see if this application has an existing project associated with it"""
        resp = self.api_get('activity')

        if resp.get('response') is None or type(resp.get('response')) is not dict:
            raise Exception("Invalid response on get activity: {}".format(resp))
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

        logger.debug("return {}".format(resp))

        if resp.get('response') is None or type(resp.get('response')) is not dict:
            raise Exception("Invalid response on create campaign: {}".format(resp))
        else:
            resp = resp.get('response')

        if len(resp.get('projects', [])) < 1:
            raise Exception("Invalid response on create campaign: {}".format(resp))

        self.project_id = resp.get('projects')[0].get('id')

        return True

    def get_agents(self):
        return ['ecbd08d2-6fdc-430b-abac-7b1827ae4433']

    def recruit(self, agent, url):
        """ Send notification to contacts that the experiment is live """
        payload = {
            "type": "ShareURL",
            "agents": [agent],
            "activityId": self.project_id,
            "url": url,
            "message": "The experiment is ready, please click on the URL."
        }

        resp = self.api_post('engage', payload)

        if resp.get('response') is None or resp.get('response', {}).get('flow', {}).get('uuid') is None:
            raise Exception("Could not trigger flow")

        return True

    def reward(self, hitId, agentId):
        """ Reward participants with airtime"""

        payload = {
            "type": "SolicitReferralAndPay",
            "agents": [agentId],
            "message": "Thank you for participating, you will be receiving your reward shortly. Would you like to refer anybody else? You will receive a .5 airtime bonus if they participate! If yes, please provide their contact info.",
            "netAmount": "1.0",
            "paymentProcessor": "TransferTo",
            "currency": "AirTime",
            'activityId': hitId,
            "agent_properties": {"participatedIn": hitId}
        }

        logger.info("Rewarding {}".format(agentId))

        resp = self.api_post('engage', payload)

        if resp.get('response') is None or resp.get('response', {}).get('flow', {}).get('uuid') is None:
            raise Exception("Could not trigger flow")

        return True


