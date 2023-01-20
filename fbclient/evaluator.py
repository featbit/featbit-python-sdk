import json
import re
from typing import Callable, Optional

from fbclient.common_types import FBEvent, FBUser, _EvalResult
from fbclient.event_types import FlagEventVariation
from fbclient.utils import is_numeric, log
from fbclient.utils.variation_splitting_algorithm import \
    VariationSplittingAlgorithm

REASON_CLIENT_NOT_READY = 'client not ready'

REASON_FLAG_NOT_FOUND = 'flag not found'

REASON_ERROR = 'error in evaluation'

REASON_USER_NOT_SPECIFIED = 'user not specified'

REASON_WRONG_TYPE = 'wrong type'

REASON_FLAG_OFF = 'flag off'

REASON_PREREQUISITE_FAILED = 'prerequisite failed'

REASON_TARGET_MATCH = 'target match'

REASON_RULE_MATCH = 'rule match'

REASON_FALLTHROUGH = 'fall through all rules'

__THAN_CLAUSE__ = 'Than'

__GE_CLAUSE__ = 'BiggerEqualThan'

__GT_CLAUSE__ = 'BiggerThan'

__LE_CLAUSE__ = 'LessEqualThan'

__LT_CLAUSE__ = 'LessThan'

__EQ_CLAUSE__ = 'Equal'

__NEQ_CLAUSE__ = 'NotEqual'

__CONTAINS_CLAUSE__ = 'Contains'

__NOT_CONTAIN_CLAUSE__ = 'NotContain'

__IS_ONE_OF_CLAUSE__ = 'IsOneOf'

__NOT_ONE_OF_CLAUSE__ = 'NotOneOf'

__STARTS_WITH_CLAUSE__ = 'StartsWith'

__ENDS_WITH_CLAUSE__ = 'EndsWith'

__IS_TRUE_CLAUSE__ = 'IsTrue'

__IS_FALSE_CLAUSE__ = 'IsFalse'

__MATCH_REGEX_CLAUSE__ = 'MatchRegex'

__NOT_MATCH_REGEX_CLAUSE__ = 'NotMatchRegex'

__IS_IN_SEGMENT_CLAUSE__ = 'User is in segment'

__NOT_IN_SEGMENT_CLAUSE__ = 'User is not in segment'

__EXPT_KEY_PREFIX__ = "expt"


