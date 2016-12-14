# from dallinger import nodes, information, db, models
# from dallinger.information import Meme, Gene
# from nose.tools import raises
# import subprocess
# import re
# import requests


# class TestBartlett(object):

#     sandbox_output = subprocess.check_output(
#         "cd demos/bartlett1932; dallinger sandbox", shell=True)
#     exp_id = re.search('Running as experiment (.*)...', sandbox_output).group(1)
#     exp_address = "http://" + exp_id + ".herokuapp.com"

#     subprocess.call("cd demos/bartlett1932; dallinger logs --app " + exp_id, shell=True)

#     args = {'hitId': 'bartlett-test-hit', 'assignmentId': 1, 'workerId': 1, 'mode': 'sandbox'}
#     participant = requests.get(exp_address + '/exp', params=args)
#     #print participant.text

#     args = {'Event.1.EventType': 'AssignmentAccepted', 'Event.1.AssignmentId': 1}
#     notification = requests.post(exp_address + '/notifications', data=args)

#     working = True
#     while working is True:
#         args = {'unique_id': '1:1'}
#         agent = requests.post(exp_address + '/agents', data=args)
#         working = agent.status_code == 200
#         if working is True:
#             agent_id = agent.json()['agents']['id']
#             args = {'destination_id': agent_id}
#             transmission = requests.get(exp_address + '/transmissions', data=args)
#             info = requests.get(
#                 exp_address + '/information/' +
#                 str(transmission.json()['transmissions'][0]['info_id']),
#                 data=args)
#             args = {'origin_id': agent_id, 'contents': 'test test test', 'info_type': 'base'}
#             requests.post(exp_address + '/information', data=args)

#     #subprocess.call("heroku apps:destroy --app " + exp_id + " --confirm " + exp_id, shell=True)
#     # for app in $(heroku apps | sed '/[pt]/ d'); do
#     #     heroku apps:destroy --app $app --confirm $app;
#     # done
