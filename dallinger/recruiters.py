"""Recruiters manage the flow of participants to the experiment."""

import logging
import os
import re

from rq import Queue
from sqlalchemy import func

from dallinger.config import get_config
from dallinger.db import session
from dallinger.heroku.worker import conn
from dallinger.models import Participant
from dallinger.models import Recruitment
from dallinger.mturk import MTurkService
from dallinger.mturk import DuplicateQualificationNameError
from dallinger.mturk import MTurkServiceException
from dallinger.mturk import QualificationNotFoundException
from dallinger.utils import get_base_url
from dallinger.utils import generate_random_id

logger = logging.getLogger(__file__)


def _get_queue():
    # Connect to Redis Queue
    return Queue('low', connection=conn)


# These are constants because other components may listen for these
# messages in logs:
NEW_RECRUIT_LOG_PREFIX = 'New participant requested:'
CLOSE_RECRUITMENT_LOG_PREFIX = 'Close recruitment.'


class Recruiter(object):
    """The base recruiter."""

    nickname = None
    external_submission_url = None  # MTurkRecruiter, for one, overides this

    def __init__(self):
        """For now, the contract of a Recruiter is that it takes no
        arguments.
        """
        pass

    def __call__(self):
        """For backward compatibility with experiments invoking recruiter()
        as a method rather than a property.
        """
        return self

    def open_recruitment(self, n=1):
        """Return a list of one or more initial recruitment URLs and an initial
        recruitment message:
        {
            items: [
                'https://experiment-url-1',
                'https://experiemnt-url-2'
            ],
            message: 'More info about this particular recruiter's process'
        }
        """
        raise NotImplementedError

    def recruit(self, n=1):
        raise NotImplementedError

    def close_recruitment(self):
        """Throw an error."""
        raise NotImplementedError

    def reward_bonus(self, assignment_id, amount, reason):
        """Throw an error."""
        raise NotImplementedError

    def notify_completed(self, participant):
        """Allow the Recruiter to be notified when a recruited Participant
        has completed an experiment they joined.
        """
        pass

    def rejects_questionnaire_from(self, participant):
        """Recruiters have different circumstances under which experiment
        questionnaires should be accepted or rejected.

        To reject a questionnaire, this method returns an error string.

        By default, they are accepted, so we return None.
        """
        return None

    def submitted_event(self):
        """Return the appropriate event type to trigger when
        an assignment is submitted. If no event should be processed,
        return None.
        """
        return 'AssignmentSubmitted'


class CLIRecruiter(Recruiter):
    """A recruiter which prints out /ad URLs to the console for direct
    assigment.
    """

    nickname = 'cli'

    def __init__(self):
        super(CLIRecruiter, self).__init__()
        self.config = get_config()

    def open_recruitment(self, n=1):
        """Return initial experiment URL list, plus instructions
        for finding subsequent recruitment events in experiemnt logs.
        """
        logger.info("Opening recruitment.")
        recruitments = self.recruit(n)
        message = (
            'Search for "{}" in the logs for subsequent recruitment URLs.\n'
            'Open the logs for this experiment with '
            '"dallinger logs --app {}"'.format(
                NEW_RECRUIT_LOG_PREFIX, self.config.get('id')
            )
        )
        return {
            'items': recruitments,
            'message': message
        }

    def recruit(self, n=1):
        """Generate experiemnt URLs and print them to the console."""
        urls = []
        template = "{}/ad?recruiter={}&assignmentId={}&hitId={}&workerId={}&mode={}"
        for i in range(n):
            ad_url = template.format(
                get_base_url(),
                self.nickname,
                generate_random_id(),
                generate_random_id(),
                generate_random_id(),
                self._get_mode()
            )
            logger.info('{} {}'.format(NEW_RECRUIT_LOG_PREFIX, ad_url))
            urls.append(ad_url)

        return urls

    def close_recruitment(self):
        """Talk about closing recruitment."""
        logger.info(CLOSE_RECRUITMENT_LOG_PREFIX)

    def approve_hit(self, assignment_id):
        """Approve the HIT."""
        logger.info(
            "Assignment {} has been marked for approval".format(assignment_id)
        )
        return True

    def reward_bonus(self, assignment_id, amount, reason):
        """Print out bonus info for the assignment"""
        logger.info(
            'Award ${} for assignment {}, with reason "{}"'.format(
                amount, assignment_id, reason)
        )

    def _get_mode(self):
        return self.config.get('mode')


