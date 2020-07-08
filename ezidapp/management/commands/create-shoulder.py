"""Create a new shoulder
"""

from __future__ import absolute_import, division, print_function

import datetime
import logging
import pprint
import re
import argparse

import django.core.management
import django.core.management.base
import hjson
import impl.nog_minter
import utils.filesystem
import ezidapp.models
import config


try:
    import bsddb
except ImportError:
    import bsddb3 as bsddb

import django.contrib.auth.models
import django.core.management.base
import django.db.transaction
import impl.util

FILE_PROTOCOL = 'file://'

log = logging.getLogger(__name__)


class Command(django.core.management.base.BaseCommand):
    help = __doc__

    def __init__(self):
        super(Command, self).__init__()
        self.opt = None

    def add_arguments(self, parser):
        # ARK and DOI
        parser.add_argument('naan_str', metavar='naan')
        parser.add_argument('shoulder_str', metavar='shoulder')
        parser.add_argument('name_str', metavar='name')
        parser.add_argument(
            '--super-shoulder,s',
            dest='is_super_shoulder',
            action='store_true',
            help='Set super-shoulder flag',
        )
        parser.add_argument(
            '--prefix-shares-datacenter,p',
            dest='is_prefix_shares_datacenter',
            action='store_true',
            help='Set prefix-shares-datacenter flag',
        )
        # Misc
        parser.add_argument(
            '--debug', '-g', action='store_true', help='Debug level logging',
        )
        parser.add_argument(
            '--test,-t',
            dest='is_test',
            action='store_true',
            help='Create a non-persistent test minter',
        )
        # DOI only (ARK is generated by default)
        parser.add_argument(
            '--doi',
            '-d',
            dest='is_doi',
            action='store_true',
            help='Create a DOI minter (ARK is created by default)',
        )
        ex_group = parser.add_mutually_exclusive_group(required=False)
        ex_group.add_argument(
            '--crossref,-c',
            dest='is_crossref',
            action='store_true',
            help='DOI is registered with Crossref',
        )
        ex_group.add_argument(
            '--datacite,-a',
            metavar='datacenter',
            dest='datacenter_str',
            help='DOI is registered with Crossref',
        )

    def handle(self, *_, **opt):
        # - NAAN: Registered part of prefix. E.g., ARK: `77913`, DOI: `b7913`
        # - Shoulder: User part of prefix. E.g., `r7`
        # - NOID: NAAN / Shoulder. E.g., '77913/r7'
        # - Prefix: Minter protocol + NOID. E.g., 'doi:10.77913/r7'

        pprint.pprint(opt)
        self.opt = opt = argparse.Namespace(**opt)

        if opt.is_doi:
            if not (opt.is_crossref or opt.datacenter_str):
                raise django.core.management.CommandError(
                    'DOI requires either --crossref or --datacite'
                )

            opt.prefix_str = 'doi:10.{}/{}'.format(
                opt.naan_str, opt.shoulder_str.upper()
            )
            shadow_str = impl.util.doi2shadow(
                '10.{}/{}'.format(opt.naan_str, opt.shoulder_str.upper())
            )
            opt.naan_str, opt.shoulder_str = shadow_str.split('/')
            self.opt.noid_str = '/'.join([opt.naan_str, opt.shoulder_str])

            if not re.match(r'[a-z0-9]\d{4}$', opt.naan_str):
                raise django.core.management.CommandError(
                    'NAAN for a DOI must be 5 digits, or one lower case character '
                    'and 4 digits:'.format(opt.naan_str)
                )

            if self.opt.datacenter_str:
                self.assert_valid_datacenter()

        else:
            noid_str = '/'.join([opt.naan_str, opt.shoulder_str])
            opt.prefix_str = 'ark:/{}'.format(noid_str)

            if not re.match(r'\d{5}$', opt.naan_str):
                raise django.core.management.CommandError(
                    'NAAN for an ARK must be 5 digits: {}'.format(opt.naan_str)
                )

        print(
            'Creating {} minter: {}...'.format(
                'DOI' if opt.is_doi else 'ARK', opt.prefix_str,
            )
        )

        try:
            self.add_shoulder_db_record()
        except django.db.utils.IntegrityError as e:
            # UNIQUE constraint failed: ezidapp_shoulder.name, ezidapp_shoulder.type
            raise django.core.management.CommandError(
                'Shoulder, name or type already exists. Error: {}'.format(str(e))
            )
        except Exception as e:
            raise django.core.management.CommandError(
                'Unable to create database record for shoulder. Error: {}'.format(
                    str(e)
                )
            )

        try:
            self.add_shoulder_file_record()
        except Exception as e:
            raise django.core.management.CommandError(
                'Unable to create shoulder record in master file. Error: {}'.format(
                    str(e)
                )
            )

        self.create_minter_database()

        print('Shoulder created successfully. Restart the EZID service to activate.')

    def assert_valid_name(self):
        name_set = {x.name for x in ezidapp.models.Shoulder.objects.all()}
        if self.opt.name_str not in name_set:
            print(
                'Datacenter must be one of:\n{}'.format(
                    '\n'.join(u'  {}'.format(x) for x in sorted(name_set))
                )
            )
            raise django.core.management.base.CommandError(
                'Invalid name: {}'.format(self.opt.name_str)
            )

    def assert_valid_datacenter(self):
        datacenter_set = {x.name for x in ezidapp.models.StoreDatacenter.objects.all()}
        if self.opt.datacenter_str not in datacenter_set:
            print(
                'Datacenter must be one of:\n{}'.format(
                    '\n'.join(u'  {}'.format(x) for x in sorted(datacenter_set))
                )
            )
            raise django.core.management.base.CommandError(
                'Invalid datacenter: {}'.format(self.opt.datacenter_str)
            )

    def add_shoulder_db_record(self):
        """Add a new shoulder row to the shoulder table"""
        ezidapp.models.Shoulder.objects.create(
            prefix=self.opt.prefix_str,
            type="DOI" if self.opt.is_doi else "ARK",
            name=self.opt.name_str,
            minter="ezid:/{}".format(self.opt.noid_str),
            datacenter=(
                ezidapp.models.StoreDatacenter.objects.get(name=self.opt.datacenter_str)
            ),
            crossrefEnabled=self.opt.is_crossref,
            isTest=self.opt.is_test,
        )

    def add_shoulder_file_record(self):
        """Add a new shoulder entry to the master shoulders file

        Example shoulder file record:

            :: doi:10.25494/P6
            type: shoulder
            manager: ezid
            #eziduser: sb-nceas
            name: Ocean Protection Council
            date: 2020.02.11
            minter: https://n2t.net/a/ezid/m/ark/d5494/p6


        """

        # datacite_str=None,
        # self.opt.datacenter_str=None,
        # prefix_shares_datacenter=None,

        _url = config.get("shoulders.url")

        assert _url.startswith(FILE_PROTOCOL)

        file_path = _url[len(FILE_PROTOCOL) :]
        now = datetime.datetime.now()

        with open(file_path, "a") as f:
            f.write(":: {}\n".format(self.opt.prefix_str))
            f.write("type: shoulder\n")
            f.write("manager: ezid\n")
            f.write("name: {}\n".format(self.opt.name_str))
            f.write("date: {:04d}.{:02d}.{:02d}\n".format(now.year, now.month, now.day))
            f.write("minter: ezid:/{}\n".format(self.opt.noid_str))

            if self.opt.is_crossref:
                f.write("registration_agency: datacite\n")

            if self.opt.datacenter_str:
                f.write("datacenter: {}".format(self.opt.datacenter_str))

            # registration_agency: datacite
            # datacenter: CDL.UCSB
            # prefix_shares_datacenter: true

            f.write("\n")

    def create_minter_database(self):
        """Create a new BerkeleyDB minter database"""
        template_path = utils.filesystem.abs_path("./resources/minter_template.hjson")
        with open(template_path) as f:
            template_str = f.read()

        template_str = template_str.replace("$NAAN$", self.opt.naan_str)
        template_str = template_str.replace("$PREFIX$", self.opt.shoulder_str)

        minter_dict = hjson.loads(template_str)
        d = {bytes(k): bytes(v) for k, v in minter_dict.items()}

        bdb = impl.nog_minter.open_bdb(
            self.opt.naan_str, self.opt.shoulder_str, root_path=None, flags_str="c"
        )
        bdb.clear()
        bdb.update(d)

    def dump_shoulders(self):
        for x in ezidapp.models.Shoulder.objects.all():
            print(x)

    def dump_datacenters(self):
        # for x in ezidapp.models.SearchDatacenter.objects.all():
        #     print(x)
        for x in ezidapp.models.StoreDatacenter.objects.all():
            print(x)
