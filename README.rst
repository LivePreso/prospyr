Prospyr
#######

A Python client library for ProsperWorks.

.. image:: https://api.travis-ci.org/salespreso/prospyr.svg?branch=master
   :target: https://travis-ci.org/salespreso/prospyr
   :alt: Prospyr builds.

.. image:: https://img.shields.io/codecov/c/github/salespreso/prospyr.svg
   :target: https://codecov.io/github/salespreso/prospyr
   :alt: Prospyr on Codecov.

.. image:: https://landscape.io/github/salespreso/prospyr/master/landscape.svg?style=flat
   :target: https://landscape.io/github/salespreso/prospyr/master
   :alt: Code Health

.. image:: https://badge.fury.io/py/prospyr.svg
   :target: https://pypi.python.org/pypi/prospyr/
   :alt: Prospyr on Pypi.

Prospyr runs on Python 2.7 or Python 3.4+. 

Installation
============

.. code-block:: sh

    pip install prospyr

Quickstart
==========

If you've used Django, Prospyr might feel strangely familiar.

.. code-block:: python

    from prospyr import connect, Person, Company

    # see https://www.prosperworks.com/developer_api/token_generation to obtain
    # a token.
    cn = connect(email='user@domain.tld', token='1aefcc3...')

    # collections can be ordered and sliced.
    newest_person = Person.objects.order_by('-date_modified')[0]

    # new records can be created.
    art = Person(
        name='Art Vandelay',
        emails=[{'email': 'art@vandelayindustries.net', 'category': 'work'}]
    )
    art.create()  # Art is local-only until .create() is called

    # related objects can be read and assigned
    art.company = Company.objects.all()[0]
    art.update()

    # and deleting works too.
    art.delete()


Resources
=========

The following ProsperWorks resources are supported by Prospyr:

- Account (read-only)
- Activity (read–only)
- ActivityType
- Company
- CustomerSource (read–only)
- Identifier
- Lead
- LossReason (read–only)
- Opportunity
- Person
- Pipeline (read–only)
- PipelineStage (read–only)
- Task (read–only)
- User (read–only)

The following resources are not supported, but will still appear when
referenced by the supported resources above. In this case, they come only with
an ``id`` attribute.

- Project

Note you will receive errors trying to deal with the Lead resource if the Leads
feature is not enabled in your ProsperWorks account. You can change this at
Settings / Customize ProsperWorks / Lead Management.


Usage
=====

Connecting
----------

To connect, you'll need an email and token per
`token generation <https://www.prosperworks.com/developer_api/token_generation>`_.

.. code-block:: python

    from prospyr import connect

    cn = connect(email='...', token='...')

All reads are cached per–connection for five minutes. You can pass a custom
cache instance when connecting to ProsperWorks to change this behaviour.

.. code-block:: python

    from prospyr import connect
    from prospyr.cache import NoOpCache, InMemoryCache

    # only cache the last request
    cn = connect(email='...', token='...', cache=InMemoryCache(size=1))

    # no caching
    cn = connect(email='...', token='...', cache=NoOpCache())

You can also substitute your own custom cache here to use e.g. Redis or
memcached.

Prospyr also supports multiple named connections. Provide a ``name='...'``
argument when calling ``connect()`` and refer to the connection when
interacting with the API later, e.g. ``Person.objects.get(id=1, using='...')``.

Create
------

You can create new records in ProsperWorks.

.. code-block:: python

    from prospyr import Person

    steve = Person(
        name='Steve Cognito',
        emails=[{'category': 'work', 'email': 'steve@example.org'}]
    )

    # steve only exists locally at this stage
    steve.id
    >>> None

    # now he exists remotely too
    steve.create()
    >>> True
    steve.id
    >>> 1

Read
----

There are two ways to read a single record from ProsperWorks. A new instance
can be fetched using the resource's ``objects.get()`` method, or you can call
``read()`` on an existing instance to have its attributes refreshed.

.. code-block:: python

    from prospyr import Person

    # a new instance
    steve = Person.objects.get(id=1)
    steve.name
    >>> 'Steve Cognito'

    # update an existing instance
    steve = Person(id=1)
    steve.read()
    >>> True
    steve.name
    >>> 'Steve Cognito'

Update
------

Note that “update” means to push an update to ProsperWorks using your local
data, rather than to refresh local data using ProsperWorks. In this example,
Steve is fetched from ProsperWorks and given a new title. Hey, congrats on the
promotion Steve.

