from email.mime.text import MIMEText
from smtplib import SMTP


resubmit_whimsical = """Dearest Friend,

I am writing to let you know that at {when},
during my regular (and thoroughly enjoyable) perousal of the most charming
participant data table, I happened to notice that assignment {assignment_id}
has been taking longer than we were expecting. I recall you had suggested
{duration} minutes as an upper limit for what was an acceptable length of time
for each assignement, however this assignment had been underway for a shocking
{minutes_so_far} minutes, a full {minutes_excess} minutes over your allowance.
I immediately dispatched a telegram to our mutual friends at AWS and they were
able to assure me that although the notification had failed to be correctly
processed, the assignment had in fact been completed. Rather than trouble you,
I dealt with this myself and I can assure you there is no immediate cause for
concern. Nonetheless, for my own peace of mind, I would appreciate you taking
the time to look into this matter at your earliest convenience.

I remain your faithful and obedient servant,

William H. Dallinger

P.S. Please do not respond to this message, I am busy with other matters.
"""


resubmit_nonwhimsical = """Dear experimenter,

This is an automated email from
Dallinger. You are receiving this email because the Dallinger platform has
discovered evidence that a notification from Amazon Web Services failed to
arrive at the server. Dallinger has automatically contacted AWS and has
determined the dropped notification was a submitted notification (i.e. the
participant has finished the experiment). This is a non-fatal error and so
Dallinger has auto-corrected the problem. Nonetheless you may wish to check the
database.

Best,
The Dallinger dev. team.

Error details:
Assignment: {assignment_id}
Allowed time: {duration}
Time since participant started: {minutes_so_far}
"""


cancelled_hit_whimsical = """Dearest Friend,

I am afraid I write to you with most grave tidings. At {when},
during a routine check of the usually most delightful participant data table,
I happened to notice that assignment {assignment_id} has been taking longer
than we were expecting. I recall you had suggested {duration} minutes as an
upper limit for what was an acceptable length of time for each assignment,
however this assignment had been underway for a shocking {minutes_so_far}
minutes, a full {minutes_excess} minutes over your allowance. I immediately
dispatched a telegram to our mutual friends at AWS and they infact informed me
that they had already sent us a notification which we must have failed to
process, implying that the assignment had not been successfully completed. Of
course when the seriousness of this scenario dawned on me I had to depend on
my trusting walking stick for support: without the notification I didn't know
to remove the old assignment's data from the tables and AWS will have already
sent their replacement, meaning that the tables may already be in a most
unsound state!

I am sorry to trouble you with this, however, I do not know how to proceed so
rather than trying to remedy the scenario myself, I have instead temporarily
ceased operations by expiring the HIT with the fellows at AWS and have
refrained from posting any further invitations myself. Once you see fit I
would be most appreciative if you could attend to this issue with the caution,
sensitivity and intelligence for which I know you so well.

I remain your faithful and
obedient servant,
William H. Dallinger

P.S. Please do not respond to this
message, I am busy with other matters.
"""

cancelled_hit_nonwhimsical = """Dear experimenter,

This is an automated email from
Dallinger. You are receiving this email because the Dallinger platform has
discovered evidence that a notification from Amazon Web Services failed to
arrive at the server. Dallinger has automatically contacted AWS and has
determined the dropped notification was an abandoned/returned notification
(i.e. the participant had returned the experiment or had run out of time).
This is a serious error and so Dallinger has paused the experiment - expiring
the HIT on MTurk and setting auto_recruit to false. Participants currently
playing will be able to finish, however no further participants will be
recruited until you do so manually. We strongly suggest you use the details
below to check the database to make sure the missing notification has not caused
additional problems before resuming.
If you are receiving a lot of these
emails this suggests something is wrong with your experiment code.

Best,

The Dallinger dev. team.

Error details:
Assignment: {assignment_id}

Allowed time: {duration}
Time since participant started: {minutes_so_far}
"""


class EmailingHITMessager(object):

    def __init__(self, when, assignment_id, hit_duration, time_active, config, server=None):
        self.when = when
        self.assignment_id = assignment_id
        self.duration = round(hit_duration / 60)
        self.minutes_so_far = round(time_active / 60)
        self.minutes_excess = round((time_active - hit_duration) / 60)
        self.whimsical = config.get("whimsical")
        self.username = config.get('dallinger_email_username')
        self.fromaddr = self.username + "@gmail.com"
        self.toaddr = config.get('contact_email_on_error')
        self.email_password = config.get("dallinger_email_key")
        self.server = server or SMTP('smtp.gmail.com:587')

    def _send(self, data):
        msg = MIMEText(data['message'])
        msg['Subject'] = data['subject']
        self.server.starttls()
        self.server.login(self.username, self.email_password)
        self.server.sendmail(self.fromaddr, self.toaddr, msg.as_string())
        self.server.quit()

    def send_resubmitted_msg(self):
        data = self._build_resubmitted_msg()
        self._send(data)
        return data

    def send_hit_cancelled_msg(self):
        data = self._build_hit_cancelled_msg()
        self._send(data)
        return data

    def _build_resubmitted_msg(self):
        if self.whimsical:
            template = resubmit_whimsical
            data = {
                'message': template.format(**self.__dict__),
                'subject': 'A matter of minor concern.'
            }

        else:
            template = resubmit_nonwhimsical
            data = {
                'message': template.format(**self.__dict__),
                'subject': "Dallinger automated email - minor error."
            }

        return data

    def _build_hit_cancelled_msg(self):
        if self.whimsical:
            template = cancelled_hit_whimsical
            data = {
                'message': template.format(**self.__dict__),
                'subject': "Most troubling news."
            }
        else:
            template = cancelled_hit_nonwhimsical
            data = {
                'message': template.format(**self.__dict__),
                'subject': "Dallinger automated email - major error."
            }

        return data


class NullHITMessager(EmailingHITMessager):

    def __init__(self, when, assignment_id, hit_duration, time_active, config):
        self.when = when,
        self.assignment_id = assignment_id,
        self.duration = round(hit_duration / 60),
        self.minutes_so_far = round(time_active / 60),
        self.minutes_excess = round((time_active - hit_duration) / 60)
        self.whimsical = config.get("whimsical")

    def _send(self, data):
        pass
