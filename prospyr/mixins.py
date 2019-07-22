# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from logging import getLogger
from datetime import datetime
from requests import codes

from prospyr.exceptions import ApiError
from prospyr.constants import *

logger = getLogger(__name__)


class Creatable(object):
    """
    Allows creation of a Resource. Should be mixed in with that class.
    """

    # pworks uses 200 OK for creates. 201 CREATED is here through optimism.
    _create_success_codes = {codes.created, codes.ok}

    def create(self, using='default', email=None, emails=None):
        """
        Create a new instance of this Resource. True on success.
        """
        if hasattr(self, 'id'):
            raise ValueError(
                '%s cannot be created; it already has an id' % self
            )
        conn = self._get_conn(using)
        path = self.Meta.create_path

        data = self._raw_data
        if email:
            data['email'] = {'category': 'work', 'email': email}

        if emails:
            data['emails'] = [{'email': emails, 'category': 'work'}]
        resp = conn.post(conn.build_absolute_url(path), json=data)

        if resp.status_code in self._create_success_codes:
            data = self._load_raw(resp.json())
            self._set_fields(data)
            return True
        elif resp.status_code == codes.unprocessable_entity:
            error = resp.json()
            raise ValueError(error['message'])
        else:
            raise ApiError(resp.status_code, resp.text)


class Readable(object):
    """
    Allows reading of a Resource. Should be mixed in with that class.
    """

    _read_success_codes = {codes.ok}

    def read(self, using='default'):
        """
        Read this Resource from remote API. True on success.
        """
        logger.debug('Connected using %s', using)
        path = self._get_path()
        conn = self._get_conn(using)
        resp = conn.get(conn.build_absolute_url(path))
        if resp.status_code not in self._read_success_codes:
            raise ApiError(resp.status_code, resp.text)
        data = self._load_raw(resp.json())
        self._set_fields(data)
        return True

    def _get_path(self):
        if getattr(self, 'id', None) is None:
            raise ValueError('%s must be saved before it is read' % self)
        return self.Meta.detail_path.format(id=self.id)


class Singleton(Readable):
    """
    Allows reading of a Resource without an id.
    Should be mixed in with that class.
    """

    def _get_path(self):
        return self.Meta.detail_path


class Updateable(object):
    """
    Allows updating a Resource. Should be mixed in with that class.
    """

    _update_success_codes = {codes.ok}

    def update(self, using='default', email=None, emails=None):
        """
        Update this Resource. True on success.
        """
        if getattr(self, 'id', None) is None:
            raise ValueError('%s cannot be deleted before it is saved' % self)

        # can't update IDs
        data = self._raw_data
        data['custom_fields'] = []
        data.pop('id')

        # convert to PW style
        for cf in self._raw_data['custom_fields']:
            if 'value' in cf:
                if cf['data_type'] == TYPE_DROPDOWN:
                    value = int(cf['value']) if cf['value'] else None
                elif cf['data_type'] == TYPE_MULTISELECT:
                    value = [int(v) for v in eval(cf['value'])]
                elif cf['data_type'] == TYPE_FLOAT:
                    value = float(cf['value']) if cf['value'] else None
                elif cf['data_type'] == TYPE_DATE:
                    date_match = re.search(r'\d{2}/\d{2}/\d{4}', cf['value'])
                    if date_match:
                        value = date_match.group()
                    else:
                        value = None
                else:
                    value = cf['value']
            else:
                value = ''
            data['custom_fields'].append(
                {'custom_field_definition_id': cf['id'], 'value': value}
            )
        if email:
            try:
                data['email']['email'] = email
            except KeyError:
                # this may happen if the lead doesn't have an email, by default we add as work email
                data['email'] = {'email': email, 'category': 'work'}
        if emails:
            try:
                data['emails'][0]['email'] = emails
            except KeyError:
                # this may happen if the lead doesn't have an email, by default we add as work email
                data['emails'] = [{'email': emails, 'category': 'work'}]
        try:
            if 'phone_numbers' in data:
                for number in data['phone_numbers']:
                    if number['category'] is None :
                        number['category'] = 'work' # set default category value to work 
        except KeyError:
            data['phone_numbers'] = [{'number': '', 'category': 'work'}]
        try:
            if 'websites' in data:
                for website in data['websites']:
                    if website['category'] is None :
                        website['category'] = 'work' # set default category value to work
        except KeyError:
            data['websites'] = [{'url': '', 'category': 'work'}]
        if type(self).__name__ == 'Opportunity':
            try:
                del data['close_date']
            except KeyError:
                pass
        conn = self._get_conn(using)
        path = self.Meta.detail_path.format(id=self.id)
        resp = conn.put(conn.build_absolute_url(path), json=data)
        if resp.status_code in self._update_success_codes:
            return True
        elif resp.status_code == codes.unprocessable_entity:
            error = resp.json()
            raise ValueError(error['message'])
        else:
            raise ApiError(resp.status_code, resp.text)


class Deletable(object):
    """
    Allows deletion of a Resource. Should be mixed in with that class.
    """

    _delete_success_codes = {codes.ok}

    def delete(self, using='default'):
        """
        Delete this Resource. True on success.
        """
        if getattr(self, 'id', None) is None:
            raise ValueError('%s cannot be deleted before it is saved' % self)
        conn = self._get_conn(using)
        path = self.Meta.detail_path.format(id=self.id)
        resp = conn.delete(conn.build_absolute_url(path))
        if resp.status_code in self._delete_success_codes:
            return True
        else:
            raise ApiError(resp.status_code, resp.text)


class ReadWritable(Creatable, Readable, Updateable, Deletable):
    pass


class CustomFieldMixin(object):
    class Meta:
        abstract = True

    def get_custom_field_value(cls, field_name):
        """
        Return custom field value depending on data type.
        """
        value = ''
        for field in cls.custom_fields:
            if field.name == field_name:
                if field.value:
                    if field.data_type in [TYPE_STRING, TYPE_TEXT, TYPE_FLOAT, TYPE_URL, TYPE_PERCENTAGE,
                                           TYPE_CURRENCY]:
                        value = field.value
                    elif field.data_type == TYPE_DROPDOWN:
                        for option in field.options:
                            if option['id'] == field.value:
                                value = option['name']
                    elif field.data_type == TYPE_MULTISELECT:
                        values = []
                        for val in field.value:
                            for option in field.options:
                                if option['id'] == val:
                                    values.append(option['name'])
                        value = ','.join(values)
                    elif field.data_type == TYPE_DATE:
                        value = datetime.fromtimestamp(field.value).date()
        return value

    def set_custom_field_value(cls, field_name, value):
        """
        Set custom field value.
        """
        custom_fields = cls.custom_fields
        index = 0
        for field in cls.custom_fields:
            if field.name == field_name:
                if value is None:
                    custom_fields[index].value = None
                elif field.data_type in [TYPE_STRING, TYPE_TEXT, TYPE_FLOAT, TYPE_URL, TYPE_PERCENTAGE,
                                         TYPE_CURRENCY]:
                    custom_fields[index].value = value
                elif field.data_type == TYPE_DROPDOWN:
                    for option in field.options:
                        if option['name'].lower().strip() == value.lower().strip():
                            custom_fields[index].value = option['id']
                elif field.data_type == TYPE_MULTISELECT:
                    values = []
                    for val in value:
                        for option in field.options:
                            if option['name'] == val:
                                values.append(option['id'])
                    custom_fields[index].value = values
                elif field.data_type == TYPE_DATE:
                    custom_fields[index].value = value
            index += 1
        cls.custom_fields = custom_fields