class HotAirRecruiter(CLIRecruiter):
    """A dummy recruiter: talks the talk, but does not walk the walk.

    - Always invokes templates in debug mode
    - Prints experiment /ad URLs to the console
    """

    nickname = 'hotair'

    def open_recruitment(self, n=1):
        """Return initial experiment URL list, plus instructions
        for finding subsequent recruitment events in experiemnt logs.
        """
        logger.info("Opening recruitment.")
        recruitments = self.recruit(n)
        message = "Recruitment requests will open browser windows automatically."

        return {
            'items': recruitments,
            'message': message
        }

    def reward_bonus(self, assignment_id, amount, reason):
        """Logging-only, Hot Air implementation"""
        logger.info(
            "Were this a real Recruiter, we'd be awarding ${} for assignment {}, "
            'with reason "{}"'.format(amount, assignment_id, reason)
        )

    def _get_mode(self):
        # Ignore config settings and always use debug mode
        return 'debug'


class SimulatedRecruiter(Recruiter):
    """A recruiter that recruits simulated participants."""

    nickname = 'sim'

    def open_recruitment(self, n=1):
        """Open recruitment."""
        return {
            'items': self.recruit(n),
            'message': 'Simulated recruitment only'
        }

    def recruit(self, n=1):
        """Recruit n participants."""
        return []

    def close_recruitment(self):
        """Do nothing."""
        pass


class MTurkRecruiterException(Exception):
    """Custom exception for MTurkRecruiter"""


