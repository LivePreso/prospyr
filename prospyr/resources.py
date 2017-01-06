# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from logging import getLogger

from marshmallow import fields
from marshmallow.validate import OneOf
from six import string_types, with_metaclass

from prospyr import connection, exceptions, mixins, schema
from prospyr.fields import NestedIdentifiedResource, NestedResource, Unix
from prospyr.search import ActivityTypeListSet, ListSet, ResultSet
from prospyr.util import encode_typename, import_dotted_path, to_snake

logger = getLogger(__name__)


class Manager(object):

    _search_cls = ResultSet

    def get(self, id):
        instance = self.resource_cls()
        instance.id = id
        instance.read(using=self.using)
        return instance

    def __get__(self, instance, cls):
        if instance:
            raise AttributeError(
                'You can\'t access this {manager_cls} from a resource '
                'instance; Use {resource_cls}.objects instead'.format(
                    resource_cls=type(instance).__name__,
                    manager_cls=type(self).__name__
                )
            )
        self.resource_cls = cls
        self.using = 'default'
        return self

    def use(self, name):
        self.using = name
        return self

    def all(self):
        return self.filter()

    def filter(self, **query):
        fresh = self._search_cls(resource_cls=self.resource_cls,
                                 using=self.using)
        return fresh.filter(**query)

    def order_by(self, field):
        fresh = self._search_cls(resource_cls=self.resource_cls,
                                 using=self.using)
        return fresh.order_by(field)

    def store_invalid(self, dest):
        fresh = self._search_cls(resource_cls=self.resource_cls,
                                 using=self.using)
        return fresh.store_invalid(dest)


class ListOnlyManager(Manager):
    """
    Manage a resource which has only a list URL.

    Some ProsperWorks resources are list-only; they have no search or detail
    URLs. The get() method is simulated. filtering and ordering is disabled.
    """

    _results_by_id = None
    _search_cls = ListSet

    def results_by_id(self, force_refresh=False):
        if self._results_by_id is None or force_refresh is True:
            rs = self.all()
            self._results_by_id = {r.id: r for r in rs}
        return self._results_by_id

    def get(self, id):
        result = self.results_by_id().get(id)
        if result is None:
            # perhaps our cache is stale?
            result = self.results_by_id(force_refresh=True).get(id)
            if result is None:
                raise KeyError('Record with id `%s` does not exist' % id)
        return result

    def all(self):
        return self._search_cls(resource_cls=self.resource_cls,
                                using=self.using)


class NoCollectionManager(Manager):
    """
    Manage resources which cannot be listed or searched.
    """

    def _raise_not_collection(self):
        raise NotImplementedError('%s cannot be treated as a collection.' %
                                  self.resource_cls.__name__)

    def all(self):
        self._raise_not_collection()

    def filter(self, **query):
        self._raise_not_collection()

    def order_by(self, field):
        self._raise_not_collection()


class SingletonManager(NoCollectionManager):
    """
    Manage resources that have a single object.
    """

    def get(self):
        instance = self.resource_cls()
        instance.read(using=self.using)
        return instance


class ActivityTypeManager(ListOnlyManager):
    """
    Special-case ActivityType's listing actually being two seperate lists.
    """
    _search_cls = ActivityTypeListSet


class ResourceMeta(type):
    """
    Metaclass of all Resources.

    Pulls marshmallow schema fields onto a Schema definition.
    """
    class Meta(object):
        abstract = True

    def __new__(cls, name, bases, attrs):
        super_new = super(ResourceMeta, cls).__new__

        # only do metaclass tomfoolery for concrete resources.
        subclasses = {b for b in bases if issubclass(b, Resource)}
        requires_schema = any(getattr(s.Meta, 'abstract', True)
                              for s in subclasses)
        if not requires_schema:
            return super_new(cls, name, bases, attrs)

        # move marshmallow fields to a new Schema subclass on cls.Meta
        schema_attrs = {}
        for attr, value in list(attrs.items()):
            if isinstance(value, fields.Field):
                schema_attrs[attr] = attrs.pop(attr)
            elif hasattr(value, 'modify_schema_attrs'):
                schema_attrs = value.modify_schema_attrs(attr, schema_attrs)
        schema_cls = type(
            encode_typename('%sSchema' % name),
            (schema.TrimSchema, ),
            schema_attrs
        )
        if 'Meta' not in attrs:
            raise AttributeError('Class %s must define a `class Meta`' %
                                 cls.__name__)
        attrs['Meta'].schema = schema_cls()

        return super_new(cls, name, bases, attrs)


