# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from logging import getLogger

from requests import codes

from prospyr.exceptions import ApiError

logger = getLogger(__name__)


class Creatable(object):
    """
    Allows creation of a Resource. Should be mixed in with that class.
    """

    # pworks uses 200 OK for creates. 201 CREATED is here through optimism.
    _create_success_codes = {codes.created, codes.ok}

    def create(self, using='default'):
        """
        Create a new instance of this Resource. True on success.
        """
        if hasattr(self, 'id'):
            raise ValueError(
                '%s cannot be created; it already has an id' % self
            )
        conn = self._get_conn(using)
        path = self.Meta.create_path
        resp = conn.post(conn.build_absolute_url(path), json=self._raw_data)

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

    def update(self, using='default'):
        """
        Update this Resource. True on success.
        """
        if getattr(self, 'id', None) is None:
            raise ValueError('%s cannot be deleted before it is saved' % self)

        # can't update IDs
        data = self._raw_data
        data.pop('id')

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