class MTurkRecruiter(Recruiter):
    """Recruit participants from Amazon Mechanical Turk.
    If fewer than 9 assignments are made initially, recruitment stops after 9
    calls to recruit()"""

    nickname = 'mturk'

    experiment_qualification_desc = 'Experiment-specific qualification'
    group_qualification_desc = 'Experiment group qualification'

    def __init__(self):
        super(MTurkRecruiter, self).__init__()
        self.config = get_config()
        self.ad_url = '{}/ad?recruiter={}'.format(
            get_base_url(),
            self.nickname,
        )
        self.hit_domain = os.getenv('HOST')
        self.mturkservice = MTurkService(
            self.config.get('aws_access_key_id'),
            self.config.get('aws_secret_access_key'),
            self.config.get('aws_region'),
            self.config.get('mode') != "live"
        )
        self._validate_config()

    def _validate_config(self):
        mode = self.config.get('mode')
        if mode not in ('sandbox', 'live'):
            raise MTurkRecruiterException(
                '"{}" is not a valid mode for MTurk recruitment. '
                'The value of "mode" must be either "sandbox" or "live"'.format(mode)
            )

    @property
    def external_submission_url(self):
        """On experiment completion, participants are returned to
        the Mechanical Turk site to submit their HIT, which in turn triggers
        notifications to the /notifications route.
        """
        if self.config.get('mode') == "sandbox":
            return "https://workersandbox.mturk.com/mturk/externalSubmit"
        return "https://www.mturk.com/mturk/externalSubmit"

    @property
    def qualifications(self):
        quals = {self.config.get('id'): self.experiment_qualification_desc}
        group_name = self.config.get('group_name', None)
        if group_name:
            quals[group_name] = self.group_qualification_desc

        return quals

    def open_recruitment(self, n=1):
        """Open a connection to AWS MTurk and create a HIT."""
        if self.is_in_progress:
            # Already started... do nothing.
            return None

        if self.hit_domain is None:
            raise MTurkRecruiterException("Can't run a HIT from localhost")

        self.mturkservice.check_credentials()

        if self.config.get('assign_qualifications'):
            self._create_mturk_qualifications()

        hit_request = {
            'max_assignments': n,
            'title': self.config.get('title'),
            'description': self.config.get('description'),
            'keywords': self._config_to_list('keywords'),
            'reward': self.config.get('base_payment'),
            'duration_hours': self.config.get('duration'),
            'lifetime_days': self.config.get('lifetime'),
            'ad_url': self.ad_url,
            'notification_url': self.config.get('notification_url'),
            'approve_requirement': self.config.get('approve_requirement'),
            'us_only': self.config.get('us_only'),
            'blacklist': self._config_to_list('qualification_blacklist'),
            'annotation': self.config.get('id'),
        }
        hit_info = self.mturkservice.create_hit(**hit_request)
        if self.config.get('mode') == "sandbox":
            lookup_url = "https://workersandbox.mturk.com/mturk/preview?groupId={type_id}"
        else:
            lookup_url = "https://worker.mturk.com/mturk/preview?groupId={type_id}"

        return {
            'items': [lookup_url.format(**hit_info), ],
            'message': 'HIT now published to Amazon Mechanical Turk'
        }

    def recruit(self, n=1):
        """Recruit n new participants to an existing HIT"""
        if not self.config.get('auto_recruit', False):
            logger.info('auto_recruit is False: recruitment suppressed')
            return

        hit_id = self.current_hit_id()
        if hit_id is None:
            logger.info('no HIT in progress: recruitment aborted')
            return

        try:
            return self.mturkservice.extend_hit(
                hit_id,
                number=n,
                duration_hours=self.config.get('duration')
            )
        except MTurkServiceException as ex:
            logger.exception(str(ex))

    def notify_completed(self, participant):
        """Assign a Qualification to the Participant for the experiment ID,
        and for the configured group_name, if it's been set.

        Overrecruited participants don't receive qualifications, since they
        haven't actually completed the experiment. This allows them to remain
        eligible for future runs.
        """
        if participant.status == 'overrecruited' or not self.qualification_active:
            return

        worker_id = participant.worker_id

        for name in self.qualifications:
            try:
                self.mturkservice.increment_qualification_score(
                    name, worker_id
                )
            except QualificationNotFoundException as ex:
                logger.exception(ex)

    def rejects_questionnaire_from(self, participant):
        """Mechanical Turk participants submit their HITs on the MTurk site
        (see external_submission_url), and MTurk then sends a notification
        to Dallinger which is used to mark the assignment completed.

        If a HIT has already been submitted, it's too late to submit the
        questionnaire.
        """
        if participant.status != "working":
            return (
                "This participant has already sumbitted their HIT "
                "on MTurk and can no longer submit the questionnaire"
            )

    def submitted_event(self):
        """MTurk will send its own notification when the worker
        completes the HIT on that service.
        """
        return None

    def reward_bonus(self, assignment_id, amount, reason):
        """Reward the Turker for a specified assignment with a bonus."""
        try:
            return self.mturkservice.grant_bonus(assignment_id, amount, reason)
        except MTurkServiceException as ex:
            logger.exception(str(ex))

    @property
    def is_in_progress(self):
        return bool(Participant.query.first())

    @property
    def qualification_active(self):
        return bool(self.config.get('assign_qualifications', False))

    def current_hit_id(self):
        any_participant_record = Participant.query.with_entities(
            Participant.hit_id).first()

        if any_participant_record is not None:
            return str(any_participant_record.hit_id)

    def approve_hit(self, assignment_id):
        try:
            return self.mturkservice.approve_assignment(assignment_id)
        except MTurkServiceException as ex:
            logger.exception(str(ex))

    def close_recruitment(self):
        """Clean up once the experiment is complete.

        This may be called before all users have finished so uses the
        expire_hit rather than the disable_hit API call. This allows people
        who have already picked up the hit to complete it as normal.
        """
        logger.info(CLOSE_RECRUITMENT_LOG_PREFIX)
        # We are not expiring the hit currently as notifications are failing
        # TODO: Reinstate this
        # try:
        #     return self.mturkservice.expire_hit(
        #         self.current_hit_id(),
        #     )
        # except MTurkServiceException as ex:
        #     logger.exception(str(ex))

    def _config_to_list(self, key):
        # At some point we'll support lists, so all service code supports them,
        # but the config system only supports strings for now, so we convert:
        as_string = self.config.get(key, '')
        return [item.strip() for item in as_string.split(',') if item.strip()]

    def _create_mturk_qualifications(self):
        """Create MTurk Qualification for experiment ID, and for group_name
        if it's been set. Qualifications with these names already exist, but
        it's faster to try and fail than to check, then try.
        """
        for name, desc in self.qualifications.items():
            try:
                self.mturkservice.create_qualification_type(name, desc)
            except DuplicateQualificationNameError:
                pass


