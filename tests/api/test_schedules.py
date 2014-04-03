import pytest
import json
import yaml
import re
import time
import common.tower.license
import common.utils
import common.exceptions
import dateutil.rrule
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dateutil.parser import parse
from tests.api import Base_Api_Test

class RRule(dateutil.rrule.rrule):
    '''Sub-class rrule to support __str__'''

    FREQNAMES = ['YEARLY','MONTHLY','WEEKLY','DAILY','HOURLY','MINUTELY','SECONDLY']
    def __str__(self):
        parts = list()
        parts.append('FREQ=' + self.FREQNAMES[self._freq])
        if self._interval:
            parts.append('INTERVAL=' + str(self._interval))
        if self._wkst:
            parts.append('WKST=' + str(self._wkst))
        if self._count:
            parts.append('COUNT=' + str(self._count))

        for name, value in [
                ('BYSETPOS', self._bysetpos),
                ('BYMONTH', self._bymonth),
                ('BYMONTHDAY', self._bymonthday),
                ('BYYEARDAY', self._byyearday),
                ('BYWEEKNO', self._byweekno),
                ('BYWEEKDAY', self._byweekday),
                # ('BYWEEKDAY', (dateutil.rrule.weekdays[num] for num in self._byweekday)),
                ('BYHOUR', self._byhour),
                ('BYMINUTE', self._byminute),
                ('BYSECOND', self._bysecond),
                ]:
            if name == "BYWEEKDAY" and value:
                value = (dateutil.rrule.weekdays[num] for num in value)
            if value:
                parts.append(name + '=' + ','.join(str(v) for v in value))

        return '''DTSTART:%s RRULE:%s ''' % (re.sub(r'[:-]', '', self._dtstart.strftime("%Y%m%dT%H%M%SZ")), ';'.join(parts))

# Create fixture for testing unsupported RRULES
@pytest.fixture(params=[
    # empty string
    "",
    # missing RRULE
    "DTSTART:asdf asdf",
    # missing DTSTART
    "RRULE:asdf asdf",
    # empty RRULE
    "DTSTART:20030925T104941Z RRULE:",
    # empty DTSTART
    "DTSTART: RRULE:FREQ=DAILY;INTERVAL=10;COUNT=5",
    # multiple RRULES
    "DTSTART:20030925T104941Z RRULE:FREQ=DAILY;INTERVAL=10;COUNT=5 RRULE:FREQ=WEEKLY;INTERVAL=10;COUNT=1",
    # multiple DSTARTS
    "DTSTART:20030925T104941Z DTSTART:20130925T104941Z RRULE:FREQ=DAILY;INTERVAL=10;COUNT=5",
    # timezone
    "DTSTART:%s RRULE:FREQ=DAILY;INTERVAL=10;COUNT=5" % parse("Thu, 25 Sep 2003 10:49:41 -0300"),
    # taken from tower unittests
    "DTSTART:20140331T055000 RRULE:FREQ=MINUTELY;INTERVAL=10;COUNT=5",
    "RRULE:FREQ=MINUTELY;INTERVAL=10;COUNT=5",
    "FREQ=MINUTELY;INTERVAL=10;COUNT=5",
    "DTSTART:20240331T075000Z RRULE:FREQ=DAILY;INTERVAL=1;COUNT=10000000",
    "DTSTART;TZID=US-Eastern:19961105T090000 RRULE:FREQ=MINUTELY;INTERVAL=10;COUNT=5",
    "DTSTART:20140331T055000Z RRULE:FREQ=SECONDLY;INTERVAL=1",
    "DTSTART:20140331T055000Z RRULE:FREQ=SECONDLY",
    "DTSTART:20140331T055000Z RRULE:FREQ=YEARLY;BYDAY=20MO;INTERVAL=1",
    "DTSTART:20140331T055000Z RRULE:FREQ=MONTHLY;BYMONTHDAY=10,15;INTERVAL=1",
    "DTSTART:20140331T055000Z RRULE:FREQ=YEARLY;BYMONTH=1,2;INTERVAL=1",
    "DTSTART:20140331T055000Z RRULE:FREQ=YEARLY;BYYEARDAY=120;INTERVAL=1",
    "DTSTART:20140331T055000Z RRULE:FREQ=YEARLY;BYWEEKNO=10;INTERVAL=1",
    ])
def unsupported_rrule(request):
    return request.param