class Resource(with_metaclass(ResourceMeta)):
    """
    Superclass of all ProsperWorks API resources.

    This class should be mixed with mixins.Readable, mixins.Creatable etc.
    """
    objects = Manager()

    class Meta:
        abstract = True

    def __init__(self, **data):
        self._set_fields(data)

    def validate(self):
        schema = self.Meta.schema
        attrs = set(dir(self)) & set(schema.declared_fields)
        data = {k: getattr(self, k) for k in attrs}
        errors = self.Meta.schema.validate(data)
        if errors:
            raise exceptions.ValidationError(
                ('{cls} instance is not valid; Errors encountered: {errors}'
                 .format(cls=type(self), errors=repr(errors))),
                raw_data=data,
                resource_cls=type(self),
                errors=errors
            )

    @classmethod
    def from_api_data(cls, orig_data):
        """
        Alternate constructor. Build instance from ProsperWorks API data.
        """
        data = cls._load_raw(orig_data)
        instance = cls()
        instance._set_fields(data)
        instance._orig_data = orig_data
        return instance

    @classmethod
    def _load_raw(cls, raw_data):
        """
        Convert `raw_data` into a Resource instance.
        """
        data, errors = cls.Meta.schema.load(raw_data)
        if errors:
            raise exceptions.ValidationError(
                ('ProsperWorks delivered data which does not agree with the '
                 'local Prospyr schema. This is probably a Prospyr bug. '
                 'Errors encountered: %s' % repr(errors)),
                raw_data=raw_data,
                resource_cls=cls,
                errors=errors,
            )
        return data

    def __repr__(self):
        classname = type(self).__name__
        friendly = str(self)
        return '<%s: %s>' % (classname, friendly)

    def __str__(self):
        if hasattr(self, 'name'):
            return self.name
        elif hasattr(self, 'id'):
            return str(self.id)
        return '(unsaved)'

    def _get_conn(self, using):
        return connection.get(using)

    def _set_fields(self, data):
        """
        Without validating, write `data` onto the fields of this Resource.
        """
        for field, value in data.items():
            setattr(self, field, value)

    @property
    def _raw_data(self):
        schema = self.Meta.schema
        data, errors = schema.dump(self)
        if errors:
            raise exceptions.ValidationError(
                'Could not serialize %s data: %s' % (self, repr(errors)),
                raw_data=data,
                resource_cls=type(self),
                errors=errors,
            )

        return data


class SecondaryResource(Resource):
    """
    Secondary resources have only a list URL.
    """
    class Meta:
        abstract = True

    objects = ListOnlyManager()


class Related(object):
    """
    Behave as a related object when an attribute of a Resource.
    """

    def __init__(self, related_cls, required=False):
        self._related_cls = related_cls
        self.required = required

    @property
    def related_cls(self):
        if isinstance(self._related_cls, string_types):
            self._related_cls = import_dotted_path(self._related_cls)
        return self._related_cls

    def __get__(self, instance, cls):
        if instance is None:
            return self
        attr = self.find_parent_attr(type(instance))
        id = getattr(instance, '%s_id' % attr)
        if id is None:
            return None
        return self.related_cls.objects.get(id=id)

    def __set__(self, instance, value):
        attr = self.find_parent_attr(type(instance))
        if not isinstance(value, self.related_cls):
            raise ValueError(
                '`{value}` must be an instance of `{cls}`'
                .format(value=value, cls=self.related_cls)
            )
        if not value.id:
            raise ValueError(
                '`{value}` can\'t be assigned without an `id` attribute.'
                .format(value=value)
            )
        setattr(instance, '%s_id' % attr, value.id)

    def find_parent_attr(self, parent_cls):
        for attr in dir(parent_cls):
            if getattr(parent_cls, attr) is self:
                return attr
        else:
            raise AttributeError('Cannot find self')

    def modify_schema_attrs(self, self_attr, schema_attrs):
        allow_none = (self.required is False)
        field = fields.Integer(allow_none=allow_none)
        schema_attrs['%s_id' % self_attr] = field
        return schema_attrs