# TODO: expiring HITs on shutdown becomes more complicated here
# because we have to go back and find all the HITs that have been
# created. One solution could be to expire the last HIT when creating
# a new one, but then we would have to require n=1 recruitments, which
# places a constraint on what experimental designs can be used.  E.g.,
# might want multiple participants will different HITs going in
# parallel
class MTurkRobustRecruiter(MTurkRecruiter):
    """Accommodates more than 9 calls to recruit() without forcing
    a large initial recruitment and avoiding higher fees"""


    def recruit(self, n=1):

        if not self.config.get('auto_recruit', False):
            logger.info('auto_recruit is False: recruitment suppressed')
            return

        hit_id = self.current_hit_id()
        if hit_id is None:
            logger.info('no HIT in progress: recruitment aborted')
            return

        hit_request = {
            'max_assignments': n,
            'title': self.config.get('title'),
            'description': self.config.get('description'),
            'keywords': self._config_to_list('keywords'),
            'reward': self.config.get('base_payment'),
            'duration_hours': self.config.get('duration'),
            'lifetime_days': self.config.get('lifetime'),
            'ad_url': self.ad_url,
            'notification_url': self.config.get('notification_url'),
            'approve_requirement': self.co>nfig.get('approve_requirement'),
            'us_only': self.config.get('us_only'),
            'blacklist': self._config_to_list('qualification_blacklist'),
        }
        try:
            self.mturkservice.create_hit(**hit_request)
        except MTurkServiceException as ex:
            logger.exception(ex.message)


class MTurkLargeRecruiter(MTurkRecruiter):

    nickname = 'mturklarge'

    def __init__(self, *args, **kwargs):
        conn.set('num_recruited', 0)
        super(MTurkLargeRecruiter, self).__init__(*args, **kwargs)

    def open_recruitment(self, n=1):
        if self.is_in_progress:
            # Already started... do nothing.
            return None
        conn.incr('num_recruited', n)
        to_recruit = max(n, 10)
        return super(MTurkLargeRecruiter, self).open_recruitment(to_recruit)

    def recruit(self, n=1):
        if not self.config.get('auto_recruit', False):
            logger.info('auto_recruit is False: recruitment suppressed')
            return
        to_recruit = n
        if int(conn.get('num_recruited')) < 10:
            num_recruited = conn.incr('num_recruited', n)
            logger.info('Recruited participant from preallocated pool')
            if num_recruited > 10:
                to_recruit = num_recruited - 10
            else:
                to_recruit = 0
        else:
            conn.incr('num_recruited', n)
        if to_recruit:
            return super(MTurkLargeRecruiter, self).recruit(to_recruit)


class BotRecruiter(Recruiter):
    """Recruit bot participants using a queue"""

    nickname = 'bots'

    def __init__(self):
        super(BotRecruiter, self).__init__()
        self.config = get_config()
        logger.info("Initialized BotRecruiter.")

    def open_recruitment(self, n=1):
        """Start recruiting right away."""
        logger.info("Open recruitment.")
        factory = self._get_bot_factory()
        bot_class_name = factory('', '', '').__class__.__name__
        return {
            'items': self.recruit(n),
            'message': 'Bot recruitment started using {}'.format(bot_class_name)
        }

    def recruit(self, n=1):
        """Recruit n new participant bots to the queue"""
        factory = self._get_bot_factory()
        urls = []
        q = _get_queue()
        for _ in range(n):
            base_url = get_base_url()
            worker = generate_random_id()
            hit = generate_random_id()
            assignment = generate_random_id()
            ad_parameters = 'recruiter=bots&assignmentId={}&hitId={}&workerId={}&mode=sandbox'
            ad_parameters = ad_parameters.format(assignment, hit, worker)
            url = '{}/ad?{}'.format(base_url, ad_parameters)
            urls.append(url)
            bot = factory(url, assignment_id=assignment, worker_id=worker, hit_id=hit)
            job = q.enqueue(bot.run_experiment, timeout=60 * 20)
            logger.warn("Created job {} for url {}.".format(job.id, url))

        return urls

    def approve_hit(self, assignment_id):
        return True

    def close_recruitment(self):
        """Clean up once the experiment is complete.

        This does nothing at this time.
        """
        logger.info(CLOSE_RECRUITMENT_LOG_PREFIX)

    def reward_bonus(self, assignment_id, amount, reason):
        """Logging only. These are bots."""
        logger.info(
            "Bots don't get bonuses. Sorry, bots."
        )

    def submitted_event(self):
        return 'BotAssignmentSubmitted'

    def _get_bot_factory(self):
        # Must be imported at run-time
        from dallinger_experiment.experiment import Bot
        return Bot


