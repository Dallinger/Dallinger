from wallace import nodes, information, db, models
from wallace.information import Meme, Gene
from nose.tools import raises
import subprocess
import re
import requests


class TestBartlett(object):

    sandbox_output = subprocess.check_output("cd examples/bartlett1932; wallace sandbox", shell=True)
    exp_id = re.search('Running as experiment (.*)...', sandbox_output).group(1)
    exp_address = "http://" + exp_id + ".herokuapp.com"

    subprocess.call("cd examples/bartlett1932; wallace logs --app " + exp_id, shell=True)

    args = {'hitId': 'bartlett-test-hit', 'assignmentId': 1, 'workerId': 1, 'mode': 'sandbox'}
    participant = requests.get(exp_address + '/exp', params=args)
    #print participant.text

    args = {'Event.1.EventType': 'AssignmentAccepted', 'Event.1.AssignmentId': 1}
    notification = requests.post(exp_address + '/notifications', data=args)

    working = True
    while working is True:
        args = {'unique_id': '1:1'}
        agent = requests.post(exp_address + '/agents', data=args)
        print agent
        print agent.contents
        print agent.text
        working = agent.status == 200
        if working is True:
            agent_uuid = agent.contents.agents.uuid
            args = {'destination_uuid': agent_uuid}
            transmission = requests.get(exp_address + '/transmissions', data=args)
            info = requests.get(exp_address + '/info/' + transmission.contents.transmissions[0].info_uuid, data=args)
            args = {'origin_uuid': agent_uuid, 'contents': 'test test test', 'info_type': 'base'}
            requests.post(exp_address + '/information', data=args)

    #subprocess.call("heroku apps:destroy --app " + exp_id + " --confirm " + exp_id, shell=True)
    # for app in $(heroku apps | sed '/[pt]/ d'); do heroku apps:destroy --app $app --confirm $app; done