@pytest.fixture(params=["MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"])
def rrule_frequency(request):
    utcnow = datetime.utcnow()
    if request.param == "MINUTELY":
        dtstart = utcnow + relativedelta(minutes=-1, seconds=+30)
        freq = dateutil.rrule.MINUTELY
    elif request.param == "HOURLY":
        dtstart = utcnow + relativedelta(hours=-1, seconds=+30)
        freq = dateutil.rrule.HOURLY
    elif request.param == "DAILY":
        dtstart = utcnow + relativedelta(days=-1, seconds=+30)
        freq = dateutil.rrule.DAILY
    elif request.param == "WEEKLY":
        dtstart = utcnow + relativedelta(weeks=-1, seconds=+30)
        freq = dateutil.rrule.WEEKLY
    elif request.param == "MONTHLY":
        dtstart = utcnow + relativedelta(months=-1, seconds=+30)
        freq = dateutil.rrule.MONTHLY
    elif request.param == "YEARLY":
        dtstart = utcnow + relativedelta(years=-1, seconds=+30)
        freq = dateutil.rrule.YEARLY
    else:
        raise Exception("Unsupported frequency:%s" % request.param)
    return RRule(freq, dtstart=dtstart)

@pytest.fixture(scope="function")
def utcnow(request):
    return datetime.utcnow()

@pytest.fixture()
def minutely_schedule(request, random_project, utcnow):
    schedules_pg = random_project.get_related('schedules')
    rrule = RRule(dateutil.rrule.HOURLY, dtstart=utcnow, interval=1, count=5)
    payload = dict(name="minutely-%s" % common.utils.random_unicode(),
                   description="Update every minute (interval:1, count:5)",
                   rrule=str(rrule))
    obj = schedules_pg.post(payload)
    request.addfinalizer(obj.delete)
    return obj

@pytest.fixture()
def hourly_schedule(request, random_project, utcnow):
    schedules_pg = random_project.get_related('schedules')
    rrule = RRule(dateutil.rrule.HOURLY, dtstart=utcnow, interval=1, count=3)
    payload = dict(name="hourly-%s" % common.utils.random_unicode(),
                   description="Update hourly (interval:1, count:3)",
                   rrule=str(rrule))
    obj = schedules_pg.post(payload)
    request.addfinalizer(obj.delete)
    return obj

@pytest.fixture()
def daily_schedule(request, random_project, utcnow):
    schedules_pg = random_project.get_related('schedules')
    rrule = RRule(dateutil.rrule.DAILY, dtstart=utcnow, interval=2)
    payload = dict(name="daily-%s" % common.utils.random_unicode(),
                   description="Update daily (interval:2)",
                   rrule=str(rrule))
    obj = schedules_pg.post(payload)
    request.addfinalizer(obj.delete)
    return obj

@pytest.fixture()
def weekly_schedule(request, random_project, utcnow):
    return 'FIXME'

@pytest.fixture()
def monthly_schedule(request, random_project, utcnow):
    schedules_pg = random_project.get_related('schedules')
    rrule = RRule(dateutil.rrule.MONTHLY, dtstart=utcnow, interval=2)
    payload = dict(name="monthly-%s" % common.utils.random_unicode(),
                   description="Update monthly (interval:1)",
                   rrule=str(rrule))
    obj = schedules_pg.post(payload)
    request.addfinalizer(obj.delete)
    return obj

@pytest.fixture()
def yearly_schedule(request, random_project, utcnow):
    schedules_pg = random_project.get_related('schedules')

    last_year = utcnow + relativedelta(years=-1, seconds=+30)
    rrule = RRule(dateutil.rrule.YEARLY, dtstart=last_year)
    payload = dict(name="yearly-%s" % common.utils.random_unicode(),
                   description="Update every year, starting last",
                   rrule=str(rrule))
    obj = schedules_pg.post(payload)
    request.addfinalizer(obj.delete)
    return obj

@pytest.fixture()
def disabled_rrule(request, utcnow):
    return RRule(dateutil.rrule.YEARLY, dtstart=utcnow)

@pytest.fixture(scope="function")
def disabled_schedule(request, random_project, disabled_rrule):
    schedules_pg = random_project.get_related('schedules')

    payload = dict(name="disabled-%s" % common.utils.random_unicode(),
                   description="Disabled schedule",
                   enabled=False,
                   rrule=str(disabled_rrule))
    obj = schedules_pg.post(payload)
    request.addfinalizer(obj.delete)
    return obj

