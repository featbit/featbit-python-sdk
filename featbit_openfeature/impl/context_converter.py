import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from openfeature.evaluation_context import EvaluationContext
from openfeature.exception import TargetingKeyMissingError


logger = logging.getLogger("featbit-openfeature-server")

_RESERVED_ATTRIBUTES = {"key", "keyid", "targetingKey", "name"}
_UNSUPPORTED_ATTRIBUTE = object()


class EvaluationContextConverter:
    """Convert an OpenFeature evaluation context to a FeatBit user mapping."""

    def to_fb_user(self, context: Optional[EvaluationContext]) -> Dict[str, Any]:
        if context is None:
            raise TargetingKeyMissingError("evaluation context is required")

        attributes = dict(context.attributes)
        targeting_key = self._targeting_key(context, attributes)
        name = attributes.get("name")
        if not self._is_non_empty_string(name):
            if name is not None:
                logger.warning(
                    "FeatBit user name must be a non-empty string; using targeting key"
                )
            name = targeting_key

        user = {"key": targeting_key, "name": name}
        for key, value in attributes.items():
            if not isinstance(key, str) or key in _RESERVED_ATTRIBUTES:
                continue

            converted = self._convert_attribute(value)
            if converted is _UNSUPPORTED_ATTRIBUTE:
                logger.debug(
                    "Ignoring unsupported structured EvaluationContext attribute %r",
                    key,
                )
                continue
            user[key] = converted

        return user

    @classmethod
    def _targeting_key(
        cls, context: EvaluationContext, attributes: Dict[str, Any]
    ) -> str:
        if cls._is_non_empty_string(context.targeting_key):
            return context.targeting_key

        attribute_key = attributes.get("key")
        if cls._is_non_empty_string(attribute_key):
            return attribute_key

        raise TargetingKeyMissingError(
            "evaluation context must contain a non-empty targeting key"
        )

    @staticmethod
    def _is_non_empty_string(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _convert_attribute(value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        if isinstance(value, (str, bool, int, float)):
            return value
        return _UNSUPPORTED_ATTRIBUTE
