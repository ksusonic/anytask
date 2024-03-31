# -*- coding: utf-8 -*-

"""
This file demonstrates writing tests using the unittest module. These will pass
when you run "manage.py test".

Replace this with more appropriate tests for your application.
"""
from io import StringIO
from unittest import skipIf

from django.core.management import call_command
from django.conf import settings
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.test.testcases import SerializeMixin

from schools.models import School
from courses.models import Course, IssueField
from groups.models import Group
from years.models import Year
from tasks.models import Task
from issues.models import Issue, File, Event
from issues.model_issue_status import IssueStatus

from django.core.files.uploadedfile import SimpleUploadedFile
from mock import patch
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from django.urls import reverse
from storages.backends.s3boto3 import S3Boto3Storage

import issues.views
import anyrb.views
import anyrb.unpacker
from storage import S3OverlayStorage


def is_s3_reachable():
    try:
        return S3Boto3Storage().listdir('/') is not None
    except Exception:
        return False


IS_S3_REACHABLE = is_s3_reachable()


def save_result_html(html):
    with open(r'../test_page.html', 'w') as f:
        f.write(html)


class CreateTest(TestCase):
    def test_issue_create_filled(self):
        year = Year.objects.create(start_year=2016)
        group = Group.objects.create(name='name_groups', year=year)
        course = Course.objects.create(name='course_name',
                                       year=year)
        course.groups.set([group])
        course.save()
        task = Task.objects.create(title='task',
                                   course=course)
        student = User.objects.create_user(username='student',
                                           password='password')
        responsible = User.objects.create_user(username='responsible',
                                               password='password')
        followers = [User.objects.create_user(username='follower1',
                                              password='password')]

        status = IssueStatus.objects.get(name=u'{"ru": "Зачтено", "en": "Accepted"}')

        issue = Issue()
        issue.student = student
        issue.task = task
        issue.mark = 3
        issue.responsible = responsible
        issue.status_field = status
        issue.save()
        issue.followers.set(followers)
        issue.save()
        issue_id = issue.id

        issue = Issue.objects.get(id=issue_id)

        self.assertIsInstance(issue, Issue)
        self.assertEqual(issue.student, student)
        self.assertEqual(issue.task, task)
        self.assertEqual(issue.mark, 3)
        self.assertEqual(issue.responsible, responsible)
        self.assertEqual(issue.status_field, status)
        self.assertCountEqual(issue.followers.all(), followers)