class MultiRecruiter(Recruiter):

    nickname = 'multi'

    # recruiter spec e.g. recruiters = bots: 5, mturk: 1
    SPEC_RE = re.compile(r'(\w+):\s*(\d+)')

    def __init__(self):
        self.spec = self.parse_spec()

    def parse_spec(self):
        """Parse the specification of how to recruit participants.

        Example: recruiters = bots: 5, mturk: 1
        """
        recruiters = []
        spec = get_config().get('recruiters')
        for match in self.SPEC_RE.finditer(spec):
            name = match.group(1)
            count = int(match.group(2))
            recruiters.append((name, count))
        return recruiters

    def pick_recruiter(self):
        """Pick the next recruiter to use.

        We use the `Recruitment` table in the db to keep track of
        how many recruitments have been requested using each recruiter.
        We'll use the first one from the specification that
        hasn't already reached its quota.
        """
        counts = dict(
            session.query(
                Recruitment.recruiter_id,
                func.count(Recruitment.id)
            ).group_by(Recruitment.recruiter_id).all()
        )

        for recruiter_id, target_count in self.spec:
            count = counts.get(recruiter_id, 0)
            if count >= target_count:
                # This recruiter quota was reached;
                # move on to the next one.
                counts[recruiter_id] = count - target_count
                continue
            else:
                # Quota is still available; let's use it.
                break
        else:
            raise Exception(
                'Reached quota for all recruiters. '
                'Not sure which one to use now.'
            )

        # record the recruitment
        session.add(Recruitment(recruiter_id=recruiter_id))

        # return an instance of the recruiter
        return by_name(recruiter_id)

    def open_recruitment(self, n=1):
        """Return initial experiment URL list.
        """
        logger.info("Opening recruitment.")
        recruitments = []
        messages = {}
        for i in range(n):
            recruiter = self.pick_recruiter()
            if recruiter.nickname in messages:
                result = recruiter.recruit(1)
                recruitments.extend(result)
            else:
                result = recruiter.open_recruitment(1)
                recruitments.extend(result['items'])
                messages[recruiter.nickname] = result['message']
        return {
            'items': recruitments,
            'message': '\n'.join(messages.values())
        }

    def recruit(self, n=1):
        urls = []
        for i in range(n):
            recruiter = self.pick_recruiter()
            urls.extend(recruiter.recruit(1))
        return urls

    def close_recruitment(self):
        for name in set(name for name, count in self.spec):
            recruiter = by_name(name)
            recruiter.close_recruitment()


def for_experiment(experiment):
    """Return the Recruiter instance for the specified Experiment.

    This provides a seam for testing.
    """
    return experiment.recruiter


def from_config(config):
    """Return a Recruiter instance based on the configuration.

    Default is HotAirRecruiter in debug mode (unless we're using
    the bot recruiter, which can be used in debug mode)
    and the MTurkRecruiter in other modes.
    """
    debug_mode = config.get('mode', None) == 'debug'
    name = config.get('recruiter', None)
    recruiter = None

    # Special case 1: Don't use a configured recruiter in replay mode
    if config.get('replay', None):
        return HotAirRecruiter()

    if name is not None:
        recruiter = by_name(name)

        # Special case 2: may run BotRecruiter or MultiRecruiter in any mode
        # (debug or not), so it trumps everything else:
        if isinstance(recruiter, (BotRecruiter, MultiRecruiter)):
            return recruiter

    # Special case 3: if we're not using bots and we're in debug mode,
    # ignore any configured recruiter:
    if debug_mode:
        return HotAirRecruiter()

    # Configured recruiter:
    if recruiter is not None:
        return recruiter

    if name and recruiter is None:
        raise NotImplementedError("No such recruiter {}".format(name))

    # Default if we're not in debug mode:
    return MTurkRecruiter()


def _descendent_classes(cls):
    for cls in cls.__subclasses__():
        yield cls
        for cls in _descendent_classes(cls):
            yield cls


BY_NAME = {}
for cls in _descendent_classes(Recruiter):
    BY_NAME[cls.__name__] = BY_NAME[cls.nickname] = cls


def by_name(name):
    """Attempt to return a recruiter class by name.

    Actual class names and known nicknames are both supported.
    """
    klass = BY_NAME.get(name)
    if klass is not None:
        return klass()