class Evaluator:
    def __init__(self,
                 flag_getter: Callable[[str], Optional[dict]],
                 segment_getter: Callable[[str], Optional[dict]]):
        self.__flag_getter = flag_getter
        self.__segment_getter = segment_getter
        self.__ops = [self._match_feature_flag_disabled_user_variation,
                      self._match_targeted_user_variation,
                      self._match_condition_user_variation,
                      self._match_default_user_variation]

    def evaluate(self, flag: dict, user: FBUser, fb_event: Optional[FBEvent] = None) -> _EvalResult:
        if not flag or not user:
            raise ValueError('null flag or empty user')
        return self._match_user_variation(flag, user, fb_event)  # type: ignore

    def _match_user_variation(self, flag: dict, user: FBUser, fb_event: Optional[FBEvent] = None) -> Optional[_EvalResult]:
        er = None
        try:
            for op in self.__ops:
                er = op(flag, user)
                if er is not None:
                    return er
        finally:
            if er is not None:
                log.info('FB Python SDK: User %s, Feature Flag %s, Flag Value %s' % (user.get('KeyId'), er.key_name, er.value))
                if fb_event is not None:
                    fb_event.add(FlagEventVariation(er))

    #  return a value when flag is off
    def _match_feature_flag_disabled_user_variation(self, flag: dict, user: FBUser) -> Optional[_EvalResult]:
        if not flag['isEnabled']:
            return _EvalResult(flag['disabledVariationId'],
                               flag['variationMap'][flag['disabledVariationId']],
                               REASON_FLAG_OFF,
                               False,
                               flag['key'],
                               flag['name'],
                               flag['variationType'])
        return None

    # return the value of target user
    def _match_targeted_user_variation(self, flag: dict, user: FBUser) -> Optional[_EvalResult]:
        for target in flag['targetUsers']:
            if any(key_id == user.get('keyid') for key_id in target['keyIds']):
                return _EvalResult(target['variationId'],
                                   flag['variationMap'][target['variationId']],
                                   REASON_TARGET_MATCH,
                                   flag['exptIncludeAllTargets'],
                                   flag['key'],
                                   flag['name'],
                                   flag['variationType'])
        return None

    # return the value of matched rule
    def _match_condition_user_variation(self, flag: dict, user: FBUser) -> Optional[_EvalResult]:
        for rule in flag['rules']:
            if self._match_any_rule(user, rule):
                return self._get_rollout_variation_option(flag,
                                                          rule,
                                                          user,
                                                          REASON_RULE_MATCH,
                                                          flag['key'],
                                                          flag['name'])
        return None

    # get value from default rule
    def _match_default_user_variation(self, flag: dict, user: FBUser) -> Optional[_EvalResult]:
        return self._get_rollout_variation_option(flag,
                                                  flag['fallthrough'],
                                                  user,
                                                  REASON_FALLTHROUGH,
                                                  flag['key'],
                                                  flag['name'])

    def _match_any_rule(self, user: FBUser, rule: dict) -> bool:
        # conditions cannot be empty
        return all(self._process_condition(user, condiction) for condiction in rule['conditions'])

    def _process_condition(self, user: FBUser, condition: dict) -> bool:
        op = condition['op']
        # segment hasn't any operation
        op = condition['property'] if not op else op
        if __THAN_CLAUSE__ in str(op):
            return self._than(user, condition)
        elif op == __EQ_CLAUSE__:
            return self._equals(user, condition)
        elif op == __NEQ_CLAUSE__:
            return not self._equals(user, condition)
        elif op == __CONTAINS_CLAUSE__:
            return self._contains(user, condition)
        elif op == __NOT_CONTAIN_CLAUSE__:
            return not self._contains(user, condition)
        elif op == __IS_ONE_OF_CLAUSE__:
            return self._one_of(user, condition)
        elif op == __NOT_ONE_OF_CLAUSE__:
            return not self._one_of(user, condition)
        elif op == __STARTS_WITH_CLAUSE__:
            return self._starts_with(user, condition)
        elif op == __ENDS_WITH_CLAUSE__:
            return self._ends_with(user, condition)
        elif op == __IS_TRUE_CLAUSE__:
            return self._true(user, condition)
        elif op == __IS_FALSE_CLAUSE__:
            return self._false(user, condition)
        elif op == __MATCH_REGEX_CLAUSE__:
            return self._match_reg_exp(user, condition)
        elif op == __NOT_MATCH_REGEX_CLAUSE__:
            return not self._match_reg_exp(user, condition)
        elif op == __IS_IN_SEGMENT_CLAUSE__:
            return self._in_segment(user, condition)
        elif op == __NOT_IN_SEGMENT_CLAUSE__:
            return not self._in_segment(user, condition)
        else:
            return False

    def _than(self, user: FBUser, condition: dict) -> bool:
        pv = user.get(condition['property'])
        if not is_numeric(pv) or not is_numeric(condition['value']):
            return False
        pv_num, cv_num = round(float(pv), 5), round(float(condition['value']), 5)  # type: ignore
        op = condition['op']
        if op == __GE_CLAUSE__:
            return pv_num >= cv_num
        elif op == __GT_CLAUSE__:
            return pv_num > cv_num
        elif op == __LE_CLAUSE__:
            return pv_num <= cv_num
        elif op == __LT_CLAUSE__:
            return pv_num < cv_num
        else:
            return False

    def _equals(self, user: FBUser, condition: dict) -> bool:
        pv = user.get(condition['property'])
        cv = condition['value']
        return pv is not None and cv is not None and str(pv) == str(cv)

    def _contains(self, user: FBUser, condition: dict) -> bool:
        pv = user.get(condition['property'])
        cv = condition['value']
        return pv is not None and cv is not None and str(cv) in str(pv)

    def _one_of(self, user: FBUser, condition: dict) -> bool:
        pv = user.get(condition['property'])
        try:
            cv = json.loads(condition['value'])
            return pv is not None and cv is not None and str(pv) in cv
        except:
            return False

    def _starts_with(self, user: FBUser, condition: dict) -> bool:
        pv = user.get(condition['property'])
        cv = condition['value']
        return pv is not None and cv is not None and str(pv).startswith(str(cv))

    def _ends_with(self, user: FBUser, condition: dict) -> bool:
        pv = user.get(condition['property'])
        cv = condition['value']
        return pv is not None and cv is not None and str(pv).endswith(str(cv))

    def _true(self, user: FBUser, condition: dict) -> bool:
        pv = user.get(condition['property'])
        return pv is not None and str(pv).lower() == 'true'

    def _false(self, user: FBUser, condition: dict) -> bool:
        pv = user.get(condition['property'])
        return pv is not None and str(pv).lower() == 'false'

    def _match_reg_exp(self, user: FBUser, clause: dict) -> bool:
        pv = user.get(clause['property'])
        cv = clause['value']
        return pv is not None and cv is not None and re.search(str(cv), str(pv)) is not None

    def _in_segment(self, user: FBUser, condition: dict) -> bool:
        def match_segment(user: FBUser, segment: Optional[dict]) -> bool:
            if not user or not segment:
                return False
            user_key = user.get('keyid')
            if user_key in segment['excluded']:
                return False
            if user_key in segment['included']:
                return True
            return any(self._match_any_rule(user, rule) for rule in segment['rules'])
        try:
            cv = json.loads(condition['value'])
            return cv and any(match_segment(user, self.__segment_getter(sgid)) for sgid in cv)
        except:
            return False

    def _get_rollout_variation_option(self,
                                      flag: dict,
                                      rollout_variations: dict,
                                      user: FBUser,
                                      reason: str,
                                      key_name: str,
                                      name: str) -> Optional[_EvalResult]:

        def is_send_to_expt(dispatch_key: str,
                            rollout: dict,
                            expt_include_all_targets: bool,
                            rule_inclued_in_expt: bool) -> bool:
            if expt_include_all_targets:
                return True
            if rule_inclued_in_expt:
                send_to_expt_percentage = rollout['exptRollout']
                splitting_percentage = rollout['rollout'][1] - rollout['rollout'][0]

                if send_to_expt_percentage == 0 or splitting_percentage == 0:
                    return False

                upper_bound = send_to_expt_percentage / splitting_percentage
                if upper_bound > 1:
                    upper_bound = 1
                new_dispatch_key = "".join((__EXPT_KEY_PREFIX__, dispatch_key))
                return VariationSplittingAlgorithm(new_dispatch_key, [0, upper_bound]).is_key_belongs_to_percentage()
            return False

        dispatch_key = rollout_variations.get('dispatchKey')
        dispatch_key = dispatch_key if dispatch_key else 'keyid'
        dispatch_key_value = "".join((flag['key'], user.get(dispatch_key, "")))  # type: ignore
        for rollout in rollout_variations['variations']:
            if VariationSplittingAlgorithm(dispatch_key_value, rollout['rollout']).is_key_belongs_to_percentage():  # type: ignore
                send_to_expt = is_send_to_expt(dispatch_key_value, rollout, flag['exptIncludeAllTargets'], rollout_variations['includedInExpt'])  # type: ignore
                return _EvalResult(rollout['id'],
                                   flag['variationMap'][rollout['id']],
                                   reason,
                                   send_to_expt,
                                   key_name,
                                   name,
                                   flag['variationType'])
        return None