class User(Resource, mixins.Readable):

    class Meta(object):
        list_path = 'users/'
        search_path = 'users/search/'
        detail_path = 'users/{id}/'
        order_fields = {
            'name',
            'email',
        }

    id = fields.Integer()
    name = fields.String(required=True)
    email = fields.Email(required=True)

    def __str__(self):
        return '{self.name} ({self.email})'.format(self=self)


class Company(Resource, mixins.ReadWritable):

    class Meta(object):
        create_path = 'companies/'
        search_path = 'companies/search/'
        detail_path = 'companies/{id}/'
        order_fields = {
            'name',
            'city',
            'state',
            'assignee',
            'inactive_days',
            'last_interaction',
            'interaction_count',
            'date_created',
            'date_modified',
        }

    id = fields.Integer()
    name = fields.String(required=True)
    address = fields.Nested(schema.AddressSchema, allow_none=True)
    assignee_id = fields.Integer(allow_none=True)
    assignee = Related(User)
    contact_type_id = fields.Integer(allow_none=True)
    details = fields.String(allow_none=True)
    email_domain = fields.String(allow_none=True)
    phone_numbers = fields.Nested(schema.PhoneNumberSchema, many=True)
    socials = fields.Nested(schema.SocialSchema, many=True)
    tags = fields.List(fields.String)
    custom_fields = fields.Nested(
        schema.CustomFieldSchema,
        many=True,
        allow_none=True
    )
    date_created = Unix()
    date_modified = Unix()
    websites = fields.Nested(schema.WebsiteSchema, many=True)


class Person(Resource, mixins.ReadWritable):

    class Meta(object):
        create_path = 'people/'
        search_path = 'people/search/'
        detail_path = 'people/{id}/'
        order_fields = {
            'name',
            'city',
            'state',
            'assignee',
            'inactive_days',
            'last_interaction',
            'interaction_count',
            'date_created',
            'date_modified',
        }

    id = fields.Integer()
    name = fields.String(required=True)
    address = fields.Nested(
        schema.AddressSchema,
        allow_none=True
    )
    assignee_id = fields.Integer(allow_none=True)
    assignee = Related(User)
    company_id = fields.Integer(allow_none=True)
    company = Related(Company)
    company_name = fields.String(allow_none=True, load_only=True)
    contact_type_id = fields.Integer(allow_none=True)
    details = fields.String(allow_none=True)
    emails = fields.Nested(
        schema.EmailSchema,
        many=True,
        required=True,
    )
    phone_numbers = fields.Nested(schema.PhoneNumberSchema, many=True)
    socials = fields.Nested(schema.SocialSchema, many=True)
    tags = fields.List(fields.String)
    title = fields.String(allow_none=True)
    custom_fields = fields.Nested(
        schema.CustomFieldSchema,
        many=True,
        allow_none=True
    )
    date_created = Unix()
    date_modified = Unix()
    websites = fields.Nested(schema.WebsiteSchema, many=True)


class LossReason(SecondaryResource, mixins.Readable):
    class Meta(object):
        list_path = 'loss_reasons'

    id = fields.Integer()
    name = fields.String(required=True)


class PipelineStage(SecondaryResource, mixins.Readable):
    class Meta(object):
        list_path = 'pipeline_stages'

    id = fields.Integer()
    name = fields.String(required=True)
    pipeline = Related('prospyr.resources.Pipeline')