.. code-block:: python

    from prospyr import Person

    steve = Person.objects.get(id=1)
    steve.title = 'Chairman'
    steve.update()
    >>> True

Delete
------

When Steve has reached the end of his useful lifespan, he can be deleted too.

.. code-block:: python

    from prospyr import Person

    steve = Person.objects.get(id=1)
    steve.delete()
    >>> True

Ordering
--------

Resource collections can be ordered. Check the `ProsperWorks API documentation
<https://www.prosperworks.com/developer_api/>`_ to learn which fields can be
ordered. However, Prospyr does check that the fields you argue are correct.

.. code-block:: python

    from prospyr import Person

    # oldest first
    rs = Person.objects.order_by('date_modified')

    # newest first (note the hyphen)
    rs = Person.objects.order_by('-date_modified')

    # At this stage, no requests have been made. Results are lazily evaluated
    # and paging is handled transparently.

    # The results can be indexed and sliced like a Python list. Doing so forces
    # evaluation. The below causes the first page of results to be fetched.
    rs[0]
    >>> <Person: Steve Cognito>

    # No request is required here, as the Bones was on the first page requested
    # above. The default page size is 200.
    rs[1]
    >>> <Person: Bones Johannson>

    # This result is on the second page, so another request is fired.
    rs[200]
    >>> <Person: Alfons Tundra>

Once ``ResultSet`` instances have been evaluated they are cached for their
lifetime. However, the ``filter()`` and ``order_by()`` methods return new
``ResultSet`` instances which require fresh evaluation. While you are dealing
with a single ``ResultSet``, it is safe to iterate and slice it as many times
as necessary.


Filtering
---------

Resource collections can be filtered. Check the `ProsperWorks API documentation
<https://www.prosperworks.com/developer_api/>`_ to learn which filters can be
used. Prospyr does *not* currently validate your filter arguments, and note
that ProsperWorks does not either; if you make an invalid filter argument,
results will be returned as though you had not filtered at all.

Multiple filters are logically ANDed together. A single call to ``filter()``
with many parameters is equivalent to many calls with single parameters.


.. code-block:: python

    from prospyr import Company

    active = Company.objects.filter(minimum_interaction_count=10)
    active_in_china = active.filter(country='CN')

    # this is equivalent
    active_in_china = Company.objects.filter(
        minimum_interaction_count=10,
        country='CN'
    )

As with ordering, filtered results are evaluated lazily and then cached
indefinitely. Re-ordering or re-filtering results in a new ``ResultSet`` which
requires fresh evaluation.

ProsperWorks' “Secondary Resources”, such as Pipeline Stages, cannot be
filtered or ordered. These resources use ``ListSet`` rather than ``ResultSet``
instances; these only support the ``all()`` method:

.. code-block:: python

    from prospyr import PipelineStage

    PipelineStage.objects.all()
    >>> <ListSet: Qualifying, Quoted, ...>


Collection Error Handling
-------------------------

Prospyr validates data delivered from ProsperWorks when building representative
Python objects for local use. Because there are no documented details on the
validation that ProsperWorks itself uses, Prospyr's validation rules are
sometimes incorrect or more strict than necessary. The author suspects that
sometimes ProsperWorks also delivers data that is simply invalid.

This can cause exceptions to be raised when iterating over result sets (e.g.
``for person in Person.objects.all()...``) which prevent the remainder of the
collection from being accessed.

To make your life easier while such a mismatch is corrected in Prospyr, you can
choose to have these validation errors collected instead of being raised:

.. code-block:: python

    from prospyr import Person

    errs = []
    for person in Person.objects.store_invalid(errs).all():
        # ...

    if errs:
        # handle errors

The argument to ``store_invalid`` must, like a list, have a working ``append``
method. It will be filled with ``ValidationError`` instances which each have
``errors``, ``raw_data`` and ``resource_cls`` attributes.

If your use–case allows you to correct the problem in ``raw_data``, you can
recover like so:

.. code-block:: python

    for err in errs:
        good_data = make_corrections(err.raw_data)
        instance = err.resource_cls.from_api_data(good_data)


Tests
=====

.. code-block:: sh

    pip install -r dev-requirements

    # test using the current python interpreter
    make test

    # test with all supported interpreters
    tox
