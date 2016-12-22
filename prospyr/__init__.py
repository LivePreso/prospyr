# -*- coding: utf-8 -*-
# flake8: noqa

from __future__ import absolute_import, print_function, unicode_literals

# alias some useful things here.
from prospyr.connection import connect
from prospyr.resources import (Activity, ActivityType, Company, CustomField,
                               CustomerSource, Identifier, Lead, LossReason,
                               Opportunity, Person, Pipeline, PipelineStage,
                               Task, User)
from prospyr.version import VERSION