@pytest.fixture(scope="function")
def random_credential_scm_key_unlock_ASK(request, authtoken, api_credentials_pg, admin_user):
    # Create scm credential with scm_key_unlock='ASK'
    payload = dict(name="credentials-%s" % common.utils.random_unicode(),
                   description="SCM credential %s (scm_key_unlock:ASK)" % common.utils.random_unicode(),
                   kind='scm',
                   username='git',
                   scm_key_unlock='ASK',
                   user=admin_user.id,
                  )
    obj = api_credentials_pg.post(payload)
    request.addfinalizer(obj.delete)
    return obj

@pytest.fixture(scope="function")
def random_project_with_credential_prompt(request, authtoken, api_projects_pg, random_organization, random_credential_scm_key_unlock_ASK):
    # Create project
    payload = dict(name="project-%s" % common.utils.random_unicode(),
                   organization=random_organization.id,
                   scm_type='git',
                   scm_url='git@github.com:ansible/ansible-examples.git',
                   scm_key_unlock='ASK',
                   credential=random_credential_scm_key_unlock_ASK.id,
                  )
    obj = api_projects_pg.post(payload)
    request.addfinalizer(obj.delete)
    return obj

@pytest.mark.skip_selenium
@pytest.mark.nondestructive
# @pytest.mark.usefixtures('authtoken', 'backup_license', 'install_license_1000')
@pytest.mark.usefixtures('authtoken')
class Test_Project_Schedules(Base_Api_Test):
    '''
    Test basic schedule CRUD operations: [GET, POST, PUT, PATCH, DELETE]

    Test schedule rrule support ...
      1. valid should be accepted
      2. invalid should return BadRequest

    Test related->project is correct?

    Create single schedule (rrule), verify ...
      1. project.next_update is expected
      2. project is updated at desired time

    Create multiple schedules (rrules), verify ...
      1. project.next_update is expected
      2. project is updated at desired time

    RBAC
      - admin can view/create/update/delete schedules
      - org_admin can view/create/update/delete schedules
      - user can *only* view schedules
      - user w/ update perm can *only* view/create/update schedules
    '''

    def test_schedule_empty(self, random_project):
        '''assert a fresh project has no schedules'''
        schedules_pg = random_project.get_related('schedules')
        assert schedules_pg.count == 0

    def test_schedule_post_invalid(self, random_project, unsupported_rrule):
        '''assert unsupported rrules are rejected'''
        schedules_pg = random_project.get_related('schedules')

        payload = dict(name="schedule-%s" % common.utils.random_unicode(),
                       description="%s" % common.utils.random_unicode(),
                       enabled=True,
                       rrule=str(unsupported_rrule))
        with pytest.raises(common.exceptions.BadRequest_Exception):
            schedules_pg.post(payload)

    def test_schedule_post_duplicate(self, random_project, disabled_schedule):
        '''assert duplicate schedules are rejected'''
        schedules_pg = random_project.get_related('schedules')

        payload = dict(name=disabled_schedule.name,
                       rrule=disabled_schedule.rrule)
        with pytest.raises(common.exceptions.Duplicate_Exception):
            schedules_pg.post(payload)

    def test_schedule_post_disabled(self, random_project, disabled_schedule):
        '''assert can POST disabled schedules'''
        assert not disabled_schedule.enabled
        schedules_pg = random_project.get_related('schedules')

        # Appears in related->schedules
        assert disabled_schedule.id in [sched.id for sched in schedules_pg.results]

    def test_schedule_post_past(self, random_project):
        '''assert creating a schedule with only past occurances'''
        schedules_pg = random_project.get_related('schedules')

        # commemorate first 10 years of pearl_harbor
        pearl_harbor = parse("Dec 7 1942")
        rrule = RRule(dateutil.rrule.YEARLY, dtstart=pearl_harbor, count=10, interval=1)
        payload = dict(name="schedule-%s" % common.utils.random_unicode(),
                       description="Commemorate the attack on pearl harbor (%s)" % common.utils.random_unicode(),
                       rrule=str(rrule))
        schedule_pg = schedules_pg.post(payload)
        assert schedule_pg.dtstart == pearl_harbor.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert schedule_pg.next_run is None

    def test_schedule_post_future(self, random_project):
        '''assert creating a schedule with only future occurances'''
        schedules_pg = random_project.get_related('schedules')

        # celebrate Odyssey three date
        odyssey_three = parse("Jan 1 2061")
        rrule = RRule(dateutil.rrule.YEARLY, dtstart=odyssey_three, interval=1)
        payload = dict(name="schedule-%s" % common.utils.random_unicode(),
                       description="2061: Odyssey Three (%s)" % common.utils.random_unicode(),
                       rrule=str(rrule))
        schedule_pg = schedules_pg.post(payload)
        assert schedule_pg.dtstart == odyssey_three.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert schedule_pg.next_run == rrule[0].isoformat() + 'Z'

    def test_schedule_post_overlap(self, random_project, utcnow):
        '''assert creating a schedule with past and future occurances'''
        schedules_pg = random_project.get_related('schedules')

        last_week = utcnow + relativedelta(weeks=-1)
        next_week = utcnow + relativedelta(weeks=+1)
        rrule = RRule(dateutil.rrule.DAILY, dtstart=last_week, until=next_week)
        payload = dict(name="schedule-%s" % common.utils.random_unicode(),
                       description="Daily project update",
                       rrule=str(rrule))
        schedule_pg = schedules_pg.post(payload)
        assert schedule_pg.next_run == rrule.after(utcnow).isoformat() + 'Z'

    def test_schedule_put(self, random_project):
        '''assert successful schedule PUT'''
        schedules_pg = random_project.get_related('schedules')
        assert schedules_pg.count > 0

        schedule_pg = schedules_pg.results[0]
        # change description
        old_desc = schedule_pg.description
        new_desc = common.utils.random_unicode()
        schedule_pg.description = new_desc
        # PUT changes
        schedule_pg.put()
        # GET updates
        schedule_pg.get()
        # Was the description changed?
        assert schedule_pg.description == new_desc

    def test_schedule_patch(self, random_project):
        '''assert successful schedule PATCH'''
        schedules_pg = random_project.get_related('schedules')
        assert schedules_pg.count > 0

        schedule_pg = schedules_pg.results[0]
        old_desc = schedule_pg.description
        new_desc = common.utils.random_unicode()
        # PATCH changes
        schedule_pg.patch(description=new_desc)
        # GET updates
        schedule_pg.get()
        assert schedule_pg.description == new_desc

    def test_schedule_readonly_fields(self, api_schedules_pg, random_project):
        '''assert read-only fields are not writable'''
        schedules_pg = random_project.get_related('schedules')

        # Create a schedule
        rrule = RRule(dateutil.rrule.MINUTELY, dtstart=datetime.utcnow(), count=2, interval=60)
        payload = dict(name="schedule-%s" % common.utils.random_unicode(),
                       description="Update (interval:60, count:2)",
                       rrule=str(rrule))
        schedule_pg = schedules_pg.post(payload)

        # PUT read-only fields
        ro_schedule = api_schedules_pg.get(id=schedule_pg.id).results[0]
        ro_schedule.dtstart = "A new dtstart"
        ro_schedule.dtend = "Some dtend"
        ro_schedule.next_run = "Next run please"
        # PUT changes
        ro_schedule.put()
        # GET updates
        ro_schedule = api_schedules_pg.get(id=schedule_pg.id).results[0]
        assert schedule_pg.dtstart == ro_schedule.dtstart
        assert schedule_pg.dtend == ro_schedule.dtend
        assert schedule_pg.next_run == ro_schedule.next_run

    def test_schedule_update_with_credential_prompt(self, random_project_with_credential_prompt, utcnow):
        '''FIXME'''
        schedules_pg = random_project_with_credential_prompt.get_related('schedules')

        # Create a schedule
        rrule = RRule(dateutil.rrule.MINUTELY, dtstart=utcnow + relativedelta(seconds=+30), count=1)
        payload = dict(name="schedule-%s" % common.utils.random_unicode(),
                       description="Update %s (interval:60, count:2)" % common.utils.random_unicode(),
                       rrule=str(rrule))
        schedule_pg = schedules_pg.post(payload)

        # Is the next_run what we expect?
        assert schedule_pg.next_run == rrule.after(utcnow).isoformat() + 'Z'

        # wait 2 minutes for 1 scheduled update to complete
        unified_jobs_pg = schedule_pg.get_related('unified_jobs')
        unified_jobs_pg = common.utils.wait_until(unified_jobs_pg, 'count', 1,
            interval=15, verbose=True, timeout=60*2)

        # Ensure correct number of scheduled launches occurred
        assert unified_jobs_pg.count == 1

        # Ensure the job status is failed
        assert unified_jobs_pg.results[0].status == 'failed'

        # Is the next_run still what we expect?
        schedule_pg.get()
        assert schedule_pg.next_run is None

    def test_schedule_delete(self, random_project):
        '''assert successful schedule DELETE'''
        schedules_pg = random_project.get_related('schedules')
        assert schedules_pg.count > 0
        for schedule in schedules_pg.results:
            schedule.delete()

        schedules_pg.get()
        assert schedules_pg.count == 0

    def test_schedule_update_count1(self, random_project, utcnow, rrule_frequency):
        '''assert a schedule launches at the proper interval'''
        schedules_pg = random_project.get_related('schedules')

        # Create schedule
        payload = dict(name="schedule-%s-%s" % (rrule_frequency._freq, common.utils.random_unicode()),
                       description="Update every %s" % rrule_frequency._freq,
                       rrule=str(rrule_frequency))
        print rrule_frequency
        schedule_pg = schedules_pg.post(payload)

        # Is the next_run what we expect?
        assert schedule_pg.next_run == rrule_frequency.after(utcnow).isoformat() + 'Z'

        # wait 2 minutes for 1 scheduled update to complete
        unified_jobs_pg = schedule_pg.get_related('unified_jobs')
        unified_jobs_pg = common.utils.wait_until(unified_jobs_pg, 'count', 1,
            interval=15, verbose=True, timeout=60*2)

        # Ensure correct number of scheduled launches occured
        assert unified_jobs_pg.count == 1

        # Is the next_run still what we expect?
        schedule_pg.get()
        assert schedule_pg.next_run == rrule_frequency.after(datetime.utcnow()).isoformat() + 'Z'

    def test_schedule_update_minutely_count3(self, random_project, utcnow):
        '''assert a minutely schedule launches properly'''
        schedules_pg = random_project.get_related('schedules')

        # Create schedule
        now = utcnow + relativedelta(seconds=+30)
        now_plus_5m = now + relativedelta(minutes=+5)
        rrule = RRule(dateutil.rrule.MINUTELY, dtstart=now, count=3, until=now_plus_5m)
        payload = dict(name="minutely-%s" % common.utils.random_unicode(),
                       description="Update every minute (count:3)",
                       rrule=str(rrule))
        schedule_pg = schedules_pg.post(payload)

        # Is the next_run what we expect?
        assert schedule_pg.next_run == rrule.after(utcnow).isoformat() + 'Z'

        # wait 5 minutes for scheduled updates to complete
        unified_jobs_pg = schedule_pg.get_related('unified_jobs')
        unified_jobs_pg = common.utils.wait_until(unified_jobs_pg, 'count', rrule.count(),
            interval=15, verbose=True, timeout=60*5)

        # ensure scheduled project updates ran
        assert unified_jobs_pg.count == rrule.count()

        # ensure the schedule has no remaining runs
        schedule_pg.get()
        assert schedule_pg.next_run is None

    # SEE JIRA(AC-1106)
    def test_schedule_project_delete(self, api_projects_pg, api_schedules_pg, random_organization):
        '''assert that schedules are deleted when a project is deleted'''
        # create a project
        payload = dict(name="project-%s" % common.utils.random_unicode(),
                       organization=random_organization.id,
                       scm_type='hg',
                       scm_url='https://bitbucket.org/jlaska/ansible-helloworld')
        project_pg = api_projects_pg.post(payload)

        # create schedules
        schedules_pg = project_pg.get_related('schedules')
        assert schedules_pg.count == 0

        schedule_ids = list()
        for repeat in [dateutil.rrule.WEEKLY, dateutil.rrule.MONTHLY, dateutil.rrule.YEARLY]:
            rrule = RRule(repeat, dtstart=datetime.utcnow())
            payload = dict(name="schedule-%s" % common.utils.random_unicode(),
                           description=common.utils.random_unicode(),
                           rrule=str(rrule))
            print rrule
            schedule_pg = schedules_pg.post(payload)
            schedule_ids.append(schedule_pg.id)

        # assert the schedules exist
        schedules_pg = project_pg.get_related('schedules')
        assert schedules_pg.count == 3

        # delete the project
        project_pg.delete()

        # assert the project schedules are gone
        remaining_schedules = api_schedules_pg.get(id__in=','.join([str(sid) for sid in schedule_ids]))
        assert remaining_schedules.count == 0
