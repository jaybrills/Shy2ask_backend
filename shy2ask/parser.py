import json
from typing import cast

from django.http import HttpRequest

from ninja.parser import Parser
from ninja.types import DictStrAny


class FlexibleParser(Parser):
    """
    Accept JSON bodies and classic form bodies for schema-based payloads.
    This avoids 400 parse errors when clients send multipart/form-data to
    endpoints that otherwise expect JSON.
    """

    def parse_body(self, request: HttpRequest) -> DictStrAny:
        content_type = (request.content_type or "").split(";")[0].strip().lower()

        if content_type in ("multipart/form-data", "application/x-www-form-urlencoded"):
            parsed: DictStrAny = {}
            for key in request.POST.keys():
                values = request.POST.getlist(key)
                parsed[key] = values if len(values) > 1 else values[0]
            return parsed

        return cast(DictStrAny, json.loads(request.body))