class Pipeline(SecondaryResource, mixins.Readable):
    class Meta(object):
        list_path = 'pipelines'

    id = fields.Integer()
    name = fields.String(required=True)
    stages = NestedResource(
        PipelineStage,
        many=True,
    )


class CustomerSource(SecondaryResource, mixins.Readable):
    class Meta(object):
        list_path = 'customer_sources'

    id = fields.Integer()
    name = fields.String(required=True)


class Opportunity(Resource, mixins.ReadWritable):
    class Meta(object):
        create_path = 'opportunities/'
        search_path = 'opportunities/search/'
        detail_path = 'opportunities/{id}/'
        order_fields = {
            'name',
            'assignee',
            'company_name',
            'customer_source_id',
            'monetary_value',
            'primary_contact',
            'priority',
            'status',
            'inactive_days',
            'last_interaction',
            'interaction_count',
            'date_created',
            'date_modified',
        }

    id = fields.Integer()
    name = fields.String(required=True)
    company_name = fields.String(allow_none=True, load_only=True)
    close_date = Unix(allow_none=True)
    details = fields.String(allow_none=True)
    monetary_value = fields.Integer(allow_none=True)

    assignee = Related(User)
    company = Related(Company)
    loss_reason = Related(LossReason)
    customer_source = Related(CustomerSource)
    pipeline = Related(Pipeline)
    pipeline_stage = Related(PipelineStage)
    primary_contact = Related(Person, required=True)
    priority = fields.String(
        allow_none=True,
        validate=OneOf(choices=('None', 'Low', 'Medium', 'High')),
    )
    stage = fields.String(
        allow_none=True,
        validate=OneOf(choices=('Open', 'Won', 'Lost', 'Abandoned')),
    )
    tags = fields.List(fields.String)
    win_probability = fields.Integer()
    custom_fields = fields.Nested(
        schema.CustomFieldSchema,
        many=True,
        allow_none=True
    )
    date_created = Unix()
    date_modified = Unix()


class ActivityType(SecondaryResource, mixins.Readable):
    class Meta(object):
        list_path = 'activity_types'

    objects = ActivityTypeManager()

    id = fields.Integer(required=True)
    category = fields.String(
        validate=OneOf(choices=('user', 'system')),
    )
    name = fields.String()
    is_disabled = fields.Boolean()
    count_as_interaction = fields.Boolean()


class Identifier(SecondaryResource):

    class Meta:
        pass

    valid_types = {'lead', 'person', 'opportunity', 'company'}
    objects = NoCollectionManager()

    id = fields.Integer()
    type = fields.String(
        validate=OneOf(choices=valid_types)
    )

    @classmethod
    def from_instance(cls, resource):
        if not isinstance(resource, Resource):
            raise ValueError('%s must be an instance of Resource' % resource)
        type_ = to_snake(type(resource).__name__)
        if type_ not in cls.valid_types:
            raise ValueError('%s must be one of %s' % (type_, cls.valid_types))
        return cls(
            type=type_,
            id=resource.id
        )

    @classmethod
    def from_resource_and_id(cls, resource, id):
        type_ = to_snake(resource.__name__)
        if type_ not in cls.valid_types:
            raise ValueError('%s must be one of %s' % (type_, cls.valid_types))
        return cls(type=type_, id=id)

    def __str__(self):
        return '{type} {id}'.format(
            type=self.type.title(),
            id=self.id
        )


class Activity(Resource, mixins.ReadWritable):
    class Meta:
        create_path = 'activities/'
        search_path = 'activities/search/'
        detail_path = 'activities/{id}/'
        order_fields = set()  # no ordering

    id = fields.Integer()
    type = NestedResource(ActivityType, id_only=True)
    parent = NestedIdentifiedResource()
    details = fields.String(allow_none=True)
    user = Related(User)
    activity_date = Unix()

    def __str__(self):
        if self._orig_data.get('is_deleted', False):
            return 'Deleted activity'
        else:
            date = getattr(self, 'activity_date', 'unknown date')
            return '%s on %s' % (self.type.name, date)


