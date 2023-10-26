class MTurkQuestions(object):
    """Creates MTurk HIT Question definitions:
    https://docs.aws.amazon.com/AWSMechTurk/latest/AWSMturkAPI/ApiReference_QuestionAnswerDataArticle.html
    """

    @staticmethod
    def external(ad_url, frame_height=600):
        q = (
            '<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/'
            'AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">'
            "<ExternalURL>{}</ExternalURL>"
            "<FrameHeight>{}</FrameHeight></ExternalQuestion>"
        )
        return q.format(ad_url, frame_height)

    @staticmethod
    def compensation(title="Compensation HIT", sandbox=False, frame_height=600):
        if sandbox:
            action = "https://workersandbox.mturk.com/mturk/externalSubmit"
        else:
            action = "https://www.mturk.com/mturk/externalSubmit"

        q = (
            '<HTMLQuestion xmlns="http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2011-11-11/HTMLQuestion.xsd">'
            "<HTMLContent><![CDATA[<!DOCTYPE html><html>"
            "<head>"
            '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/>'
            '<script type="text/javascript" src="https://s3.amazonaws.com/mturk-public/externalHIT_v1.js"></script>'
            "</head>"
            "<body>"
            '<form name="mturk_form" method="post" id="mturk_form" action="{}">'
            '<input type="hidden" value="" name="assignmentId" id="assignmentId"/>'
            "<h1>{}</h1>"
            "<p>We are sorry that you encountered difficulties with our experiment. "
            "We will compensate you immediately upon submission of this HIT.</p>"
            '<input type="hidden" name="some-input-required" value="anything" ></input>'
            '<input type="submit" id="submitButton" value="Submit" /></p></form>'
            '<script language="Javascript">turkSetAssignmentID();</script>'
            "</body></html>]]>"
            "</HTMLContent>"
            "<FrameHeight>{}</FrameHeight>"
            "</HTMLQuestion>"
        )

        return q.format(action, title, frame_height)


mturk_resubmit_whimsical = """Dearest Friend,

I am writing to let you know that at {s.when}, during my regular (and thoroughly
enjoyable) perousal of the most charming participant data table, I happened to
notice that assignment {s.assignment_id} has been taking longer than we were
expecting. I recall you had suggested {s.allowed_minutes:.0f} minutes as an upper
limit for what was an acceptable length of time for each assignement, however
this assignment had been underway for a shocking {s.active_minutes:.0f} minutes, a
full {s.excess_minutes:.0f} minutes over your allowance. I immediately dispatched a
telegram to our mutual friends at AWS and they were able to assure me that
although the notification had failed to be correctly processed, the assignment
had in fact been completed. Rather than trouble you, I dealt with this myself
and I can assure you there is no immediate cause for concern. Nonetheless, for
my own peace of mind, I would appreciate you taking the time to look into this
matter at your earliest convenience.

I remain your faithful and obedient servant,

William H. Dallinger

P.S. Please do not respond to this message, I am busy with other matters.
"""


mturk_resubmit = """Dear experimenter,

This is an automated email from Dallinger. You are receiving this email because
the Dallinger platform has discovered evidence that a notification from Amazon
Web Services failed to arrive at the server. Dallinger has automatically
contacted AWS and has determined the dropped notification was a submitted
notification (i.e. the participant has finished the experiment). This is a non-
fatal error and so Dallinger has auto-corrected the problem. Nonetheless you may
wish to check the database.

Best,
The Dallinger dev. team.

Error details:
Assignment: {s.assignment_id}
Allowed time: {s.allowed_minutes:.0f} minute(s)
Time since participant started: {s.active_minutes:.0f}
"""


mturk_cancelled_hit_whimsical = """Dearest Friend,

I am afraid I write to you with most grave tidings. At {s.when}, during a
routine check of the usually most delightful participant data table, I happened
to notice that assignment {s.assignment_id} has been taking longer than we were
expecting. I recall you had suggested {s.allowed_minutes:.0f} minutes as an upper
limit for what was an acceptable length of time for each assignment, however
this assignment had been underway for a shocking {s.active_minutes:.0f} minutes, a
full {s.excess_minutes:.0f} minutes over your allowance. I immediately dispatched a
telegram to our mutual friends at AWS and they infact informed me that they had
already sent us a notification which we must have failed to process, implying
that the assignment had not been successfully completed. Of course when the
seriousness of this scenario dawned on me I had to depend on my trusting walking
stick for support: without the notification I didn't know to remove the old
assignment's data from the tables and AWS will have already sent their
replacement, meaning that the tables may already be in a most unsound state!

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

cancelled_hit = """Dear experimenter,

This is an automated email from Dallinger. You are receiving this email because
the Dallinger platform has discovered evidence that a notification from Amazon
Web Services failed to arrive at the server. Dallinger has automatically
contacted AWS and has determined the dropped notification was an
abandoned/returned notification (i.e. the participant had returned the
experiment or had run out of time). This is a serious error and so Dallinger has
paused the experiment - expiring the HIT on MTurk and setting auto_recruit to
false. Participants currently playing will be able to finish, however no further
participants will be recruited until you do so manually. We strongly suggest you
use the details below to check the database to make sure the missing
notification has not caused additional problems before resuming. If you are
receiving a lot of these emails this suggests something is wrong with your
experiment code.

Best,

The Dallinger dev. team.

Error details:
Assignment: {s.assignment_id}

Allowed time (minutes): {s.allowed_minutes:.0f}
Time since participant started: {s.active_minutes:.0f}
"""


class MTurkHITMessages(object):
    @staticmethod
    def by_flavor(summary, whimsical):
        if whimsical:
            return WhimsicalMTurkHITMessages(summary)
        return MTurkHITMessages(summary)

    _templates = {
        "resubmitted": {
            "subject": "Dallinger automated email - minor error.",
            "template": mturk_resubmit,
        },
        "cancelled": {
            "subject": "Dallinger automated email - major error.",
            "template": cancelled_hit,
        },
    }

    def __init__(self, summary):
        self.summary = summary

    def resubmitted_msg(self):
        return self._build("resubmitted")

    def hit_cancelled_msg(self):
        return self._build("cancelled")

    def _build(self, category):
        data = self._templates[category]
        return {
            "body": data["template"].format(s=self.summary),
            "subject": data["subject"],
        }


class WhimsicalMTurkHITMessages(MTurkHITMessages):
    _templates = {
        "resubmitted": {
            "subject": "A matter of minor concern.",
            "template": mturk_resubmit_whimsical,
        },
        "cancelled": {
            "subject": "Most troubling news.",
            "template": mturk_cancelled_hit_whimsical,
        },
    }