@override_settings(LANGUAGE_CODE='en-EN', LANGUAGES=(('en', 'English'),))
class ViewsTest(TestCase):
    def setUp(self):
        self.teacher_password = 'password1'
        self.teacher = User.objects.create_user(username='teacher',
                                                password=self.teacher_password)
        self.teacher.first_name = 'teacher_name'
        self.teacher.last_name = 'teacher_last_name'
        self.teacher.save()

        self.student_password = 'password2'
        self.student = User.objects.create_user(username='student',
                                                password=self.student_password)
        self.student.first_name = 'student_name'
        self.student.last_name = 'student_last_name'
        self.student.save()

        self.year = Year.objects.create(start_year=2016)

        self.group = Group.objects.create(name='group_name',
                                          year=self.year)
        self.group.students.set([self.student])
        self.group.save()

        self.course = Course.objects.create(name='course_name',
                                            year=self.year)
        self.course.groups.set([self.group])
        self.course.teachers.set([self.teacher])
        self.course.issue_fields.set(IssueField.objects.exclude(id=10).exclude(id=11).exclude(id=12))
        self.course.save()

        self.school = School.objects.create(name='school_name',
                                            link='school_link')
        self.school.courses.set([self.course])
        self.school.save()

        self.task = Task.objects.create(title='task_title',
                                        course=self.course,
                                        score_max=10)

    def test_get_or_create_anonymously(self):
        client = self.client

        # get get_or_create page
        response = client.get(reverse(issues.views.get_or_create,
                                      kwargs={'task_id': self.task.id, 'student_id': self.student.id}))
        self.assertEqual(response.status_code, 302, "Need login for get_or_create")

        issue = Issue()
        issue.student = self.student
        issue.task = self.task
        issue.save()

        # get issue_page page
        response = client.get(reverse(issues.views.issue_page,
                                      kwargs={'issue_id': issue.id}))
        self.assertEqual(response.status_code, 302, "Need login for issue_page")

    def test_get_or_create_with_teacher(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        # get create task page
        response = client.get(reverse(issues.views.get_or_create,
                                      kwargs={'task_id': self.task.id, 'student_id': self.student.id}), follow=True)
        self.assertEqual(response.status_code, 200, "Can't get get_or_create via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect from get_or_create")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # title
        self.assertEqual(html.find('title').string.strip().strip('\n'), u'task_title | student_last_name student_name')

        # navbar
        navbar = html.nav
        navbar_links = navbar.ul('li')
        self.assertEqual(len(navbar_links), 2, 'navbar must have only 2 link')
        self.assertEqual(navbar_links[0].a['href'], '/course/1#tasks-tab', 'navbar 1st link wrong')
        self.assertEqual(navbar_links[1].a['href'], '/course/1/queue', 'navbar 2nd link wrong')

        # breadcrumbs
        breadcrumbs = container.find('ul', 'breadcrumb')('li')
        self.assertEqual(len(breadcrumbs), 4, 'breadcrumbs len is not 4')
        self.assertEqual(breadcrumbs[0].a['href'], u'/', 'breadcrumbs 1st link wrong')
        self.assertEqual(breadcrumbs[1].a['href'], u'/school/school_link', 'breadcrumbs 2nd link wrong')
        self.assertEqual(breadcrumbs[1].a.string.strip().strip('\n'), u'school_name', 'breadcrumbs 2nd text wrong')
        self.assertEqual(breadcrumbs[2].a['href'], u'/course/1', 'breadcrumbs 3rd link wrong')
        self.assertEqual(breadcrumbs[2].a.string.strip().strip('\n'), u'course_name', 'breadcrumbs 3rd text wrong')
        self.assertEqual(breadcrumbs[3].string.strip().strip('\n'),
                         u'Issue: 1 task_title',
                         'breadcrumbs 4th text wrong')

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(history, [])

        # info
        info = container.find('div', {'id': 'accordion2'})
        self.assertEqual(len(info('div', 'card')), 8, 'Issue fields len is not 8')
        labels = info('div', 'accordion2-label')
        results = info('div', 'accordion2-result')
        forms = info('form')
        self.assertEqual(len(forms), 4, 'Issue field forms len is not 8')
        self.assertEqual(labels[0].string.strip().strip('\n'), 'Course:', '1st issue field label wrong')
        self.assertEqual(results[0].a['href'], '/course/1', '1st issue field link wrong')
        self.assertEqual(results[0].a.string.strip().strip('\n'), 'course_name', '1st issue field link text wrong')

        self.assertEqual(labels[1].string.strip().strip('\n'), 'Problem:', '2nd issue field label wrong')
        self.assertEqual(results[1].a.string.strip().strip('\n'), 'task_title', '2nd issue field text wrong')

        self.assertEqual(labels[2].string.strip().strip('\n'), 'Student:', '3rd issue field label wrong')
        self.assertEqual(results[2].a['href'], '/users/student/', '3rd issue field link wrong')
        self.assertEqual(results[2].a.string.strip().strip('\n'),
                         'student_last_name student_name',
                         '3rd issue field link text wrong')

        self.assertEqual(labels[3].a.string.strip().strip('\n'), 'TA', '4th issue field label text wrong')
        self.assertEqual(labels[3].a['data-target'], u'#collapse5', '4th issue field label data-target wrong')
        self.assertEqual(results[3].string.strip().strip('\n'), '---', '4th issue field text wrong')
        self.assertEqual(forms[0].find('input', {'name': 'form_name'})['value'],
                         'responsible_name_form',
                         '4th issue field input form_name wrong')
        self.assertEqual(len(forms[0]('option')), 1, '4th issue field select option len is not 1')
        self.assertEqual(forms[0]('option')[0]['value'], str(self.teacher.id))
        self.assertEqual(forms[0]('option')[0].string.strip().strip('\n'),
                         'teacher_name teacher_last_name',
                         '4th issue field select option text wrong')
        self.assertEqual(len(forms[0]('button')), 2, '4th issue field button len is not 2')
        self.assertEqual(forms[0]('button')[0].string.strip().strip('\n'),
                         'Save',
                         '4th issue field 1st button wrong ')
        self.assertEqual(forms[0]('button')[1].string.strip().strip('\n'),
                         'Me',
                         '4th issue field 2st button wrong ')

        self.assertEqual(labels[4].a.string.strip().strip('\n'), 'Viewers', '5th issue field label text wrong')
        self.assertEqual(labels[4].a['data-target'], u'#collapse6', '5th issue field label data-target wrong')
        self.assertEqual(results[4].string.strip().strip('\n'), '---', '5th issue field text wrong')
        self.assertEqual(forms[1].find('input', {'name': 'form_name'})['value'],
                         'followers_names_form',
                         '5th issue field input form_name wrong')
        self.assertEqual(len(forms[1]('option')), 1, '5th issue field select option len is not 1')
        self.assertEqual(forms[1]('option')[0]['value'], str(self.teacher.id))
        self.assertEqual(forms[1]('option')[0].string.strip().strip('\n'),
                         'teacher_name teacher_last_name',
                         '5th issue field select option text wrong')
        self.assertEqual(len(forms[1]('button')), 2, '5th issue field button len is not 2')
        self.assertEqual(forms[1]('button')[0].string.strip().strip('\n'),
                         'Save',
                         '5th issue field 1st button wrong ')
        self.assertEqual(forms[1]('button')[1].string.strip().strip('\n'),
                         'Me',
                         '5th issue field 2st button wrong ')

        self.assertEqual(labels[5].a.string.strip().strip('\n'), 'Status', '6th issue field label text wrong')
        self.assertEqual(labels[5].a['data-target'], u'#collapse7', '6th issue field label data-target wrong')
        self.assertEqual(results[5].string.strip().strip('\n'), u'Новый', '6th issue field text wrong')
        self.assertEqual(forms[2].find('input', {'name': 'form_name'})['value'],
                         'status_form',
                         '6th issue field input form_name wrong')
        self.assertEqual(len(forms[2]('option')), 3, '6th issue field select option len is not 4')
        self.assertIn('value="3"', str(forms[2]('option')[0]), '6th issue field select 1st option value wrong')
        self.assertIn(u'На проверке',
                      str(forms[2]('option')[0]),
                      '6th issue field select 1st option text wrong')
        self.assertIn('value="4"', str(forms[2]('option')[1]), '6th issue field select 2st option value wrong')
        self.assertIn(u'На доработке',
                      str(forms[2]('option')[1]),
                      '6th issue field select 2st option text wrong')
        self.assertIn('value="5"', str(forms[2]('option')[2]), '6th issue field select 3st option value wrong')
        self.assertIn(u'Зачтено',
                      str(forms[2]('option')[2]),
                      '6th issue field select 3st option text wrong')
        self.assertEqual(len(forms[2]('button')), 1, '6th issue field button len is not 1')
        self.assertEqual(forms[2]('button')[0].string.strip().strip('\n'),
                         'Save',
                         '6th issue field 1st button wrong ')

        self.assertEqual(labels[6].a.string.strip().strip('\n'), 'Mark', '7th issue field label text wrong')
        self.assertEqual(labels[6].a['data-target'], u'#collapse8', '7th issue field label data-target wrong')
        self.assertEqual(results[6].string.strip().strip('\n'), '0 out of 10', '7th issue field text wrong')
        self.assertEqual(forms[3].find('input', {'name': 'form_name'})['value'],
                         'mark_form',
                         '7th issue field input form_name wrong')
        self.assertEqual(forms[3].find('input', {'id': 'max_mark'})['value'],
                         '10',
                         '7th issue field input max_mark wrong')
        self.assertIsNotNone(forms[3].find('input', {'name': 'mark'}), '7th issue field mark input wrong')
        self.assertEqual(len(forms[3]('button')), 2, '7th issue field button len is not 2')
        self.assertEqual(forms[3]('button')[0].string.strip().strip('\n'),
                         'Save',
                         '7th issue field 1st button wrong ')
        self.assertEqual(forms[3]('button')[1].string.strip().strip('\n'),
                         'Зачтено',
                         '7th issue field 2st button wrong ')

        self.assertEqual(labels[7].string.strip().strip('\n'), 'Submit due:', '8th issue field label wrong')
        self.assertEqual(results[7].string.strip().strip('\n'), '', '8th issue field text wrong')

    def test_post_responsible_name_form_send_button_with_teacher(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        # post
        response = client.post(reverse(issues.views.issue_page, kwargs={'issue_id': issue.id}),
                               {'form_name': 'responsible_name_form',
                                'responsible_name': str(self.teacher.id)},
                               follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        self.assertEqual(history[0].find('div', 'history-body').find('p').string.strip().strip('\n'),
                         'Task reviewer changed: teacher_last_name teacher_name',
                         'Wrong comment text')

        # info
        info = container.find('div', {'id': 'accordion2'})
        results = info('div', 'accordion2-result')
        forms = info('form')
        self.assertEqual(results[3].a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         '4th issue field text wrong')
        self.assertEqual(results[3].a['href'],
                         '/users/teacher/',
                         '4th issue field text link wrong')
        self.assertEqual(len(forms[0]('option')), 1, '4th issue field select option len is not 1')
        self.assertIsNotNone(forms[0]('option')[0]['selected'], '4th issue field select option not selected')
        self.assertEqual(forms[0]('option')[0]['value'], str(self.teacher.id))
        self.assertEqual(forms[0]('option')[0].string.strip().strip('\n'),
                         'teacher_name teacher_last_name',
                         '4th issue field select option text wrong')

    def test_post_responsible_name_form_me_button_with_teacher(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        # post
        response = client.post(reverse(issues.views.issue_page, kwargs={'issue_id': issue.id}),
                               {'form_name': 'responsible_name_form',
                                'Me': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        self.assertEqual(history[0].find('div', 'history-body').find('p').string.strip().strip('\n'),
                         'Task reviewer changed: teacher_last_name teacher_name',
                         'Wrong comment text')

        # info
        info = container.find('div', {'id': 'accordion2'})
        results = info('div', 'accordion2-result')
        forms = info('form')
        self.assertEqual(results[3].a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         '4th issue field text wrong')
        self.assertEqual(results[3].a['href'],
                         '/users/teacher/',
                         '4th issue field text link wrong')
        self.assertEqual(len(forms[0]('option')), 1, '4th issue field select option len is not 1')
        self.assertIsNotNone(forms[0]('option')[0]['selected'], '4th issue field select option not selected')
        self.assertEqual(forms[0]('option')[0]['value'], str(self.teacher.id))
        self.assertEqual(forms[0]('option')[0].string.strip().strip('\n'),
                         'teacher_name teacher_last_name',
                         '4th issue field select option text wrong')

    def test_post_followers_names_form_send_button_with_teacher(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        # post
        response = client.post(reverse(issues.views.issue_page, kwargs={'issue_id': issue.id}),
                               {'form_name': 'followers_names_form',
                                'followers_names': [str(self.teacher.id)]}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        self.assertEqual(history[0].find('div', 'history-body').find('p').string.strip().strip('\n'),
                         'Viewers teacher_last_name teacher_name',
                         'Wrong comment text')

        # info
        info = container.find('div', {'id': 'accordion2'})
        results = info('div', 'accordion2-result')
        forms = info('form')
        self.assertEqual(results[4].a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         '5th issue field text wrong')
        self.assertEqual(results[4].a['href'],
                         '/users/teacher/',
                         '4th issue field text link wrong')
        self.assertEqual(len(forms[1]('option')), 1, '5th issue field select option len is not 1')
        self.assertIsNotNone(forms[1]('option')[0]['selected'], '5th issue field select option not selected')
        self.assertEqual(forms[1]('option')[0]['value'], str(self.teacher.id))
        self.assertEqual(forms[1]('option')[0].string.strip().strip('\n'),
                         'teacher_name teacher_last_name',
                         '5th issue field select option text wrong')

    def test_post_followers_names_form_me_button_with_teacher(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        # post
        response = client.post(reverse(issues.views.issue_page, kwargs={'issue_id': issue.id}),
                               {'form_name': 'followers_names_form',
                                'Me': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        self.assertEqual(history[0].find('div', 'history-body').find('p').string.strip().strip('\n'),
                         'Viewers teacher_last_name teacher_name',
                         'Wrong comment text')

        # info
        info = container.find('div', {'id': 'accordion2'})
        results = info('div', 'accordion2-result')
        forms = info('form')
        self.assertEqual(results[4].a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         '5th issue field text wrong')
        self.assertEqual(results[4].a['href'],
                         '/users/teacher/',
                         '4th issue field text link wrong')
        self.assertEqual(len(forms[1]('option')), 1, '5th issue field select option len is not 1')
        self.assertIsNotNone(forms[1]('option')[0]['selected'], '5th issue field select option not selected')
        self.assertEqual(forms[1]('option')[0]['value'], str(self.teacher.id))
        self.assertEqual(forms[1]('option')[0].string.strip().strip('\n'),
                         'teacher_name teacher_last_name',
                         '5th issue field select option text wrong')

    def test_post_status_send_button_with_teacher(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        # post
        response = client.post(reverse(issues.views.issue_page, kwargs={'issue_id': issue.id}),
                               {'form_name': 'status_form',
                                'status': '4'}, follow=True)

        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        self.assertEqual(history[0].find('div', 'history-body').find('p').string.strip().strip('\n'),
                         'Status updated: На доработке',
                         'Wrong comment text')

        # info
        info = container.find('div', {'id': 'accordion2'})
        results = info('div', 'accordion2-result')
        self.assertEqual(results[5].string.strip().strip('\n'), u'На доработке', '6th issue field text wrong')

    def test_post_mark_form_send_button_with_teacher(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        # post
        response = client.post(reverse(issues.views.issue_page, kwargs={'issue_id': issue.id}),
                               {'form_name': 'mark_form',
                                'mark': '3'}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        self.assertEqual(history[0].find('div', 'history-body').find('p').string.strip().strip('\n'),
                         'Grade mark changed to 3',
                         'Wrong comment text')

        # info
        info = container.find('div', {'id': 'accordion2'})
        results = info('div', 'accordion2-result')
        self.assertEqual(results[5].string.strip().strip('\n'), 'Новый', '6th issue field text wrong')
        self.assertEqual(results[6].string.strip().strip('\n'), '3 out of 10', '7th issue field text wrong')

    def test_post_mark_form_accept_button_with_teacher(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        # post
        response = client.post(reverse(issues.views.issue_page, kwargs={'issue_id': issue.id}),
                               {'form_name': 'mark_form',
                                'mark': '3',
                                'Accepted': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 2, 'History len is not 2')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        self.assertEqual(history[0].find('div', 'history-body').find('p').string.strip().strip('\n'),
                         'Status updated: Зачтено',
                         'Wrong comment text')
        self.assertEqual(history[1].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[1].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        self.assertEqual(history[1].find('div', 'history-body').find('p').string.strip().strip('\n'),
                         'Grade mark changed to 3',
                         'Wrong comment text')

        # info
        info = container.find('div', {'id': 'accordion2'})
        results = info('div', 'accordion2-result')
        self.assertEqual(results[5].string.strip().strip('\n'), 'Зачтено', '6th issue field text wrong')
        self.assertEqual(results[6].string.strip().strip('\n'), '3 out of 10', '7th issue field text wrong')

    def test_comment_with_teacher(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        # post
        response = client.post(reverse(issues.views.upload),
                               {'comment': 'test_comment',
                                'files[]': '',
                                'issue_id': str(issue.id),
                                'form_name': 'comment_form',
                                'update_issue': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        self.assertEqual(history[0].find('div', 'history-body').find('div', 'not-sanitize').string.strip().strip('\n'),
                         'test_comment',
                         'Wrong comment text')

    def test_get_or_create_with_student(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.student.username, password=self.student_password),
                        "Can't login via student")

        # get create task page
        response = client.get(reverse(issues.views.get_or_create,
                                      kwargs={'task_id': self.task.id, 'student_id': self.student.id}), follow=True)
        self.assertEqual(response.status_code, 200, "Can't get get_or_create via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect from get_or_create")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # title
        self.assertEqual(html.find('title').string.strip().strip('\n'), u'task_title | student_last_name student_name')

        # navbar
        navbar = html.nav
        navbar_links = navbar.ul('li')
        self.assertEqual(len(navbar_links), 1, 'navbar must have only 1 link')
        self.assertEqual(navbar_links[0].a['href'], '/course/1#tasks-tab', 'navbar 1st link wrong')

        # breadcrumbs
        breadcrumbs = container.find('ul', 'breadcrumb')('li')
        self.assertEqual(len(breadcrumbs), 4, 'breadcrumbs len is not 4')
        self.assertEqual(breadcrumbs[0].a['href'], u'/', 'breadcrumbs 1st link wrong')
        self.assertEqual(breadcrumbs[1].a['href'], u'/school/school_link', 'breadcrumbs 2nd link wrong')
        self.assertEqual(breadcrumbs[1].a.string.strip().strip('\n'), u'school_name', 'breadcrumbs 2nd text wrong')
        self.assertEqual(breadcrumbs[2].a['href'], u'/course/1', 'breadcrumbs 3rd link wrong')
        self.assertEqual(breadcrumbs[2].a.string.strip().strip('\n'), u'course_name', 'breadcrumbs 3rd text wrong')
        self.assertEqual(breadcrumbs[3].string.strip().strip('\n'),
                         u'Issue: 1 task_title',
                         'breadcrumbs 4th text wrong')

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(history, [])

        # info
        info = container.find('div', {'id': 'accordion2'})
        self.assertEqual(len(info('div', 'card')), 8, 'Issue fields len is not 8')
        labels = info('div', 'accordion2-label')
        results = info('div', 'accordion2-result')
        forms = info('form')
        self.assertEqual(len(forms), 0, 'Issue field forms len is not 0')
        self.assertEqual(labels[0].string.strip().strip('\n'), 'Course:', '1st issue field label wrong')
        self.assertEqual(results[0].a['href'], '/course/1', '1st issue field link wrong')
        self.assertEqual(results[0].a.string.strip().strip('\n'), 'course_name', '1st issue field link text wrong')

        self.assertEqual(labels[1].string.strip().strip('\n'), 'Problem:', '2nd issue field label wrong')
        self.assertEqual(results[1].a.string.strip().strip('\n'), 'task_title', '2nd issue field text wrong')

        self.assertEqual(labels[2].string.strip().strip('\n'), 'Student:', '3rd issue field label wrong')
        self.assertEqual(results[2].a['href'], '/users/student/', '3rd issue field link wrong')
        self.assertEqual(results[2].a.string.strip().strip('\n'),
                         'student_last_name student_name',
                         '3rd issue field link text wrong')

        self.assertEqual(labels[3].string.strip().strip('\n'), 'TA:', '4th issue field label text wrong')
        self.assertEqual(results[3].string.strip().strip('\n'), '---', '4th issue field text wrong')

        self.assertEqual(labels[4].string.strip().strip('\n'), 'Viewers:', '5th issue field label text wrong')
        self.assertEqual(results[4].string.strip().strip('\n'), '---', '5th issue field text wrong')

        self.assertEqual(labels[5].string.strip().strip('\n'), 'Status:', '6th issue field label text wrong')
        self.assertEqual(results[5].string.strip().strip('\n'), 'Новый', '6th issue field text wrong')

        self.assertEqual(labels[6].string.strip().strip('\n'), 'Mark:', '7th issue field label text wrong')
        self.assertEqual(results[6].string.strip().strip('\n'), '0 out of 10', '7th issue field text wrong')

        self.assertEqual(labels[7].string.strip().strip('\n'), 'Submit due:', '8th issue field label wrong')
        self.assertEqual(results[7].string.strip().strip('\n'), '', '8th issue field text wrong')

    def test_comment_with_student(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.student.username, password=self.student_password),
                        "Can't login via student")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        # post
        response = client.post(reverse(issues.views.upload),
                               {'comment': 'test_comment',
                                'files[]': '',
                                'issue_id': str(issue.id),
                                'form_name': 'comment_form',
                                'update_issue': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via student")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/student/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'student_last_name student_name',
                         'Wrong comment author name')
        self.assertEqual(history[0].find('div', 'history-body').find('div', 'not-sanitize').string.strip().strip('\n'),
                         'test_comment',
                         'Wrong comment text')

    def _extract_history_from_response(self, issue_page_response):
        html = BeautifulSoup(issue_page_response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)
        history = container.find('ul', 'history')('li')
        return history

    def test_empty_comment_with_student(self):
        client = self.client

        # login
        self.assertTrue(client.login(username=self.student.username, password=self.student_password),
                        "Can't login via student")

        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)

        # Get page before comment
        response_before = client.get(reverse(issues.views.issue_page,
                                             kwargs={'issue_id': issue.id}))

        # post
        response_after = client.post(reverse(issues.views.upload),
                                     {'comment': '',
                                      'files[]': '',
                                      'issue_id': str(issue.id),
                                      'form_name': 'comment_form',
                                      'update_issue': ''}, follow=True)

        history_before = self._extract_history_from_response(response_before)
        history_after = self._extract_history_from_response(response_after)

        self.assertEqual(history_before, history_after, 'History changed after empty comment')

    def test_deadline(self):
        client = self.client
        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)

        # login via teacher
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        # post comment via teacher
        self.task.deadline_time = datetime.now() - timedelta(days=5)
        self.task.save()
        response = client.post(reverse(issues.views.upload),
                               {'comment': 'test_comment_teacher',
                                'files[]': '',
                                'issue_id': str(issue.id),
                                'form_name': 'comment_form',
                                'update_issue': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 2, 'History len is not 2')
        self.assertIsNotNone(history[0].find('div', {'id': 'event_alert'}), 'No info message for deadline')
        self.assertNotIn('after_deadline',
                         history[1].find('div', 'history-body')['class'],
                         'Wrong deadline end comment color')

        # login via student
        self.assertTrue(client.login(username=self.student.username, password=self.student_password),
                        "Can't login via student")

        # post comment via student
        response = client.post(reverse(issues.views.upload),
                               {'comment': 'test_comment_student',
                                'files[]': '',
                                'issue_id': str(issue.id),
                                'form_name': 'comment_form',
                                'update_issue': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 3, 'History len is not 3')
        self.assertIsNotNone(history[0].find('div', {'id': 'event_alert'}), 'No info messege for deadline')
        self.assertNotIn('after_deadline',
                         history[1].find('div', 'history-body')['class'],
                         'Wrong deadline end comment color')
        self.assertIn('after_deadline',
                      history[2].find('div', 'history-body')['class'],
                      'Wrong deadline end comment color')

        # check if deadline greater
        # login via teacher
        self.assertTrue(client.login(username=self.teacher.username, password=self.teacher_password),
                        "Can't login via teacher")

        # get page
        self.task.deadline_time = datetime.now() + timedelta(days=5)
        self.task.save()
        response = client.get(reverse(issues.views.issue_page,
                                      kwargs={'issue_id': issue.id}))
        self.assertEqual(response.status_code, 200, "Can't get issue_page via teacher")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 2, 'History len is not 2')
        self.assertIsNone(history[0].find('div', {'id': 'event_alert'}), 'No info messege for deadline')
        self.assertNotIn('after_deadline',
                         history[0].find('div', 'history-body')['class'],
                         'Wrong deadline end comment color')
        self.assertNotIn('after_deadline',
                         history[1].find('div', 'history-body')['class'],
                         'Wrong deadline end comment color')

    @patch('anyrb.common.AnyRB.upload_review')
    def test_upload_review_with_student(self, mock_upload_review):
        client = self.client
        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        event_create_file = Event.objects.create(issue=issue, field=IssueField.objects.get(name='file'))
        File.objects.create(file=SimpleUploadedFile('test_rb.py', b'some text'), event=event_create_file)
        User.objects.create_user(username='anytask.monitoring', password='password')
        self.task.rb_integrated = True
        self.task.save()

        # login
        self.assertTrue(client.login(username=self.student.username, password=self.student_password),
                        "Can't login via teacher")

        # post rb error
        mock_upload_review.return_value = None
        response = client.post(reverse(issues.views.upload),
                               {'comment': 'test_comment',
                                'files[]': '',
                                'pk_test_rb.py': '1',
                                'issue_id': str(issue.id),
                                'form_name': 'comment_form',
                                'update_issue': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get upload via student")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/student/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'student_last_name student_name',
                         'Wrong comment author name')
        comment_body = history[0].find('div', 'history-body').find('div', 'not-sanitize').next
        self.assertEqual(comment_body.string.strip().strip('\n'),
                         'test_comment',
                         'Wrong comment text')
        comment_body = comment_body.next.next
        self.assertEqual(comment_body.string.strip().strip('\n'),
                         'Sending to RB failed',
                         'Wrong comment text about RB')
        comment_body = history[0].find('div', 'history-body').find('div', 'files')
        self.assertEqual(comment_body.a.string.strip().strip('\n'),
                         'test_rb.py',
                         'Wrong filename in comment')

        # post rb no error
        mock_upload_review.return_value = 1
        response = client.post(reverse(issues.views.upload),
                               {'comment': 'test_comment',
                                'files[]': '',
                                'pk_test_rb.py': '1',
                                'issue_id': str(issue.id),
                                'form_name': 'comment_form',
                                'update_issue': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get upload via student")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 2, 'History len is not 2')
        self.assertEqual(history[1].strong.a['href'],
                         '/users/student/',
                         'Wrong comment author link')
        self.assertEqual(history[1].strong.a.string.strip().strip('\n'),
                         'student_last_name student_name',
                         'Wrong comment author name')
        comment_body = history[1].find('div', 'history-body')
        self.assertEqual(comment_body.find('div', 'not-sanitize').next.string.strip().strip('\n'),
                         'test_comment',
                         'Wrong comment text')
        self.assertEqual(comment_body.find('div', 'not-sanitize').a.string.strip().strip('\n'),
                         u'Review request 1',
                         'Wrong comment text about RB')
        self.assertEqual(comment_body.find('div', 'files').a.string.strip().strip('\n'),
                         'test_rb.py',
                         'Wrong filename in comment')

        # changes from rb
        issue.set_byname('review_id', 1)
        response = client.post(reverse(anyrb.views.message_from_rb, kwargs={'review_id': '1'}),
                               {'author': 'teacher'}, follow=True)
        self.assertEqual(response.status_code, 201, "Can't get message_from_rb via student")

        response = client.get(reverse(issues.views.issue_page,
                                      kwargs={'issue_id': issue.id}))
        self.assertEqual(response.status_code, 200, "Can't get upload via student")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 3, 'History len is not 3')
        self.assertEqual(history[2].strong.a['href'],
                         '/users/teacher/',
                         'Wrong comment author link')
        self.assertEqual(history[2].strong.a.string.strip().strip('\n'),
                         'teacher_last_name teacher_name',
                         'Wrong comment author name')
        comment_body = history[2].find('div', 'history-body').strong
        self.assertEqual(comment_body.next.string.strip().strip('\n'),
                         'New comment',
                         'Wrong comment text')
        self.assertEqual(comment_body.a.string.strip().strip('\n'),
                         u'Review request 1',
                         'Wrong comment text about RB')

    @skipIf(not IS_S3_REACHABLE, "S3 seems misconfigured")
    def test_attached_file_in_s3(self):
        client = self.client
        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        event_create_file = Event.objects.create(issue=issue, field=IssueField.objects.get(name='file'))
        File.objects.create(file=SimpleUploadedFile('test_solution.c', b'main(){}'), event=event_create_file)
        self.task.rb_integrated = False
        self.task.save()

        call_command('s3migrate_issue_attachments', '--execute', '--do-rewrite-url')

        # login
        self.assertTrue(client.login(username=self.student.username, password=self.student_password),
                        "Can't login via teacher")

        response = client.post(reverse(issues.views.upload),
                               {'comment': 'test_comment',
                                'files[]': '',
                                'pk_test_solution.c': '1',
                                'issue_id': str(issue.id),
                                'form_name': 'comment_form',
                                'update_issue': ''}, follow=True)
        self.assertEqual(response.status_code, 200, "Can't get upload via student")
        self.assertEqual(len(response.redirect_chain), 1, "Must be redirect")

        html = BeautifulSoup(response.content, features="lxml")
        container = html.body.find('div', 'container', recursive=False)

        # history
        history = container.find('ul', 'history')('li')
        self.assertEqual(len(history), 1, 'History len is not 1')
        self.assertEqual(history[0].strong.a['href'],
                         '/users/student/',
                         'Wrong comment author link')
        self.assertEqual(history[0].strong.a.string.strip().strip('\n'),
                         'student_last_name student_name',
                         'Wrong comment author name')
        comment_body = history[0].find('div', 'history-body').find('div', 'not-sanitize').next
        self.assertEqual(comment_body.string.strip().strip('\n'),
                         'test_comment',
                         'Wrong comment text')
        comment_body = history[0].find('div', 'history-body').find('div', 'files')
        self.assertEqual(comment_body.a.string.strip().strip('\n'),
                         'test_solution.c',
                         'Wrong filename in comment')
        self.assertTrue(comment_body.a['href'].startswith(settings.AWS_S3_ENDPOINT_URL))


@skipIf(not IS_S3_REACHABLE, "S3 seems misconfigured")
class S3MigrateIssueAttachments(TestCase, SerializeMixin):
    maxDiff = None

    def setUp(self):
        self.teacher_password = 'password1'
        self.teacher = User.objects.create_user(username='teacher',
                                                password=self.teacher_password)
        self.teacher.first_name = 'teacher_name'
        self.teacher.last_name = 'teacher_last_name'
        self.teacher.save()

        self.student_password = 'password2'
        self.student = User.objects.create_user(username='student',
                                                password=self.student_password)
        self.student.first_name = 'student_name'
        self.student.last_name = 'student_last_name'
        self.student.save()

        self.year = Year.objects.create(start_year=2016)

        self.group = Group.objects.create(name='group_name',
                                          year=self.year)
        self.group.students = [self.student]
        self.group.save()

        self.course = Course.objects.create(name='course_name',
                                            year=self.year)
        self.course.groups = [self.group]
        self.course.teachers = [self.teacher]
        self.course.issue_fields = IssueField.objects.exclude(id=10).exclude(id=11)
        self.course.save()

        self.school = School.objects.create(name='school_name',
                                            link='school_link')
        self.school.courses = [self.course]
        self.school.save()

        self.task = Task.objects.create(title='task_title',
                                        course=self.course,
                                        score_max=10)

        self.s3_storage = S3OverlayStorage()

    def test_dry_run_rewrite_new_no_changes(self):
        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        event_create_file = Event.objects.create(issue=issue, field=IssueField.objects.get(name='file'))
        file = File.objects.create(file=SimpleUploadedFile('test_s3_issues.py', b'some text'), event=event_create_file)

        out = StringIO()
        call_command('s3migrate_issue_attachments', '--do-rewrite-url', stdout=out)

        expected_s3_path = S3OverlayStorage.append_s3_prefix(file.file.name)
        expected_stdout = ('''Note: Dry run\n'''
                           '''Note: uploaded: {}\n'''
                           '''Note: updating model: {}, {}''').format(
            expected_s3_path, file, expected_s3_path)
        file = File.objects.get(pk=file.pk)
        self.assertFalse(S3OverlayStorage.is_s3_stored(file.file.name))
        self.assertFalse(self.s3_storage.exists(expected_s3_path))
        self.assertEqual(expected_stdout, out.getvalue().strip())

    def test_dry_run_dont_rewrite_new_no_changes(self):
        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        event_create_file = Event.objects.create(issue=issue, field=IssueField.objects.get(name='file'))
        file = File.objects.create(file=SimpleUploadedFile('test_s3_issues.py', b'some text'),
                                   event=event_create_file)

        out = StringIO()
        call_command('s3migrate_issue_attachments', '--rewrite-only-existing', stdout=out)

        expected_s3_path = S3OverlayStorage.append_s3_prefix(file.file.name)
        expected_stdout = ('''Note: Dry run\n'''
                           '''Note: uploaded: {}''').format(
            expected_s3_path)
        file = File.objects.get(pk=file.pk)
        self.assertFalse(S3OverlayStorage.is_s3_stored(file.file.name))
        self.assertFalse(self.s3_storage.exists(expected_s3_path))
        self.assertEqual(expected_stdout, out.getvalue().strip())

    def test_upload_no_rewrite(self):
        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        event_create_file = Event.objects.create(issue=issue, field=IssueField.objects.get(name='file'))
        file = File.objects.create(file=SimpleUploadedFile('test_s3_issues.py', b'some text'), event=event_create_file)

        out = StringIO()
        call_command('s3migrate_issue_attachments', '--execute', stdout=out)

        file = File.objects.get(pk=file.pk)
        expected_s3_path = S3OverlayStorage.append_s3_prefix(file.file.name)
        expected_stdout = 'Note: uploaded: {}'.format(expected_s3_path)
        self.assertFalse(S3OverlayStorage.is_s3_stored(file.file.name))
        self.assertTrue(self.s3_storage.exists(expected_s3_path))
        self.assertEqual(expected_stdout, out.getvalue().strip())

    def test_upload_with_rewrite(self):
        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        event_create_file = Event.objects.create(issue=issue, field=IssueField.objects.get(name='file'))
        file = File.objects.create(file=SimpleUploadedFile('test_s3_issues.py', b'some text'), event=event_create_file)

        out = StringIO()
        call_command('s3migrate_issue_attachments', '--execute', '--do-rewrite-url', stdout=out)

        expected_s3_path = S3OverlayStorage.append_s3_prefix(file.file.name)
        expected_stdout = ('''Note: uploaded: {}\n'''
                           '''Note: updating model: {}, {}\n'''
                           '''Note: updated model: {}, {}''').format(
            expected_s3_path, file, expected_s3_path, file, expected_s3_path)
        file = File.objects.get(pk=file.pk)
        self.assertTrue(S3OverlayStorage.is_s3_stored(file.file.name))
        self.assertTrue(self.s3_storage.exists(expected_s3_path))
        self.assertEqual(expected_stdout, out.getvalue().strip())

    def test_rewrite_url_only_existing(self):
        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        event_create_file = Event.objects.create(issue=issue, field=IssueField.objects.get(name='file'))
        file = File.objects.create(file=SimpleUploadedFile('test_s3_issues.py', b'some text'), event=event_create_file)

        out = StringIO()
        call_command('s3migrate_issue_attachments', '--execute', '--rewrite-only-existing', stdout=out)

        file = File.objects.get(pk=file.pk)
        expected_s3_path = S3OverlayStorage.append_s3_prefix(file.file.name)
        self.assertFalse(S3OverlayStorage.is_s3_stored(file.file.name))
        self.assertTrue(self.s3_storage.exists(expected_s3_path))
        self.assertEqual('Note: uploaded: {}'.format(expected_s3_path),
                         out.getvalue().strip())

        out = StringIO()
        call_command('s3migrate_issue_attachments', '--execute', '--rewrite-only-existing', stdout=out)

        expected_s3_path = S3OverlayStorage.append_s3_prefix(file.file.name)
        expected_stdout = ('''Note: destination already exists: {}\n'''
                           '''Note: updating model: {}, {}\n'''
                           '''Note: updated model: {}, {}''').format(
            expected_s3_path, file, expected_s3_path, file, expected_s3_path)
        file = File.objects.get(pk=file.pk)
        self.assertTrue(S3OverlayStorage.is_s3_stored(file.file.name))
        self.assertTrue(self.s3_storage.exists(file.file.name))
        self.assertEqual(expected_stdout, out.getvalue().strip())

    def test_rewrite_url_only_existing_many_refs(self):
        issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
        event_create_file = Event.objects.create(issue=issue, field=IssueField.objects.get(name='file'))
        file_first = File.objects.create(
            file=SimpleUploadedFile('test_s3_issues.py', b'some text'), event=event_create_file)
        file_second = File.objects.get(pk=file_first.pk)
        file_second.pk = 0x1337
        file_second.save(force_insert=True)

        out = StringIO()
        call_command('s3migrate_issue_attachments', '--execute', '--rewrite-only-existing', stdout=out)

        file_first = File.objects.get(pk=file_first.pk)
        file_second = File.objects.get(pk=file_second.pk)
        for file in [file_first, file_second]:
            expected_s3_path = S3OverlayStorage.append_s3_prefix(file.file.name)
            self.assertFalse(S3OverlayStorage.is_s3_stored(file.file.name))
            self.assertTrue(self.s3_storage.exists(expected_s3_path))
            self.assertEqual(('''Note: uploaded: {}'''.format(expected_s3_path)),
                             out.getvalue().strip())

        out = StringIO()
        err = StringIO()
        call_command('s3migrate_issue_attachments', '--execute', '--rewrite-only-existing', stdout=out, stderr=err)

        for file in [file_first, file_second]:
            expected_s3_path = S3OverlayStorage.append_s3_prefix(file.file.name)
            expected_stdout = ('''Note: destination already exists: {}\n'''
                               '''Note: updating model: {}, {}\n'''
                               '''Note: updated model: {}, {}\n'''
                               ).format(
                expected_s3_path, file, expected_s3_path, file, expected_s3_path)
            expected_stdout = (expected_stdout * 2).strip()
            file = File.objects.get(pk=file.pk)
            cmd_out = out.getvalue().strip()
            self.assertEqual(expected_stdout, cmd_out)
            self.assertTrue(S3OverlayStorage.is_s3_stored(file.file.name))
            self.assertTrue(self.s3_storage.exists(file.file.name))

    def test_upload_archives(self):
        for ext in anyrb.unpacker.get_supported_extensions():
            fail_msg = 'Failed for extension: {}'.format(ext)
            issue = Issue.objects.create(task_id=self.task.id, student_id=self.student.id)
            event_create_file = Event.objects.create(issue=issue, field=IssueField.objects.get(name='file'))
            file = File.objects.create(
                file=SimpleUploadedFile('test_s3_issues.{}'.format(ext), b'some binary archive'),
                event=event_create_file)

            out = StringIO()
            call_command('s3migrate_issue_attachments', '--execute', '--do-rewrite-url', stdout=out)

            expected_s3_path = S3OverlayStorage.append_s3_prefix(file.file.name)
            expected_stdout = ('''Note: uploaded: {}\n'''
                               '''Note: updating model: {}, {}\n'''
                               '''Note: updated model: {}, {}''').format(
                expected_s3_path, file, expected_s3_path, file, expected_s3_path)
            file = File.objects.get(pk=file.pk)
            self.assertTrue(
                S3OverlayStorage.is_s3_stored(file.file.name),
                fail_msg)
            self.assertTrue(
                self.s3_storage.exists(expected_s3_path),
                fail_msg)
            self.assertEqual(
                expected_stdout,
                out.getvalue().strip(),
                fail_msg + out.getvalue().strip())

            issue.delete()
            event_create_file.delete()
            file.delete()