class Task(Resource, mixins.ReadWritable):
    class Meta:
        create_path = 'tasks/'
        search_path = 'tasks/search/'
        detail_path = 'tasks/{id}/'
        order_fields = {
            'name',
            'assigned_to',
            'related_to',
            'status',
            'priority',
            'due_date',
            'reminder_date',
            'completed_date',
            'date_created',
            'date_modified',
        }

    id = fields.Integer()
    name = fields.String()
    related_resource = NestedIdentifiedResource(allow_none=True)
    assignee = Related(User)
    due_date = Unix(allow_none=True)
    reminder_date = Unix(allow_none=True)
    completed_date = Unix(allow_none=True)
    priority = fields.String(validate=OneOf(choices=('None', 'High')))
    status = fields.String(validate=OneOf(choices=('Open', 'Completed')))
    details = fields.String(allow_none=True)
    tags = fields.List(fields.String)
    custom_fields = fields.Nested(
        schema.CustomFieldSchema,
        many=True,
        allow_none=True
    )
    date_created = Unix()
    date_modified = Unix()


class Lead(Resource, mixins.ReadWritable):
    class Meta:
        create_path = 'leads/'
        search_path = 'leads/search'
        detail_path = 'leads/{id}'
        order_fields = {
            'name',
            'assignee',
            'company_name',
            'customer_source',
            'monetary_value',
            'status',
            'title',
            'city',
            'state',
            'inactive_days',
            'last_interaction',
            'interaction_count',
            'date_created',
            'date_modified',
        }

    id = fields.Integer()
    name = fields.String()
    address = fields.Nested(schema.AddressSchema, allow_none=True)
    assignee_id = fields.Integer(allow_none=True)
    assignee = Related(User)
    company_name = fields.String(allow_none=True)
    customer_source_id = fields.Integer(allow_none=True)
    customer_source = Related(CustomerSource)
    details = fields.String(allow_none=True)
    email = fields.Nested(schema.EmailSchema, allow_none=True)
    monetary_value = fields.Integer(allow_none=True)
    phone_numbers = fields.Nested(schema.PhoneNumberSchema, many=True)
    socials = fields.Nested(schema.SocialSchema, many=True)
    status = fields.String()
    tags = fields.List(fields.String)
    title = fields.String(allow_none=True)
    websites = fields.Nested(schema.WebsiteSchema, many=True)
    custom_fields = fields.Nested(
        schema.CustomFieldSchema,
        many=True,
        allow_none=True,
    )
    date_created = Unix()
    date_modified = Unix()


class Account(Resource, mixins.Singleton):

    objects = SingletonManager()

    class Meta:
        detail_path = 'account/'

    id = fields.Integer()
    name = fields.String()

    
class CustomField(Resource, mixins.Readable):
    _data_types = (
        'String', 'Text', 'Dropdown', 'Date', 'Checkbox', 'Float', 'URL',
        'Percentage', 'Currency'
    )

    objects = ListOnlyManager()

    class Meta:
        list_path = 'custom_field_definitions/'
        detail_path = 'custom_field_definitions/{id}'

    id = fields.Integer()
    name = fields.String()
    data_type = fields.String(validate=OneOf(choices=_data_types))
    currency = fields.String(allow_none=True)
    options = fields.Nested(
        schema.CustomFieldOptionSchema,
        many=True,
        allow_none=True
    )


class Placeholder(object):
    """
    Stand-in for Prosperworks resources that Prospyr does not yet model.

    This is required because an Identifier field can point at resources that
    aren't yet implemented.
    """

    def __init__(self, id):
        self.id = id

    def __repr__(self):
        classname = type(self).__name__
        friendly = str(self)
        return '<%s: %s (placeholder)>' % (classname, friendly)

    def __str__(self):
        return str(self.id)


class Project(Placeholder):
    pass
