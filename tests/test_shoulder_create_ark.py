"""Test the shoulder-create-ark management command
"""
import logging

import django.core.management
import freezegun

import ezidapp.models
import tests.util.sample as sample
import tests.util.util

log = logging.getLogger(__name__)


@freezegun.freeze_time('2010-10-11')
class TestShoulderCreateArk:
    def test_1000(self, capsys):
        """Creating basic ARK shoulder returns expected messages"""
        assert not ezidapp.models.Shoulder.objects.filter(
            prefix='ark:/91101/r01'
        ).exists()
        django.core.management.call_command(
            # <naan> <shoulder> <name>
            'shoulder-create-ark',
            '91101',
            'r01',
            'r01 test org',
        )
        out_str, err_str = capsys.readouterr()
        sample.assert_match(out_str, 'output')

    def test_1010(self, capsys):
        """Creating a basic ARK shoulder creates expected database entries"""
        assert not ezidapp.models.Shoulder.objects.filter(
            prefix='ark:/91101/r01'
        ).exists()
        django.core.management.call_command(
            # <naan> <shoulder> <name>
            'shoulder-create-ark',
            '91101',
            'r01',
            'r01 test org',
        )
        s = ezidapp.models.Shoulder.objects.filter(prefix='ark:/91101/r01').get()
        sample.assert_match(tests.util.util.shoulder_to_dict(s), 'basic')
        assert s.active
        assert not s.isSupershoulder
        assert not s.isTest

    def test_1020(self, capsys):
        """Creating an ARK shoulder with flags creates expected database entries"""
        assert not ezidapp.models.Shoulder.objects.filter(
            prefix='ark:/91101/r01'
        ).exists()
        django.core.management.call_command(
            # <naan> <shoulder> <name>
            'shoulder-create-ark',
            '91101',
            'r01',
            'r01 test org',
            '--super-shoulder',
            '--test',
        )
        s = ezidapp.models.Shoulder.objects.filter(prefix='ark:/91101/r01').get()
        sample.assert_match(tests.util.util.shoulder_to_dict(s), 'flags')
        assert s.active
        assert s.isSupershoulder
        assert s.isTest

    def test_1030(self, capsys, tmp_bdb_root):
        """Creating a full shoulder without specifying the shoulder causes the minters
        to be stored in a separate directory named 'unspecified'.
        """
        org_str = 'test org unspecified shoulder'
        namespace_str = 'ark:/99920/'
        assert not ezidapp.models.Shoulder.objects.filter(prefix=namespace_str).exists()
        django.core.management.call_command(
            # <naan> <shoulder> <name>
            'shoulder-create-ark',
            '99920',
            '',
            org_str,
            '--super-shoulder',
            '--test',
        )
        assert ezidapp.models.Shoulder.objects.filter(prefix=namespace_str).exists()
        ezid_uri = "ezid:/99920/unspecified"
        s = ezidapp.models.Shoulder.objects.filter(minter=ezid_uri).get()
        sample.assert_match(tests.util.util.shoulder_to_dict(s), 'unspecified')
        assert s.minter == ezid_uri
        assert s.name == org_str
        assert s.active
        assert s.isSupershoulder
        assert s.isTest
