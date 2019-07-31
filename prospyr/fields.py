# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from functools import wraps
import datetime
import arrow
from arrow.parser import ParserError
from marshmallow import ValidationError, fields
from marshmallow.utils import missing as missing_
from requests import codes

from prospyr import exceptions
from prospyr.util import encode_typename, import_dotted_path
from prospyr.validate import WhitespaceEmail


class FieldsCache:
    def __init__(self):
        """Constructor"""
        self.cache = {}

    def contains(self, key):
        """ Returns True or False depending on whether or not the key is in the cache."""
        return key in self.cache

    def get(self, key):
        """Return value for the key."""
        return self.cache[key]['value']

    def set(self, key, value):
        """Set key value in cache."""
        self.cache[key] = {'date_created': datetime.datetime.now(),
                           'value': value}


CACHE = FieldsCache()


class Unix(fields.Field):
    """
    datetime.datetime <-> unix timestamp
    """

    def _serialize(self, value, attr, obj):
        try:
            return arrow.get(value).timestamp
        except ParserError as ex:
            raise ValidationError(ex)

    def _deserialize(self, value, attr, obj):
        try:
            return arrow.get(value).datetime
        except ParserError as ex:
            raise ValidationError(ex)


class Email(fields.Email):
    """
    ProsperWorks emails can have leading and trailing spaces.
    """

    def __init__(self, *args, **kwargs):
        super(Email, self).__init__(self, *args, **kwargs)

        # clobber the validator that superclass inserted with
        # whitespace-tolerant equivalent
        validator = WhitespaceEmail(error=self.error_messages['invalid'])
        self.validators[0] = validator

    def _validated(self, value):
        if value is None:
            return None
        return WhitespaceEmail(
            error=self.error_messages['invalid']
        )(value)


def normalise_many(fn, default=False):
    """
    Turn single values into lists if self.many = True.

    Use to wrap the _serialize and _deserialize methods of Field subclasses.
    These methods normally have the signature (self, value, attr, data); once
    wrapped they can assume `value` is a collection. From there, (self, values,
    attr, data) makes more sense as the signature.
    """

    @wraps(fn)
    def wrapper(self, value, attr, data):
        many = getattr(self, 'many', default)
        if not many:
            value = [value]
        res = fn(self, value, attr, data)
        if not many:
            return res[0]
        else:
            return res

    return wrapper


class NestedResource(fields.Field):
    """
    Represent a nested data structure as a Resource instance.

    If many=True, a listlike data structure is expected instead. If
    id_only=True, only the id field must exist in the nested representation;
    the remainder of the Resource's data will be fetched.
    """

    def __init__(self, resource_cls, default=missing_, many=False,
                 id_only=False, custom_field=False, **kwargs):
        self.resource_cls = resource_cls
        self.schema = type(resource_cls.Meta.schema)
        self.many = many
        self.id_only = id_only
        self.custom_field = custom_field
        super(NestedResource, self).__init__(default=default, many=many,
                                             **kwargs)

    @normalise_many
    def _deserialize(self, values, attr, data):
        resources = []
        for value in values:
            if self.id_only:
                resources.append(self.resource_cls.objects.get(id=value['id']))
            elif self.custom_field:
                if CACHE.contains(value['custom_field_definition_id']):
                    resource = CACHE.get(value['custom_field_definition_id'])
                else:
                    resource = self.resource_cls.objects.get(id=value['custom_field_definition_id'])
                    CACHE.set(value['custom_field_definition_id'], resource)
                resource.value = value['value']
                resources.append(resource)
            else:
                resources.append(self.resource_cls.from_api_data(value))
        return resources

    @normalise_many
    def _serialize(self, values, attr, data):
        return [value._raw_data for value in values]


class NestedIdentifiedResource(fields.Field):
    """
    (De)serialize "Identifier" fields as Resource instances.

    See:
        https://www.prosperworks.com/developer_api/identifier
    """

    _default_types = {
        'person': 'prospyr.resources.Person',
        'lead': 'prospyr.resources.Lead',
        'opportunity': 'prospyr.resources.Opportunity',
        'company': 'prospyr.resources.Company',
    }

    placeholder_types = {
        'lead': 'Lead',
        'project': 'Project',
    }

    def __init__(self, default=missing_, many=False, types=None, **kwargs):
        self.many = many
        self.types = self._default_types if types is None else types
        self.reverse_types = {v: k for k, v in self.types.items()}
        super(NestedIdentifiedResource, self).__init__(default=default,
                                                       many=many, **kwargs)

    @normalise_many
    def _deserialize(self, values, attr, data):
        resources = []
        for value in values:
            idtype = value['type']
            if idtype is None and self.allow_none is False:
                self.fail('null')
            elif idtype is None:
                resource = None
            elif idtype in self.placeholder_types:
                # the resource isn't modelled yet
                from prospyr.resources import Placeholder
                name = encode_typename(self.placeholder_types[idtype])
                resource_cls = type(name, (Placeholder,), {})
                resource = resource_cls(id=value['id'])
            else:
                # modelled resource; fetch
                resource_path = self.types.get(idtype)
                if resource_path is None:
                    raise ValueError('Unknown identifier type %s' % idtype)
                resource_cls = import_dotted_path(resource_path)
                try:
                    resource = resource_cls.objects.get(id=value['id'])
                except exceptions.ApiError as ex:
                    status_code, msg = ex.args
                    if status_code == codes.not_found:
                        resource = None
                    else:
                        raise

            resources.append(resource)
        return resources

    @normalise_many
    def _serialize(self, values, attr, data):
        from prospyr.resources import Identifier  # avoid circular derp

        raws = []
        for value in values:
            if value is None and self.allow_none is False:
                self.fail('null')
            elif value is None:
                raw = {'type': None, 'id': None}
            else:
                raw = Identifier.from_instance(value)._raw_data
            raws.append(raw)
        return raws
