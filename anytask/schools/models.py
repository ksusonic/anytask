from django.db import models
from django.urls import reverse
from courses.models import Course


# Create your models here.

class School(models.Model):
    name = models.CharField(max_length=191, db_index=True, null=False, blank=False)
    link = models.CharField(max_length=191, db_index=False, null=False, blank=False)
    is_active = models.BooleanField(db_index=True, null=False, blank=False, default=True)
    courses = models.ManyToManyField(Course, blank=True)

    def __str__(self):
        return str(self.name)

    def get_full_name(self):
        return str(self.name)

    def get_absolute_url(self):
        return reverse('schools.views.school_page', args=[str(self.link)])
