import requests
import json
import logging

logger = logging.getLogger(__file__)


class PulseService:
    api_url = None
    app_id = None
    campaign_id = None
    project_id = None

    def __init__(self, api_url, app_id):
        """ Setup Credentials """
        self.api_url = api_url
        self.app_id = app_id

    def api_post(self, endpoint, payload):
        """ Post to the Pulse API """
        r = requests.post(self.api_url + "/{}".format(endpoint), json=payload,
                          headers={'applicationId': self.app_id})

        resp = json.loads(r.text)

        return resp

    def api_get(self, endpoint, query):
        """ Get from the Pulse API """
        r = requests.get(self.api_url + "/{}".format(endpoint), params=query,
                         headers={'applicationId': self.app_id})

        resp = json.loads(r.text)

        return resp

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

        if resp.get('id') is not None:
            campaign_id = resp.get('id')

        if len(resp.get('projects', [])) < 1:
            raise Exception("Invalid response on create campaign: {}".format(resp))

        self.project_id = resp.get('projects')[0].get('id')

        self.campaign_id = campaign_id

        return True

    def recruit(self, flow, url):
        """ Send notification to contacts that the experiment is live """
        payload = {
            "flow": flow,
            "contacts": [],
            "restart_participants": True,
            "extra": {
                "applicationId": self.app_id,
                "activityId": self.project_id,
                "url": url
            }
        }

        resp = self.api_post('engage', payload)

        if resp.get('response') is None or resp.get('response', {}).get('flow', {}).get('uuid') != flow:
            raise Exception("Could not trigger flow")

        return True

    def reward(self, flow, agentId):
        """ Reward participants with airtime"""
        payload = {
            "flow": flow,
            "contacts": [agentId],
            "restart_participants": True,
            "extra": {
                "applicationId": self.app_id,
                "message": "Thank you for participating, you will be receiving your reward shortly. Would you like to refer anybody else? You will receive a .5 airtime bonus if they participate! If yes, please provide their contact info.",
                "netAmount": 34.565,
                "paymentProcessor": "TransferTo",
                "currency": "AirTime"
            }
        }

        resp = self.api_post('engage', payload)

        if resp.get('response') is None or resp.get('response', {}).get('flow', {}).get('uuid') != flow:
            raise Exception("Could not trigger flow")

        return True


