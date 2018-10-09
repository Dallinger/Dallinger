import user_agents
from functools import update_wrapper
from flask import make_response


def nocache(func):
    """Stop caching for pages wrapped in nocache decorator."""
    def new_func(*args, **kwargs):
        """No cache Wrapper."""
        resp = make_response(func(*args, **kwargs))
        resp.cache_control.no_cache = True
        return resp
    return update_wrapper(new_func, func)


class ValidatesBrowser(object):
    """Checks if participant's browser has been excluded via the Configuration.
    """
    def __init__(self, config):
        self.config = config

    @property
    def exclusions(self):
        """Return list of browser exclusion rules defined in the Configuration.
        """
        exclusion_rules = [
            r.strip() for r in self.config.get('browser_exclude_rule', '').split(',')
            if r.strip()
        ]
        return exclusion_rules

    def is_supported(self, user_agent_string):
        """Check user agent against configured exclusions.
        """
        user_agent_obj = user_agents.parse(user_agent_string)
        browser_ok = True
        for rule in self.exclusions:
            if rule in ["mobile", "tablet", "touchcapable", "pc", "bot"]:
                if (rule == "mobile" and user_agent_obj.is_mobile) or\
                   (rule == "tablet" and user_agent_obj.is_tablet) or\
                   (rule == "touchcapable" and user_agent_obj.is_touch_capable) or\
                   (rule == "pc" and user_agent_obj.is_pc) or\
                   (rule == "bot" and user_agent_obj.is_bot):
                    browser_ok = False
            elif rule in user_agent_string:
                browser_ok = False

        return browser_ok
