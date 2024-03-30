from django.shortcuts import render
from schools.models import School

ROBOTS_TXT = """User-agent: *
Allow: /
Clean-param: next /accounts/login/
"""

def index(request):
    schools = School.objects.all().filter(is_active=True).order_by('name')

    # current_year = get_current_year()
    # courses = Course.objects.filter(is_active=True).order_by('name')
    # archive_courses = Course.objects.exclude(is_active=True).order_by('year', 'name')

    context = {
        'schools': schools,
    }

    return render(request, 'schools_page.html', context)


def archive_index(request):
    schools = School.objects.all().filter(is_active=False).order_by('name')

    context = {
        'schools': schools,
    }

    return render(request, 'archived_schools_page.html', context)


def robotstxt_view(request):
    return HttpResponse(ROBOTS_TXT, content_type="text/plain")
